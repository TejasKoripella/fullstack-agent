"""Cached speech workers, owned exclusively by Jarvis and stoppable mid-inference."""
import base64
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import safety as safety_runtime

_workers = {}
_locks = {kind: threading.Lock() for kind in ("speak", "transcribe", "voices", "observe", "preview")}


class PrivateWorker:
    def __init__(self, kind):
        self._terminate_lock = threading.RLock()
        self.job = None
        self.terminated = False
        self.process = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("local_worker.py")), kind],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            if os.name == "nt":
                # A private job captures only this waiting helper and its future
                # fixed speech children. It never includes browser/app processes.
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.CreateJobObjectW.argtypes = [w.LPVOID, w.LPCWSTR]
                kernel.CreateJobObjectW.restype = w.HANDLE
                kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
                kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
                kernel.CloseHandle.argtypes = [w.HANDLE]
                self.kernel = kernel
                self.job = kernel.CreateJobObjectW(None, None)
                # JOBOBJECT_EXTENDED_LIMIT_INFORMATION: LimitFlags offset 16,
                # total 144 bytes on Win64, 112 on Win32.
                limits = ctypes.create_string_buffer(144 if ctypes.sizeof(w.HANDLE) == 8 else 112)
                ctypes.c_uint32.from_buffer(limits, 16).value = 0x2000  # KILL_ON_JOB_CLOSE
                if not self.job or not kernel.SetInformationJobObject(self.job, 9, limits, len(limits)) \
                        or not kernel.AssignProcessToJobObject(self.job, w.HANDLE(int(self.process._handle))):
                    raise OSError("Cannot isolate the private speech worker")
        except BaseException:
            self.terminate()
            raise

    def poll(self):
        return -15 if self.terminated else self.process.poll()

    @property
    def cleanup_pending(self):
        # The retained private Job still needs closing even if its first child exited.
        return bool(self.job)

    def terminate(self):
        with self._terminate_lock:
            if self.terminated: return
            if self.job:
                if not self.kernel.CloseHandle(self.job):
                    raise OSError("Private worker job cleanup failed")
                self.job = None
            if self.process.poll() is None:
                self.process.terminate()
            self.terminated = True


def run_worker(kind, payload, cancel_event=None):
    if kind not in _locks:
        raise ValueError("Unknown private worker")
    if cancel_event is not None and kind != 'preview':
        raise ValueError('Scoped cancellation supports preview helpers only')
    with _locks[kind], safety_runtime.safety.operation() as epoch:
        worker = None
        finished = threading.Event()
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError('Target preview cancelled')
            worker = _workers.get(kind)
            if worker is None or worker.poll() is not None:
                if worker:
                    worker.terminate()
                    safety_runtime.safety.release_owned(worker)
                worker = safety_runtime.safety.spawn_owned(lambda: PrivateWorker(kind), "local " + kind)
                _workers[kind] = worker
            safety_runtime.safety.ensure_running(epoch)
            if cancel_event is not None:
                def watch_cancel():
                    while not finished.wait(.05):
                        if cancel_event.is_set():
                            worker.terminate()
                            return
                threading.Thread(target=watch_cancel, daemon=True, name='Jarvis preview cancellation').start()
            worker.process.stdin.write(json.dumps(payload) + "\n")
            worker.process.stdin.flush()
            timer = threading.Timer(8 if kind in {"observe", "preview"} else 95, worker.terminate)
            timer.daemon = True
            timer.start()
            try:
                line = worker.process.stdout.readline(60 * 1024 * 1024)
            finally:
                timer.cancel()
            safety_runtime.safety.ensure_running(epoch)
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError('Target preview cancelled')
            result = json.loads(line)
            scroll_trace = result.get('scroll_trace')
            if kind == 'preview' and isinstance(scroll_trace,dict) and scroll_trace.get('reason') in {
                    'provider_call','provider_exception','target_attestation_lost','position_unchanged','verified'}:
                import logging
                positions = [scroll_trace.get(key) for key in ('before','after')]
                if all(value is None or type(value) in (int,float) and 0<=value<=100 for value in positions):
                    logging.getLogger(__name__).warning('Scroll verification: reason=%s before=%s after=%s',
                        scroll_trace['reason'], *positions)
            trace = result.get('foreground_trace')
            if kind == 'preview' and isinstance(trace,dict) \
                    and type(trace.get('request_accepted')) is bool and type(trace.get('confirmed')) is bool \
                    and type(trace.get('wait_ms')) is int and 0 <= trace['wait_ms'] <= 1000:
                import logging
                logging.getLogger(__name__).warning('Foreground verification: accepted=%s confirmed=%s wait_ms=%s',
                    trace['request_accepted'], trace['confirmed'], trace['wait_ms'])
            if not result.get("ok"):
                if kind in {"observe", "preview"}:
                    import logging
                    logging.getLogger(__name__).warning('Window inspection diagnostic: %s', result.get('diagnostic', 'unavailable'))
                raise RuntimeError(result.get("error", "Local speech failed"))
            return base64.b64decode(result["value"], validate=True) if kind == "speak" else result["value"]
        except (OSError, ValueError):
            safety_runtime.safety.ensure_running(epoch)
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError('Target preview cancelled')
            raise RuntimeError("Window inspection timed out or disconnected" if kind in {"observe", "preview"} else "Local speech worker disconnected")
        finally:
            finished.set()
            if kind == 'preview' and worker is not None:
                worker.terminate()
                safety_runtime.safety.release_owned(worker)
                if _workers.get(kind) is worker: _workers.pop(kind, None)
