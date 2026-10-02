from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
import api
import computer_controller as controller
import model_tools
import safety
from memory import MemoryStore
from tool_broker import ToolBroker
from test_support import IsolatedSafetyTestCase
import test_computer_controller


class ScrollProposalTests(IsolatedSafetyTestCase):
    def context(self,scope='master:1'):
        snapshot=test_computer_controller.ControllerTests.snapshot(self)
        snapshot['controls'][0].update(name='Playlist pane',scrollable=True)
        reference=controller.issue_reference(snapshot,scope,purpose='context')
        return controller.window_context(reference,scope)['action_context']

    def call(self,**changes):
        arguments=dict(pane='pane_1',direction='down',confidence=.97)
        arguments.update(changes)
        return SimpleNamespace(function=SimpleNamespace(name='scroll_control',arguments=arguments))

    def test_proposal_never_sends_input_and_approval_reuses_the_same_controller(self):
        context=self.context()
        broker=ToolBroker(Mock())
        with patch.object(controller,'run_worker') as worker:
            proposal=model_tools.run_calls([self.call()],'scroll the playlist down',Mock(),broker,action_context=context)[0]
            self.assertEqual(proposal['status'],'approval_required')
            self.assertFalse(proposal['persistent_eligible'])
            worker.assert_not_called()
            with self.assertRaises(PermissionError):
                broker.scroll_control(proposal['reference'],context['scope'],proposal['control_id'],'scroll_down')
            worker.assert_not_called()
            worker.return_value=dict(app='Spotify',action='scroll_down',indicator_shown=True,indicator_completed=True,
                                     action_attempted=True,outcome='verified',before=10,after=20)
            result=broker.scroll_control(proposal['reference'],context['scope'],proposal['control_id'],'scroll_down',approved=True)
            self.assertEqual(result['outcome'],'verified')
            worker.assert_called_once()
            with self.assertRaises(PermissionError): controller.propose_scroll(context,'pane_1','down')

    def test_model_cannot_supply_authority_or_unobserved_targets(self):
        context=self.context()
        for changes in ({'reference':'a'*64},{'pane':'other'},{'direction':'click'},
                        {'pane':{}},{'confidence':True},{'confidence':float('nan')}):
            with self.subTest(changes=changes), patch.object(controller,'run_worker') as worker:
                with self.assertRaises((PermissionError,ValueError)):
                    model_tools.run_calls([self.call(**changes)],'scroll down',Mock(),ToolBroker(Mock()),action_context=context)
                worker.assert_not_called()
        with self.assertRaises(PermissionError):
            model_tools.run_calls([self.call()],'scroll down',Mock(),ToolBroker(Mock()))
        with self.assertRaises(PermissionError):
            model_tools.run_calls([self.call()],'do not scroll down',Mock(),ToolBroker(Mock()),action_context=context)
        result=model_tools.run_calls([self.call(confidence=.4)],'scroll down',Mock(),ToolBroker(Mock()),action_context=context)
        self.assertEqual(result[0]['status'],'clarification_required')

    def test_duplicate_labels_keep_distinct_observed_roles_and_regions(self):
        snapshot=test_computer_controller.ControllerTests.snapshot(self)
        root=snapshot['controls'][0]
        root.update(name='Playlist',scrollable=True,type=50030,bounds=[0,0,1000,800])
        snapshot['controls'].append(dict(root,id='c'*64,context_id='f'*64,type=50026,bounds=[300,20,700,750]))
        reference=controller.issue_reference(snapshot,'master:1',purpose='context')
        panes=controller.window_context(reference,'master:1')['action_context']['panes']
        self.assertEqual(panes['pane_1']['region'],'whole window')
        self.assertEqual(panes['pane_2']['region'],'center')
        self.assertEqual(panes['pane_2']['role'],'group')
        self.assertEqual(panes['pane_1']['label'],panes['pane_2']['label'])

    def test_scope_expiry_stop_and_multiple_steps_fail_without_input(self):
        context=self.context()
        with self.assertRaises(PermissionError): controller.propose_scroll(dict(context,scope='side:1'),'pane_1','down')
        with self.assertRaises(PermissionError):
            model_tools.run_calls([self.call(),self.call(direction='up')],'scroll down then up',Mock(),ToolBroker(Mock()),action_context=context)
        snapshot=controller._references[context['reference']][1]
        snapshot['captured_at']-=61
        result=model_tools.run_calls([self.call()],'scroll down',Mock(),ToolBroker(Mock()),action_context=context)
        self.assertEqual(result[0]['status'],'clarification_required')
        self.assertIn('inspect',result[0]['message'])
        context=self.context()
        safety.safety.stop('invalidate'); safety.safety.resume()
        with self.assertRaises(safety.StoppedError): controller.propose_scroll(context,'pane_1','down')

    def test_side_chat_http_proposal_cannot_execute_or_write_memory(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            store=MemoryStore(Path(folder)/'test.db'); store.initialize(approved=True)
            context=self.context('draft:1')
            # Issue a fresh context attachment; model receives no action token.
            snapshot=controller._references[context['reference']][1]
            reference=controller.issue_reference(snapshot,'draft:1',purpose='context')
            response=SimpleNamespace(message=SimpleNamespace(content='I scrolled it.',tool_calls=[self.call()]))
            with patch.object(api,'memory',store),patch.object(api,'broker',ToolBroker(store)), \
                 patch.object(api,'call_model',AsyncMock(return_value=response)) as model,patch.object(controller,'run_worker') as worker:
                client=TestClient(api.app,base_url='http://127.0.0.1:8000')
                result=client.post('/chat',json={'message':'scroll the playlist down','new_side':True,
                                              'window_reference':reference,'workspace_scope':'draft:1',
                                              '_window_action_context':{'reference':'forged'}})
                self.assertEqual(result.status_code,200,result.text)
                proposal=result.json()['tool_results'][0]
                self.assertEqual(proposal['status'],'approval_required')
                self.assertNotIn('I scrolled it',result.json()['reply'])
                worker.assert_not_called()
                self.assertEqual(store.list_facts(),[])
                self.assertNotIn(proposal['reference'],str(store.conversation_history(result.json()['conversation_id'])))
                schema=model.call_args.kwargs['tools'][0]['function']['parameters']
                self.assertEqual(schema['properties']['pane']['enum'],['pane_1'])
                self.assertNotIn('reference',schema['properties'])
                body={key:proposal[key] for key in ('reference','workspace_scope','control_id','action','safety_epoch')}
                self.assertEqual(client.post('/tools/scroll-control',json=dict(body,decision='always_allow')).status_code,422)
                safety.safety.stop('pending proposal'); safety.safety.resume()
                self.assertEqual(client.post('/tools/scroll-control',json=dict(body,decision='allow_once')).status_code,423)

