from unittest.mock import Mock, patch, PropertyMock
from fastapi.testclient import TestClient
from test_support import IsolatedSafetyTestCase
import computer_controller as controller
import computer_observation as observation
import test_computer_controller
from tool_broker import ToolBroker
import safety


class ScrollTests(IsolatedSafetyTestCase):
    def snapshot(self):
        value=test_computer_controller.ControllerTests.snapshot(self)
        value['controls'][0].update(name='Main',scrollable=True)
        return value

    def result(self,**changes):
        value=dict(app='Spotify',action='scroll_down',indicator_shown=True,indicator_completed=True,
                   action_attempted=True,outcome='verified',before=10,after=20)
        value.update(changes)
        return value

    def test_only_fixed_accessibility_actions_and_registered_targets_are_allowed(self):
        from computer_action_policy import validate_action
        for action in ('click','type','delete','shell','purchase','scroll_down;delete'):
            with self.assertRaises(PermissionError): validate_action('Spotify',{'scrollable':True},action)
        with self.assertRaises(PermissionError): validate_action('Windows',{'scrollable':True},'scroll_down')
        for value in (False,'true',1,None):
            with self.assertRaises(PermissionError): validate_action('Spotify',{'scrollable':value},'scroll_down')

    def test_control_effects_cannot_inherit_saved_or_unscoped_authority(self):
        from computer_action_policy import validate_action
        from capability_registry import ActionContract, ACTION_CONTRACTS
        for contract in (ActionContract('reversible','exact_target',True),
                         ActionContract('consequential','fresh_once_scoped_reference'),
                         ActionContract('reversible','fresh_once_scoped_reference',True)):
            contracts=dict(ACTION_CONTRACTS,scroll_control=contract)
            with patch('computer_action_policy.ACTION_CONTRACTS',contracts):
                with self.assertRaises(PermissionError):
                    validate_action('Spotify',{'scrollable':True},'scroll_down')

    def test_scope_purpose_single_use_and_cancel_remain_enforced_for_actions(self):
        for purpose in ('context','preview'):
            ref=controller.issue_reference(self.snapshot(),'master:1',purpose=purpose)
            with patch.object(controller,'run_worker') as worker:
                with self.assertRaises(PermissionError): controller.execute_control(ref,'master:1','b'*64,'scroll_down')
                worker.assert_not_called()
        ref=controller.issue_reference(self.snapshot(),'master:1',purpose='control')
        with patch.object(controller,'run_worker',return_value=self.result()) as worker:
            with self.assertRaises(PermissionError): controller.execute_control(ref,'side:1','b'*64,'scroll_down')
            self.assertEqual(controller.execute_control(ref,'master:1','b'*64,'scroll_down')['outcome'],'verified')
            payload=worker.call_args.args[1]
            self.assertNotIn('bounds',payload['control'])
            self.assertNotIn('hwnd',payload)
            with self.assertRaises(PermissionError): controller.execute_control(ref,'master:1','b'*64,'scroll_down')
        ref=controller.issue_reference(self.snapshot(),'master:1',purpose='control')
        controller.cancel_preview(ref,'master:1')
        with patch.object(controller,'run_worker') as worker:
            with self.assertRaises(PermissionError): controller.execute_control(ref,'master:1','b'*64,'scroll_down')
            worker.assert_not_called()

    def test_receipts_require_real_directional_movement_and_indicator_readiness(self):
        for change in ({'after':10},{'after':5},{'after':float('nan')},{'before':True},
                       {'indicator_shown':False},{'app':'Chrome'},{'action_attempted':False}):
            with self.assertRaises(RuntimeError): controller.validate_action_result('Spotify','scroll_down',self.result(**change))
        result=controller.validate_action_result('Spotify','scroll_down',self.result(hwnd=123,permission='always_allow'))
        self.assertNotIn('hwnd',result)
        self.assertNotIn('permission',result)
        self.assertEqual(controller.validate_action_result('Spotify','scroll_down',self.result(outcome='unknown'))['outcome'],'unknown')

    def test_stop_discards_late_action_results_even_after_resume(self):
        ref=controller.issue_reference(self.snapshot(),'master:1',purpose='control')
        def worker(*args,**kwargs):
            safety.safety.stop('during scroll'); safety.safety.resume()
            return self.result()
        with patch.object(controller,'run_worker',side_effect=worker):
            with self.assertRaises(safety.StoppedError): controller.execute_control(ref,'master:1','b'*64,'scroll_down')

    def test_broker_requires_fresh_approval_and_unknown_outcome_never_claims_success(self):
        broker=ToolBroker(Mock())
        with patch.object(controller,'execute_control') as execute:
            with self.assertRaises(PermissionError): broker.scroll_control('r','s','c','scroll_down')
            execute.assert_not_called()
        with patch.object(controller,'execute_control',return_value=self.result(outcome='unknown')),patch.object(broker,'_audit') as audit:
            result=broker.scroll_control('r','s','c','scroll_down',approved=True)
            self.assertIn('could not be confirmed',result['message'])
            self.assertFalse(audit.call_args.args[3])

    def test_api_accepts_only_fresh_once_scroll_and_stop_blocks_broker(self):
        import api
        client=TestClient(api.app,base_url='http://127.0.0.1:8000')
        body=dict(reference='a'*64,control_id='b'*64,workspace_scope='master:1',
                  decision='allow_once',safety_epoch=safety.safety.epoch,action='scroll_down')
        with patch.object(api.broker,'scroll_control',return_value=self.result()) as execute:
            self.assertEqual(client.post('/tools/scroll-control',json=dict(body,decision='always_allow')).status_code,422)
            self.assertEqual(client.post('/tools/scroll-control',json=dict(body,action='click')).status_code,422)
            self.assertEqual(client.post('/tools/scroll-control',json=body).status_code,200)
            safety.safety.stop('test')
            self.assertEqual(client.post('/tools/scroll-control',json=body).status_code,423)
            self.assertEqual(execute.call_count,1)

    def test_worker_scroll_is_one_pattern_call_then_observation_without_retry(self):
        for action,positions,expected_amount,outcome in (
                ('scroll_down',[10,20],4,'verified'),('scroll_up',[20,10],1,'verified'),
                ('scroll_up',[0],None,'boundary'),('scroll_down',[100],None,'boundary'),
                ('scroll_down',[10],4,'unknown')):
            with self.subTest(action=action,positions=positions):
                root,element,automation,pattern=Mock(),Mock(),Mock(),Mock()
                root.CurrentProcessId=2; root.GetRuntimeId.return_value=(3,4)
                automation.ElementFromHandle.return_value=root
                element.GetRuntimeId.return_value=(5,6)
                element.CurrentName='Main'; element.CurrentControlType=50033
                element.CurrentIsPassword=element.CurrentIsOffscreen=False
                element.CurrentIsEnabled=True
                element.CurrentBoundingRectangle=Mock(left=10,top=10,right=100,bottom=100)
                element.GetCurrentPattern.return_value.QueryInterface.return_value=pattern
                pattern.CurrentVerticallyScrollable=True
                if outcome=='unknown': pattern.Scroll.side_effect=OSError('provider disconnected after accepting action')
                type(pattern).CurrentVerticalScrollPercent=PropertyMock(side_effect=positions)
                window=observation.identity_key(1,2,7,(3,4))
                control=dict(id=observation.identity_key(window,(5,6)),name='Main',type=50033,context_id='e'*64,scrollable=True)
                def border_factory(*args,**kwargs):
                    border=Mock(was_shown=True,completed=True)
                    border.run.side_effect=kwargs['on_ready']
                    return border
                with patch.object(observation,'select_window',return_value=(1,2,None,7)), \
                     patch.object(observation,'automation_client',return_value=automation),patch.object(observation,'focus'), \
                     patch.object(observation,'current_control_context',return_value='e'*64), \
                     patch.object(observation,'observe',return_value=({'window_id':window},(1,2,7,(3,4),automation,element))), \
                     patch('window_glow.NativeBorder',side_effect=border_factory):
                    result=observation.preview('Spotify',window,control,action)
                self.assertEqual(result['outcome'],outcome)
                if outcome=='unknown':
                    self.assertEqual(observation.SCROLL_TRACE['reason'],'provider_exception')
                if outcome=='verified':
                    self.assertEqual(observation.SCROLL_TRACE,dict(reason='verified',before=positions[0],after=positions[1]))
                if expected_amount is None: pattern.Scroll.assert_not_called()
                else: pattern.Scroll.assert_called_once_with(2,expected_amount)
