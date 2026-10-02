from unittest.mock import patch
from test_support import IsolatedSafetyTestCase
import computer_controller as controller
import safety
import time


class ControllerTests(IsolatedSafetyTestCase):
    def test_focus_requires_exact_worker_confirmation_and_stop_discards_it(self):
        with patch.object(controller, 'run_worker', return_value={'app': 'Chrome', 'focused': True}):
            with self.assertRaises(RuntimeError): controller.focus('Spotify')
        with patch.object(controller, 'run_worker', return_value={'app': 'Spotify', 'focused': True}) as worker:
            self.assertTrue(controller.focus('Spotify')['focused'])
            worker.assert_called_once_with('observe', {'target': 'Spotify', 'mode': 'focus'})
        def interrupted(*args):
            safety.safety.stop('during focus')
            return {'app': 'Spotify', 'focused': True}
        with patch.object(controller, 'run_worker', side_effect=interrupted):
            with self.assertRaises(safety.StoppedError): controller.focus('Spotify')
    def snapshot(self):
        return {'app': 'Spotify', 'window_title': 'Spotify', 'read_only': True, 'partial': False,
                'window_id': 'a' * 64,
                'capture_epoch': safety.safety.epoch, 'captured_at': time.monotonic(),
                'controls': [{'name': 'Play', 'type': 50000, 'enabled': True, 'offscreen': False,
                              'id': 'b' * 64, 'context_id': 'e' * 64, 'bounds': [20, 30, 60, 70]}]}

    def test_snapshot_is_data_not_authority(self):
        snapshot = self.snapshot()
        snapshot.update(permission='always_allow', action='delete', hwnd=123)
        snapshot['controls'][0]['command'] = 'anything'
        result = controller.validate_observation('Spotify', snapshot)
        self.assertNotIn('permission', result)
        self.assertNotIn('hwnd', result)
        self.assertNotIn('command', result['controls'][0])

    def test_only_controller_stamps_snapshot_epoch_and_time(self):
        snapshot = self.snapshot()
        snapshot.update(capture_epoch=-1, captured_at=0)
        with patch.object(controller, 'run_worker', return_value=snapshot):
            result = controller.observe('Spotify')
        self.assertEqual(result['capture_epoch'], safety.safety.epoch)
        self.assertGreater(result['captured_at'], 0)

    def test_invalid_target_mode_size_and_control_fail_closed(self):
        for key, value in [('app', 'Chrome'), ('read_only', False), ('partial', 'false'),
                           ('controls', [self.snapshot()['controls'][0]] * 181), ('controls', [{'name': 'Play'}])]:
            snapshot = self.snapshot()
            snapshot[key] = value
            with self.assertRaises(RuntimeError): controller.validate_observation('Spotify', snapshot)
        snapshot = self.snapshot()
        snapshot['controls'][0]['name'] = r'C:\Users\vijay koripella\notes'
        with self.assertRaises(PermissionError): controller.validate_observation('Spotify', snapshot)

    def test_stop_during_observation_rejects_result_even_after_resume(self):
        def interrupted(*args):
            safety.safety.stop('during observation')
            safety.safety.resume()
            return self.snapshot()
        with patch.object(controller, 'run_worker', side_effect=interrupted):
            with self.assertRaises(safety.StoppedError): controller.observe('Spotify')

    def test_unsupported_or_stopped_never_calls_worker(self):
        with patch.object(controller, 'run_worker') as worker:
            with self.assertRaises(PermissionError): controller.observe('Windows')
            safety.safety.stop('before observation')
            with self.assertRaises(safety.StoppedError): controller.observe('Spotify')
            worker.assert_not_called()

    def test_control_resolution_uses_fresh_geometry_and_rejects_changed_identity(self):
        previous, fresh = self.snapshot(), self.snapshot()
        fresh['controls'][0]['bounds'] = [50, 60, 90, 100]
        result = controller.resolve_control(previous, fresh, 'b' * 64)
        self.assertEqual(result['bounds'], [50, 60, 90, 100])
        for field, value in [('name', 'Buy'), ('enabled', False), ('offscreen', True),
                             ('bounds', [0, 0, 0, 0]), ('id', 'c' * 64), ('context_id','f'*64), ('context_id',None)]:
            fresh = self.snapshot()
            fresh['controls'][0][field] = value
            with self.assertRaises(PermissionError): controller.resolve_control(previous, fresh, 'b' * 64)
        fresh = self.snapshot()
        fresh['window_id'] = 'd' * 64
        with self.assertRaises(PermissionError): controller.resolve_control(previous, fresh, 'b' * 64)

    def test_snapshot_rejects_ambiguous_identifiers_and_invalid_geometry(self):
        snapshot = self.snapshot()
        snapshot['controls'].append(dict(snapshot['controls'][0]))
        with self.assertRaises(RuntimeError): controller.validate_observation('Spotify', snapshot)
        for bounds in ([True, 0, 1, 2], [0, 0, float('nan'), 2], [0, 0, 2], [0, 0, 1000001, 2]):
            snapshot = self.snapshot()
            snapshot['controls'][0]['bounds'] = bounds
            with self.assertRaises(RuntimeError): controller.validate_observation('Spotify', snapshot)

    def test_target_references_expire_and_do_not_survive_stop_resume(self):
        previous, fresh = self.snapshot(), self.snapshot()
        previous['captured_at'] -= 61
        with self.assertRaises(controller.StaleTargetError): controller.resolve_control(previous, fresh, 'b' * 64)
        previous, fresh = self.snapshot(), self.snapshot()
        fresh['captured_at'] -= 6
        with self.assertRaises(controller.StaleTargetError): controller.resolve_control(previous, fresh, 'b' * 64)
        previous, fresh = self.snapshot(), self.snapshot()
        safety.safety.stop('invalidate target')
        safety.safety.resume()
        with self.assertRaises(safety.StoppedError): controller.resolve_control(previous, fresh, 'b' * 64)
