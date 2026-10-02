import math
import ctypes
from ctypes import wintypes as w
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from test_support import IsolatedSafetyTestCase
from window_glow import NativeBorder, reticle_segments, physical_pixel_context
from owned_workers import PrivateWorker


class OverlayContractTests(IsolatedSafetyTestCase):
    def test_physical_pixels_restore_thread_context_even_on_failure(self):
        user32=Mock()
        user32.SetThreadDpiAwarenessContext.return_value=123
        with self.assertRaises(RuntimeError):
            with physical_pixel_context(user32,required=True):
                raise RuntimeError('renderer failed')
        calls=user32.SetThreadDpiAwarenessContext.call_args_list
        self.assertEqual(len(calls),2)
        self.assertEqual(ctypes.c_ssize_t(calls[0].args[0].value).value,-4)
        self.assertEqual(calls[1].args,(123,))

    def test_control_overlay_rejects_unknown_dpi_context(self):
        for user32 in (object(),Mock()):
            if isinstance(user32,Mock): user32.SetThreadDpiAwarenessContext.return_value=None
            with self.assertRaises(OSError):
                with physical_pixel_context(user32,required=True):
                    self.fail('must not draw with unverified coordinates')
            with physical_pixel_context(user32):
                pass # Existing decorative border remains best effort.

    def test_reticle_fails_closed_for_missing_or_outside_geometry(self):
        window = (100, 100, 500, 400)
        for bounds in (None, [100, 100, 100, 200], [0, 100, 200, 200],
                       [100, 100, math.nan, 200], [100, True, 200, 200]):
            self.assertEqual(reticle_segments(bounds, window, .3), [])

    def test_marks_follow_current_control_and_remain_inside_it(self):
        for bounds, window in (([150, 120, 250, 160], (100, 100, 500, 400)),
                               ([350, 320, 450, 360], (300, 300, 700, 600))):
            marks = reticle_segments(bounds, window, .3)
            self.assertEqual(len(marks), 10)
            for left, top, right, bottom in marks:
                self.assertTrue(bounds[0]-window[0] <= left < right <= bounds[2]-window[0])
                self.assertTrue(bounds[1]-window[1] <= top < bottom <= bounds[3]-window[1])

    def test_control_provider_cannot_be_used_from_unmarshalled_overlay_thread(self):
        border = NativeBorder('spotify.exe', exact_window=(1,2), control_bounds=lambda: [0, 0, 100, 100], duration=3)
        with self.assertRaises(ValueError): border.start()
        self.assertFalse(border.shown.is_set())
        for duration in (0, 6, True, float('nan')):
            with self.assertRaises(ValueError): NativeBorder('spotify.exe', duration=duration)

    def test_failed_native_frame_never_publishes_readiness_and_releases_resources(self):
        for failure in ('position','dc','black','edge','background','mark','alpha'):
            with self.subTest(failure=failure):
                border=NativeBorder('spotify.exe')
                u,g=Mock(),Mock()
                u.SetWindowPos.return_value=failure!='position'
                u.GetDC.return_value=0 if failure=='dc' else 10
                g.CreateSolidBrush.side_effect=[0 if failure=='black' else 11,0 if failure=='edge' else 12]
                u.FillRect.side_effect=[0] if failure=='background' else ([1]*5+[0] if failure=='mark' else None)
                u.FillRect.return_value=1
                u.SetLayeredWindowAttributes.return_value=failure!='alpha'
                with self.assertRaises(OSError):
                    border._paint_frame(u,g,7,w.RECT(0,0,100,100),[(5,5,10,6)],150)
                self.assertFalse(border.was_shown)
                self.assertFalse(border.shown.is_set())
                if failure not in ('position','dc'):
                    u.ReleaseDC.assert_called_once_with(7,10)
                    expected=1 if failure in ('black','edge') else 2
                    self.assertEqual(g.DeleteObject.call_count,expected)
                else:
                    u.ReleaseDC.assert_not_called()

    def test_successful_frame_readiness_does_not_claim_lifecycle_completion(self):
        border=NativeBorder('spotify.exe')
        u,g=Mock(),Mock()
        u.SetWindowPos.return_value=True
        u.GetDC.return_value=10
        g.CreateSolidBrush.side_effect=[11,12]
        u.FillRect.return_value=1
        u.SetLayeredWindowAttributes.return_value=True
        border._paint_frame(u,g,7,w.RECT(0,0,100,100),[(5,5,10,6)],150)
        self.assertTrue(border.was_shown)
        self.assertTrue(border.shown.is_set())
        self.assertFalse(border.completed)
        self.assertEqual(u.FillRect.call_count,6)
        u.ReleaseDC.assert_called_once_with(7,10)

    def worker(self):
        worker = object.__new__(PrivateWorker)
        worker._terminate_lock = threading.RLock()
        worker.terminated, worker.job = False, 123
        worker.kernel, worker.process = Mock(), Mock()
        worker.kernel.CloseHandle.return_value = True
        worker.process.poll.return_value = None
        return worker

    def test_stop_and_timeout_close_only_one_owned_job_handle(self):
        worker = self.worker()
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(lambda _: worker.terminate(), range(10)))
        worker.kernel.CloseHandle.assert_called_once_with(123)
        worker.process.terminate.assert_called_once_with()
        self.assertTrue(worker.terminated)

    def test_failed_owned_job_cleanup_keeps_handle_for_retry(self):
        worker = self.worker()
        worker.kernel.CloseHandle.return_value = False
        with self.assertRaises(OSError): worker.terminate()
        self.assertEqual(worker.job, 123)
        self.assertFalse(worker.terminated)
        worker.process.terminate.assert_not_called()
        worker.kernel.CloseHandle.return_value = True
        worker.terminate()
        self.assertTrue(worker.terminated)

    def test_stop_closes_retained_private_job_after_the_initial_child_exits(self):
        import safety
        worker=self.worker()
        worker.process.poll.return_value=0
        safety.safety._terminate(worker)
        worker.kernel.CloseHandle.assert_called_once_with(123)
        worker.process.terminate.assert_not_called()
        self.assertFalse(worker.cleanup_pending)
