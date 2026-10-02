from unittest.mock import Mock, patch
from test_support import IsolatedSafetyTestCase
import test_computer_controller
import computer_controller as controller
import safety
from tool_broker import ToolBroker


class PreviewTests(IsolatedSafetyTestCase):
    def snapshot(self):
        return test_computer_controller.ControllerTests.snapshot(self)

    def test_briefly_shown_but_incomplete_native_preview_cannot_claim_success(self):
        import computer_observation as observation
        root,element,automation=Mock(),Mock(),Mock()
        root.CurrentProcessId=2
        root.GetRuntimeId.return_value=(3,4)
        automation.ElementFromHandle.return_value=root
        element.GetRuntimeId.return_value=(5,6)
        element.CurrentName='Next'
        element.CurrentControlType=50000
        element.CurrentIsPassword=element.CurrentIsOffscreen=False
        element.CurrentIsEnabled=True
        element.CurrentBoundingRectangle=Mock(left=10,top=10,right=100,bottom=100)
        window=observation.identity_key(1,2,7,(3,4))
        control={'id':observation.identity_key(window,(5,6)),'name':'Next','type':50000,'context_id':'e'*64}
        with patch.object(observation,'select_window',return_value=(1,2,None,7)), \
             patch.object(observation,'automation_client',return_value=automation), \
             patch.object(observation,'focus'), \
             patch.object(observation,'current_control_context',return_value='e'*64), \
             patch.object(observation,'observe',return_value=({'window_id':window},(1,2,7,(3,4),automation,element))), \
             patch('window_glow.NativeBorder') as factory:
            border=factory.return_value
            border.was_shown=True
            border.completed=False
            with self.assertRaisesRegex(RuntimeError,'until completion'):
                observation.preview('Spotify',window,control)
            border.completed=True
            self.assertEqual(observation.preview('Spotify',window,control),
                             {'app':'Spotify','preview_shown':True,'input_sent':False})

    def test_reference_is_scoped_single_use_and_does_not_trust_mutable_output(self):
        snapshot=self.snapshot()
        reference=controller.issue_reference(snapshot,'master:1')
        snapshot['controls'][0]['name']='Delete'
        with self.assertRaises(PermissionError):
            controller.consume_reference(reference,'side:2','b'*64)
        old,control=controller.consume_reference(reference,'master:1','b'*64)
        self.assertEqual(control['name'],'Play')
        with self.assertRaises(PermissionError):
            controller.consume_reference(reference,'master:1','b'*64)

    def test_reference_expiry_epoch_and_cache_bound(self):
        with controller._reference_lock: controller._references.clear()
        for _ in range(35): controller.issue_reference(self.snapshot(),'master')
        self.assertEqual(len(controller._references),32)
        reference=controller.issue_reference(self.snapshot(),'master')
        with controller._reference_lock:
            controller._references[reference][1]['captured_at']-=61
        with self.assertRaises(controller.StaleTargetError):
            controller.consume_reference(reference,'master','b'*64)
        reference=controller.issue_reference(self.snapshot(),'master')
        safety.safety.stop('invalidate'); safety.safety.resume()
        with self.assertRaises(safety.StoppedError):
            controller.consume_reference(reference,'master','b'*64)

    def test_cancel_before_or_during_preview_is_scoped_and_idempotent(self):
        reference=controller.issue_reference(self.snapshot(),'master')
        self.assertFalse(controller.cancel_preview(reference,'side'))
        self.assertTrue(controller.cancel_preview(reference,'master'))
        self.assertFalse(controller.cancel_preview(reference,'master'))
        with self.assertRaises(PermissionError):
            controller.preview(reference,'master','b'*64)
        reference=controller.issue_reference(self.snapshot(),'master')
        def worker(kind,payload,cancel_event):
            self.assertEqual(kind,'preview')
            self.assertNotIn('bounds',payload['control'])
            self.assertTrue(controller.cancel_preview(reference,'master'))
            self.assertTrue(cancel_event.is_set())
            return {'app':'Spotify','preview_shown':True,'input_sent':False}
        with patch.object(controller,'run_worker',side_effect=worker):
            with self.assertRaisesRegex(RuntimeError,'cancelled'):
                controller.preview(reference,'master','b'*64)
        self.assertNotIn(reference,controller._previews)

    def test_worker_cannot_claim_input_or_wrong_target_and_stop_discards_late_result(self):
        for result in ({'app':'Chrome','preview_shown':True,'input_sent':False},
                       {'app':'Spotify','preview_shown':True,'input_sent':True}):
            reference=controller.issue_reference(self.snapshot(),'master')
            with patch.object(controller,'run_worker',return_value=result):
                with self.assertRaises(RuntimeError): controller.preview(reference,'master','b'*64)
        reference=controller.issue_reference(self.snapshot(),'master')
        def worker(*args,**kwargs):
            safety.safety.stop('preview'); safety.safety.resume()
            return {'app':'Spotify','preview_shown':True,'input_sent':False}
        with patch.object(controller,'run_worker',side_effect=worker):
            with self.assertRaises(safety.StoppedError): controller.preview(reference,'master','b'*64)

    def test_broker_requires_fresh_confirmation_and_audits_without_control_content(self):
        broker=ToolBroker(Mock())
        with patch.object(controller,'preview') as preview:
            with self.assertRaises(PermissionError): broker.preview_control('x','master','y')
            preview.assert_not_called()
        with patch.object(controller,'preview',return_value={'app':'Spotify','preview_shown':True,'input_sent':False}), patch.object(broker,'_audit') as audit:
            result=broker.preview_control('x','master','y',approved=True)
            self.assertFalse(result['input_sent'])
            audit.assert_called_once()
            self.assertNotIn('x',audit.call_args.args[1])
