from unittest.mock import Mock,patch
from types import SimpleNamespace
import model_tools
import window_glow
import safety
from tool_responses import receipt
from test_support import IsolatedSafetyTestCase


class AppExperienceTests(IsolatedSafetyTestCase):
    def test_aliases_cannot_authorize_other_targets_or_questions(self):
        for target,text in [('Default playlist','Play my playlist'),('Default playlist','Play my default playlist'),('Default playlist','Put on my playlist'),('Jarvis project','Open my Jarvis project'),('Jarvis project','Open Jarvis in VS Code'),('Jarvis project','Pull up the Jarvis project')]:
            call=SimpleNamespace(function=SimpleNamespace(name='open_resource',arguments={'target':target}))
            with patch.object(model_tools,'dispatch') as dispatch:
                model_tools.run_calls([call],text,Mock(),Mock())
                dispatch.assert_called_once()
                for denied in ('What happens if I '+text.lower()+'?', 'Do not '+text.lower(), 'Open something else'):
                    with self.assertRaises(PermissionError): model_tools.run_calls([call],denied,Mock(),Mock())
        self.assertFalse(model_tools.target_requested('Python documentation','Play my playlist'))

    def test_receipts_qualify_launch_and_playback(self):
        pending=receipt({'target':'Default playlist','status':'approval_required','action_type':'open_resource'})
        self.assertEqual(pending, 'Sure, I’ll open your playlist.')
        self.assertNotIn('playing',pending)
        opened=receipt({'target':'Default playlist','status':'executed','resource_kind':'playlist'})
        self.assertNotIn('playing',opened)
        self.assertEqual(receipt({'target':'Chrome','status':'executed'}), 'Sure, I’ll pull up Chrome.')

    def test_overlay_lifetime_failure_stop_and_unknown_target(self):
        border=Mock()
        with patch.object(window_glow,'NativeBorder',return_value=border):
            with window_glow.action_glow('open_app','Chrome'):
                border.start.assert_called_once()
                self.assertEqual(safety.safety.status()['active_operations'],1)
                safety.safety.stop('overlay cancellation')
                border.close.assert_called_once()
            self.assertEqual(border.close.call_count,1)
            border.finish.assert_called_once()
            window_glow._active.discard(border)
            self.assertEqual(safety.safety.status()['active_operations'],0)
        self.assertIsNone(window_glow.executable_for('open_app','Unknown'))
