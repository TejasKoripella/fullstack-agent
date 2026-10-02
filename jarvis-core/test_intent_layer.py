from intent_layer import normalize_intent, resolve_target, ClarificationNeeded
from test_support import IsolatedSafetyTestCase
from unittest.mock import Mock,patch
from types import SimpleNamespace
import model_tools
import safety

class IntentLayerTests(IsolatedSafetyTestCase):
    def test_playback_resolves_app_mentions_and_safe_recent_references(self):
        targets=['Spotify Play','Spotify Pause']
        proposal={'action':'spotify_playback','target':'Spotify Pause','confidence':.98}
        for text,context in [('pause Spotify',None),('pause spotfy',None),('pause it','Spotify'),('pause it','Default playlist')]:
            self.assertEqual(normalize_intent(proposal,text,targets,context)['target'],'Spotify Pause')
        for text,context in [('pause it',None),('pause it','Chrome'),('play Spotify','Spotify'),('pause Chrome','Spotify')]:
            with self.assertRaises(ClarificationNeeded): normalize_intent(proposal,text,targets,context)
        self.assertTrue(model_tools.action_request('spotify pls'))
    def test_typo_resolution_and_current_turn_evidence(self):
        for typo in ('spotfy','spoitfy','spotify'):
            self.assertEqual(resolve_target(typo,['Spotify','Chrome']),'Spotify')
            intent=normalize_intent({'action':'open_app','target':'Spotify','confidence':.97},'could u pull up '+typo,['Spotify','Chrome'])
            self.assertEqual(intent['target'],'Spotify')
        self.assertEqual(resolve_target('chrom',['Spotify','Chrome']),'Chrome')
        self.assertEqual(resolve_target('vs cod',['Jarvis project']),'Jarvis project')
    def test_ambiguous_unknown_low_confidence_and_paths_fail_closed(self):
        for raw in ('spot','nonsense',r'C:\Users\vijay koripella\spotify.exe','../chrome','spotify.exe /run'):
            with self.assertRaises(ClarificationNeeded): resolve_target(raw,['Spotify','Spotify Web','Chrome'])
        for confidence in (.5,float('nan'),True):
            with self.assertRaises(ClarificationNeeded): normalize_intent({'action':'open_app','target':'Spotify','confidence':confidence},'Open Spotify',['Spotify'])
        with self.assertRaises(ClarificationNeeded): normalize_intent({'action':'open_app','target':'Spotify','confidence':.99},'Open Chrome',['Spotify','Chrome'])

    def test_context_is_chat_scoped_unambiguous_expiring_and_epoch_scoped(self):
        store=Mock(db_path='intent-test')
        result={'target':'Spotify','status':'executed','action_type':'open_app'}
        model_tools.remember_tools(store,1,[result])
        self.assertEqual(model_tools.recent_target(store,1),'Spotify')
        self.assertIsNone(model_tools.recent_target(store,2))
        self.assertEqual(normalize_intent({'action':'open_app','target':'Spotify','confidence':.98},'bring that back up',['Spotify'],model_tools.recent_target(store,1))['target'],'Spotify')
        with patch('model_tools.time.monotonic',return_value=10**12): self.assertIsNone(model_tools.recent_target(store,1))
        model_tools.remember_tools(store,1,[result,{**result,'target':'Chrome'}])
        self.assertIsNone(model_tools.recent_target(store,1))
        model_tools.remember_tools(store,1,[result])
        safety.safety.stop('stop intent')
        with self.assertRaises(safety.StoppedError): model_tools.recent_target(store,1)
        safety.safety.resume()
        self.assertIsNone(model_tools.recent_target(store,1))

    def test_low_confidence_batch_and_stop_do_not_dispatch(self):
        calls=[SimpleNamespace(function=SimpleNamespace(name='open_app',arguments={'target':'Spotify','confidence':.98})),
               SimpleNamespace(function=SimpleNamespace(name='open_app',arguments={'target':'Chrome','confidence':.3}))]
        with patch.object(model_tools,'dispatch') as dispatch:
            results=model_tools.run_calls(calls,'Open Spotify and Chrome',Mock(),Mock())
            self.assertEqual(results[0]['status'],'clarification_required')
            dispatch.assert_not_called()
            safety.safety.stop('before intent')
            with self.assertRaises(safety.StoppedError): model_tools.run_calls(calls,'Open Spotify and Chrome',Mock(),Mock())
            dispatch.assert_not_called()
