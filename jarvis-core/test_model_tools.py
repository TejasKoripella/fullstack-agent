import unittest
from test_support import IsolatedSafetyTestCase
from types import SimpleNamespace
from unittest.mock import Mock, patch
import model_tools


class ModelToolTests(IsolatedSafetyTestCase):
    def test_read_only_inspection_is_explicit_and_uses_existing_dispatch(self):
        text = 'look at spotfy'
        self.assertEqual([tool['function']['name'] for tool in model_tools.definitions(text)], ['inspect_app'])
        call = self.call(name='inspect_app', target='Spotify', confidence=.97)
        with patch.object(model_tools, 'dispatch', return_value={'target': 'Spotify', 'status': 'approval_required'}) as dispatch:
            result = model_tools.run_calls([call], text, Mock(), Mock())
            dispatch.assert_called_once()
            self.assertEqual(result[0]['status'], 'approval_required')
            for denied in ('Open Spotify', "Don't inspect Spotify", 'What if I inspect Spotify?', 'What tools are able to inspect Spotify?'):
                with self.assertRaises(PermissionError): model_tools.run_calls([call], denied, Mock(), Mock())
            self.assertEqual(dispatch.call_count, 1)
        self.assertEqual([tool['function']['name'] for tool in model_tools.definitions('inspect Spotify without opening it')], ['inspect_app'])

    def test_search_first_compound_opening_is_explicit_and_negation_safe(self):
        text='Find robotics filenames in Documents and open Spotify'
        self.assertIn('open_app',{tool['function']['name'] for tool in model_tools.definitions(text)})
        broker=Mock()
        broker.find_documents.return_value={'matches':[],'partial':False}
        with patch.object(model_tools,'dispatch',return_value={'target':'Spotify','status':'approval_required'}) as dispatch:
            model_tools.run_calls([self.call(name='find_documents',query='robotics'),self.call()],text,Mock(),broker)
            dispatch.assert_called_once()
            dispatch.reset_mock()
            for denied in ('What if I find robotics in Documents and open Spotify?',
                           'Find robotics in Documents and do not open Spotify',
                           'Find robotics in Documents without opening Spotify'):
                with self.assertRaises(PermissionError):
                    model_tools.run_calls([self.call()],denied,Mock(),broker)
            dispatch.assert_not_called()
    def test_mixed_search_and_open_preserve_separate_outcomes(self):
        text='Open Spotify and find robotics filenames in Documents'
        broker=Mock()
        broker.find_documents.return_value={'matches':[{'path':'robotics.txt'}],'partial':False}
        with patch.object(model_tools,'dispatch',return_value={'target':'Spotify','status':'approval_required'}) as dispatch:
            result=model_tools.run_calls([self.call(),self.call(name='find_documents',query='robotics')],text,Mock(),broker)
            dispatch.assert_called_once()
            output=model_tools.result_text(result)
            self.assertIn('pull up Spotify',output)
            self.assertIn('robotics.txt',output)
            self.assertNotIn('action denied',output)
        self.assertTrue(model_tools.action_request('Pull up Spotify'))
        self.assertFalse(model_tools.document_search_request('What happens if I open Spotify and find robotics in Documents?'))
    def test_document_search_requires_current_query_and_never_opens_results(self):
        call = self.call(name="find_documents", query="robotics")
        broker = Mock()
        broker.find_documents.return_value = {"matches": [{"path": "robotics.txt"}], "partial": False}
        results = model_tools.run_calls([call,call], "Find robotics files in Documents", Mock(), broker)
        broker.find_documents.assert_called_once_with("robotics",approved=True)
        self.assertIn("File contents were not read",model_tools.result_text(results))
        self.assertEqual(results[0]['status'],'searched')
        for text in ("What do you remember about robotics?", "Do not find robotics in Documents", "Find math in Documents"):
            with self.assertRaises(PermissionError):
                model_tools.run_calls([call],text,Mock(),broker)
        self.assertEqual([tool['function']['name'] for tool in model_tools.definitions('Find robotics in Documents')],['find_documents'])

    def call(self, name="open_app", **arguments):
        return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments or {"target": "Spotify"}))

    def test_existing_tools_only_and_no_tools_for_context_questions(self):
        self.assertEqual(model_tools.definitions("What apps can you open?"), [])
        self.assertEqual(model_tools.definitions("Don't open Spotify"), [])
        self.assertEqual({t["function"]["name"] for t in model_tools.definitions("Launch Spotify")}, set(model_tools.ACTION_TARGETS) - {"spotify_playback", "open_site", "inspect_app", "focus_app"})

    def test_focus_is_only_offered_for_a_current_explicit_focus_request(self):
        self.assertEqual([t['function']['name'] for t in model_tools.definitions('focus spotfy')], ['focus_app'])
        self.assertIn('focus_app', {t['function']['name'] for t in model_tools.definitions('bring Spotify to the front')})
        call = self.call(name='focus_app', target='Spotify', confidence=.97)
        with patch.object(model_tools, 'dispatch', return_value={'status': 'approval_required', 'target': 'Spotify'}) as dispatch:
            model_tools.run_calls([call], 'focus spotfy', Mock(), Mock())
            dispatch.assert_called_once()
            for text in ('Open Spotify', "Don't focus Spotify", 'What if I focus Spotify?'):
                with self.assertRaises(PermissionError): model_tools.run_calls([call], text, Mock(), Mock())
            self.assertEqual(dispatch.call_count, 1)

    def test_spotify_defaults_to_installed_app_web_requires_explicit_request(self):
        self.assertNotIn("open_site", {t["function"]["name"] for t in model_tools.definitions("Open Spotify")})
        self.assertIn("open_site", {t["function"]["name"] for t in model_tools.definitions("Open Spotify Web")})
        with patch.object(model_tools, "dispatch") as dispatch:
            with self.assertRaises(PermissionError):
                model_tools.run_calls([self.call(name="open_site", target="Spotify Web")], "Open Spotify", Mock(), Mock())
            dispatch.assert_not_called()

    def test_parser_security_permission_dispatch_once(self):
        with patch.object(model_tools, "dispatch", return_value={"status": "executed", "target": "Spotify"}) as dispatch:
            results = model_tools.run_calls([self.call(), self.call()], "Open Spotify", Mock(), Mock())
            dispatch.assert_called_once()
        self.assertEqual(model_tools.result_text(results), "Sure, I’ll pull up Spotify.")

    def test_no_model_approval_or_unrequested_targets(self):
        with patch.object(model_tools, "dispatch") as dispatch:
            for call, text in [(self.call(target="Spotify", decision="always_allow"), "Open Spotify"),
                               (self.call(), "What does my saved memory say?"),
                               (self.call(target=r"C:\Users\vijay koripella"), "Open Spotify")]:
                with self.assertRaises((ValueError, PermissionError)):
                    model_tools.run_calls([call], text, Mock(), Mock())
            dispatch.assert_not_called()

    def test_compound_requests_validate_whole_batch_before_execution(self):
        calls=[self.call(name='open_resource',target='Jarvis project'),self.call(name='open_resource',target='Jarvis verification')]
        with patch.object(model_tools,'dispatch',return_value={'status':'approval_required'}) as dispatch:
            model_tools.run_calls(calls,'Open Jarvis project and Jarvis verification',Mock(),Mock())
            self.assertEqual(dispatch.call_count,2)
            dispatch.reset_mock()
            with self.assertRaises(PermissionError):
                model_tools.run_calls(calls,'Open Jarvis project',Mock(),Mock())
            dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
