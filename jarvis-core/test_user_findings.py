"""Regressions for the reported app-control failures; live UI evidence is separate."""
from contextlib import nullcontext, contextmanager
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
from unittest.mock import Mock, patch
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
import api

import computer_observation as observation
import model_tools
import permissions
import safety
import window_glow
import capability_registry
from intent_layer import normalize_intent, ClarificationNeeded
from memory import MemoryStore
from test_support import IsolatedSafetyTestCase
from tool_broker import ToolBroker
from tool_responses import receipt


class UserFindingsTests(IsolatedSafetyTestCase):
    def test_registry_and_permissions_share_trusted_effect_classification(self):
        for app in capability_registry.application_capabilities():
            for capability in app['capabilities']:
                if capability['tool'] is None: continue
                self.assertEqual(capability['persistent_eligible'],
                                 capability_registry.persistent_permission_eligible(capability['tool']))
        for action in ('purchase','send_message','delete','click','type','unknown'):
            self.assertFalse(capability_registry.persistent_permission_eligible(action))
        with self.assertRaises(TypeError):
            capability_registry.ACTION_CONTRACTS['purchase']=capability_registry.ActionContract('reversible','exact_target',True)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            store=MemoryStore(Path(folder)/'test.db'); store.initialize(approved=True)
            store.grant_permission('open_app','Spotify',approved=True)
            contracts=dict(capability_registry.ACTION_CONTRACTS)
            # Even a mistakenly persistent consequential declaration cannot use
            # an existing grant; classification must still require fresh consent.
            contracts['open_app']=capability_registry.ActionContract('consequential','exact_target',True)
            broker=Mock()
            with patch.object(capability_registry,'ACTION_CONTRACTS',contracts):
                result=permissions.dispatch(store,broker,'open_app','Spotify')
                self.assertEqual(result['status'],'approval_required')
                self.assertFalse(result['persistent_eligible'])
                with self.assertRaises(PermissionError):
                    permissions.dispatch(store,broker,'open_app','Spotify','always_allow')
                broker.open_packaged_app.assert_not_called()

    def test_plain_model_promise_cannot_replace_a_real_tool_request(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            store=MemoryStore(Path(folder)/'test.db'); store.initialize(approved=True)
            message=SimpleNamespace(content='Your playlist is playing; approval is required.',tool_calls=[])
            response=SimpleNamespace(message=message)
            with patch.object(api,'memory',store),patch.object(api,'call_model',AsyncMock(return_value=response)), \
                    patch.object(api,'run_calls') as run:
                result=TestClient(api.app,base_url='http://127.0.0.1:8000').post('/chat',json={'message':'put my playlist on','new_side':True})
                self.assertEqual(result.status_code,200)
                self.assertIn('couldn’t start',result.json()['reply'])
                self.assertNotIn('is playing',result.json()['reply'])
                self.assertEqual(result.json()['tool_results'],[])
                run.assert_not_called()

    def test_approved_ui_receipt_updates_only_its_chat_context(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            store=MemoryStore(Path(folder)/'test.db'); store.initialize(approved=True)
            master=store.master_conversation()['id']
            result={'status':'executed','action_type':'spotify_playback','target':'Spotify Pause'}
            with patch.object(api,'memory',store),patch.object(api,'dispatch',return_value=result):
                api.dispatch_tool(api.DispatchRequest(action_type='spotify_playback',target='Spotify Pause',workspace_scope=str(master)+':7'))
            self.assertEqual(model_tools.recent_target(store,master),'Spotify Pause')
            self.assertIsNone(model_tools.recent_target(store,master+1))

    def test_media_reference_does_not_reselect_playlist_after_pause(self):
        proposal={'action':'spotify_playback','target':'Default playlist','confidence':.98}
        targets=permissions.ACTION_TARGETS['spotify_playback']()
        self.assertEqual(normalize_intent(proposal,'play it',targets,'Spotify Pause')['target'],'Spotify Play')
        self.assertEqual(normalize_intent(proposal,'play my playlist',targets,'Spotify Pause')['target'],'Default playlist')
        with self.assertRaises(ClarificationNeeded): normalize_intent(proposal,'play it',targets,None)

    def test_tool_proposal_cannot_imitate_old_acknowledgements(self):
        messages=[{'role':'system','content':'Security rules and recent validated target: Spotify'},
                  {'role':'user','content':'Untrusted recalled memory'},
                  {'role':'assistant','content':'Default playlist requires approval; I will request it.'},
                  {'role':'user','content':'put my playlist on'}]
        original=[dict(item) for item in messages]
        self.assertEqual(model_tools.proposal_messages(messages,model_tools.definitions('put my playlist on')),[messages[0],messages[-1]])
        self.assertEqual(messages,original)
        self.assertIs(model_tools.proposal_messages(messages,[]),messages)

    def test_resource_grant_is_exact_revocable_audited_and_cannot_override_stop(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            store=MemoryStore(Path(folder)/'test.db'); store.initialize(approved=True)
            broker=ToolBroker(store)
            with patch('tool_broker.require_browser_launch_context'), patch('tool_broker.os.startfile') as launch, \
                    patch('permissions.action_glow',return_value=nullcontext()):
                pending=permissions.dispatch(store,broker,'open_resource','Jarvis project')
                self.assertTrue(pending['persistent_eligible'])
                permissions.dispatch(store,broker,'open_resource','Jarvis project','allow_once')
                self.assertFalse(store.has_permission('open_resource','Jarvis project'))
                self.assertEqual(permissions.dispatch(store,broker,'open_resource','Jarvis project')['status'],'approval_required')
                permissions.dispatch(store,broker,'open_resource','Jarvis project','always_allow')
                self.assertEqual(permissions.dispatch(store,broker,'open_resource','Jarvis project')['source'],'persistent')
                self.assertEqual(permissions.dispatch(store,broker,'open_resource','Default playlist')['status'],'approval_required')
                with store._connect(readonly=True) as db:
                    self.assertTrue(db.execute("SELECT 1 FROM audit_log WHERE authorization_source='persistent' AND security_result='passed'").fetchone())
                count=launch.call_count
                safety.safety.stop('permission test')
                with self.assertRaises(safety.StoppedError): permissions.dispatch(store,broker,'open_resource','Jarvis project')
                self.assertEqual(launch.call_count,count)
                safety.safety.resume()
                store.revoke_permission(store.list_permissions()[0]['id'],approved=True)
                self.assertEqual(permissions.dispatch(store,broker,'open_resource','Jarvis project')['status'],'approval_required')
                for action,target in [('purchase','anything'),('open_resource',r'C:\Users\vijay koripella\secret.txt')]:
                    with self.assertRaises(PermissionError): permissions.dispatch(store,broker,action,target,'always_allow')
                self.assertEqual(launch.call_count,count)

    def test_cancelled_approval_cannot_save_permission_after_stop_or_resume(self):
        for resume in (False,True):
            with self.subTest(resume=resume), tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
                safety.safety.resume()
                store=MemoryStore(Path(folder)/'test.db'); store.initialize(approved=True)
                broker=Mock()
                original=permissions.validate
                def validate_then_stop(action,target):
                    validated=original(action,target)
                    safety.safety.stop('cancel approval during target validation')
                    if resume: safety.safety.resume()
                    return validated
                with patch.object(permissions,'validate',side_effect=validate_then_stop):
                    with self.assertRaises(safety.StoppedError):
                        permissions.dispatch(store,broker,'spotify_playback','Spotify Play','always_allow')
                self.assertFalse(store.has_permission('spotify_playback','Spotify Play'))
                broker.spotify_playback.assert_not_called()
                with store._connect(readonly=True) as db:
                    self.assertTrue(db.execute("SELECT 1 FROM audit_log WHERE execution_result='cancelled'").fetchone())

    def test_stop_during_permission_insert_rolls_back_the_grant(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as folder:
            store=MemoryStore(Path(folder)/'test.db'); store.initialize(approved=True)
            connect=store._connect
            @contextmanager
            def interrupted_connection(*args,**kwargs):
                with connect(*args,**kwargs) as db:
                    proxy=Mock(wraps=db)
                    def insert_then_cancel(sql,parameters):
                        result=db.execute(sql,parameters)
                        if 'INSERT INTO permissions' in sql:
                            safety.safety.stop('during permission write')
                            safety.safety.resume()
                        return result
                    proxy.execute.side_effect=insert_then_cancel
                    yield proxy
            with patch.object(store,'_connect',side_effect=interrupted_connection):
                with self.assertRaises(safety.StoppedError):
                    permissions.dispatch(store,Mock(),'spotify_playback','Spotify Play','always_allow')
            self.assertFalse(store.has_permission('spotify_playback','Spotify Play'))
            with store._connect(readonly=True) as db:
                self.assertTrue(db.execute("SELECT 1 FROM audit_log WHERE execution_result='cancelled'").fetchone())

    def test_playlist_play_and_navigation_are_distinct_broker_targets(self):
        def call(name): return SimpleNamespace(function=SimpleNamespace(name=name,arguments={'target':'Default playlist','confidence':.99}))
        for text in ('play my playlist','put my playlist on','start my playlist','play my default playlist'):
            offered={item['function']['name'] for item in model_tools.definitions(text)}
            self.assertIn('spotify_playback',offered)
            with patch('model_tools.dispatch',return_value={'status':'approval_required'}) as dispatch:
                model_tools.run_calls([call('spotify_playback')],text,Mock(),Mock())
                dispatch.assert_called_once_with(dispatch.call_args.args[0],dispatch.call_args.args[1],'spotify_playback','Default playlist')
        with patch('model_tools.dispatch') as dispatch:
            model_tools.run_calls([call('open_resource')],'open my playlist',Mock(),Mock())
            self.assertEqual(dispatch.call_args.args[2:4],('open_resource','Default playlist'))
            with self.assertRaises(PermissionError): model_tools.run_calls([call('spotify_playback')],'open my playlist',Mock(),Mock())

    def test_multi_ack_and_unverified_playback_never_claim_success(self):
        results=[{'action_type':'open_resource','target':'Jarvis project','status':'approval_required'},
                 {'action_type':'spotify_playback','target':'Default playlist','status':'approval_required'}]
        self.assertEqual(model_tools.result_text(results),'Got it, I’ll open your Jarvis project and put your playlist on.')
        unverified=dict(results[1],status='executed',resource_kind='playlist',playback_confirmed=False)
        self.assertIn('couldn’t confirm',receipt(unverified))
        self.assertNotIn('is playing',receipt(unverified))
        self.assertEqual(receipt(dict(unverified,playback_confirmed=True)),'Your playlist is playing.')
        self.assertNotIn('approval',model_tools.result_text(results))

    def test_active_control_has_no_flash_timeout(self):
        border=window_glow.NativeBorder('spotify.exe',action_lifecycle=True)
        # Long execution and verification phases must never hit the post-action cap.
        self.assertFalse(border.action_lifetime_complete(100,1,now=100000))
        with patch('window_glow.time.monotonic',return_value=100): border.finish()
        self.assertFalse(border.action_lifetime_complete(0,1,now=100.5))
        self.assertTrue(border.action_lifetime_complete(1.1,1,now=101.2))
        with patch('window_glow.time.monotonic',return_value=200): border.finish()
        self.assertEqual(border.finished_at,100,'Repeated finish must not restart the indicator')
        self.assertTrue(border.action_lifetime_complete(0,None,now=102.1))

    def test_decorative_overlay_outlives_return_and_remains_stoppable(self):
        entered=threading.Event(); after_finish=threading.Event()
        def native(border):
            entered.set()
            border.action_finished.wait(.5)
            after_finish.set()
            border.stop_event.wait(1)
        with patch('window_glow.ctypes.WinDLL',return_value=Mock()), \
                patch('window_glow.physical_pixel_context',return_value=nullcontext()), \
                patch.object(window_glow.NativeBorder,'_run_native',native):
            with window_glow.action_glow('open_app','Spotify'):
                self.assertTrue(entered.wait(.5))
                with window_glow._active_lock: border=next(iter(window_glow._active))
            self.assertTrue(after_finish.wait(.5))
            self.assertTrue(border.thread.is_alive())
            self.assertGreater(safety.safety.status()['active_operations'],0)
            safety.safety.stop('post-focus stop')
            border.thread.join(.5)
            self.assertFalse(border.thread.is_alive())
            self.assertTrue(border.stop_event.is_set())
            self.assertNotIn(border,window_glow._active)

    def test_playlist_invokes_only_main_play_button_once_and_verifies(self):
        title="Tejas' Playlist"; view=title+' - playlist by Tejas Koripella | Spotify'
        element=Mock(CurrentProcessId=2,CurrentName='Play '+title,CurrentControlType=50000,
                     CurrentIsPassword=False,CurrentIsOffscreen=False,CurrentIsEnabled=True)
        element.CurrentBoundingRectangle=SimpleNamespace(left=1,top=1,right=9,bottom=9)
        pattern=Mock()
        pattern.Invoke.side_effect=lambda: setattr(element,'CurrentName','Pause '+title)
        element.GetCurrentPattern.return_value.QueryInterface.return_value=pattern
        root=Mock(CurrentProcessId=2); root.GetRuntimeId.return_value=(3,)
        automation=Mock(); automation.ElementFromHandle.return_value=root
        control={'id':'id','context_id':'ctx','name':'Play '+title,'type':50000,'enabled':True,'offscreen':False}
        snapshot={'window_id':'window','controls':[control]}
        context=(1,2,4,(3,),automation,element)
        def observe(target,locate=None): return (snapshot,context) if locate else snapshot
        def border(*args,**kwargs): return Mock(run=kwargs['on_ready'])
        with patch('tool_broker.resource_path',return_value=('playlist','spotify:playlist:6chnzVM2lWXKhcvDSia4JW')), \
                patch('tool_broker.known_resources',return_value={'Default playlist':{'view_name':view}}), \
                patch.object(observation,'focus'), patch.object(observation,'observe',observe), \
                patch.object(observation,'playlist_parent',return_value=True), \
                patch.object(observation,'select_window',return_value=(1,2,'Spotify',4)), \
                patch.object(observation,'current_control_context',return_value='ctx'), \
                patch('window_glow.NativeBorder',border), patch('spotify_media.spotify_status',return_value={'playing':True}):
            result=observation.play_playlist('Default playlist')
            self.assertTrue(result['playback_confirmed'])
            self.assertTrue(result['action_attempted'])
            pattern.Invoke.assert_called_once()
            self.assertEqual(element.GetCurrentPattern.call_args.args,(10000,))
