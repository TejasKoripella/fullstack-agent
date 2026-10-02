"""Local user-controlled stop latch. Never exposed as a model tool."""
import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import threading

from security import assert_not_admin, check_path

_ticket = ContextVar("jarvis_safety_epoch", default=None)


class StoppedError(PermissionError):
    pass


class SafetyState:
    def __init__(self, path):
        self.path = check_path(Path(path))
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.epoch = 0
        self.callbacks = {}
        self.children = {}
        self.reason = ""
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                self.epoch = int(saved["epoch"])
                if saved["state"] != "RUNNING":
                    self.stopped.set()
                    self.reason = saved.get("reason", "Emergency stop")
            except (OSError, ValueError, KeyError, TypeError):
                self.stopped.set()
                self.reason = "Safety state could not be loaded"

    def status(self):
        return {"state": "STOPPED" if self.stopped.is_set() else "RUNNING",
                "epoch": self.epoch, "reason": self.reason,
                "active_operations": len(self.callbacks), "owned_processes": len(self.children)}

    def ensure_running(self, epoch=None):
        epoch = _ticket.get() if epoch is None else epoch
        if self.stopped.is_set() or (epoch is not None and epoch != self.epoch):
            raise StoppedError("Jarvis is stopped or this operation was cancelled. Resume manually to start new activity.")
        return self.epoch

    @contextmanager
    def operation(self, cancel=None):
        with self.lock:
            epoch = self.ensure_running()
            key = object()
            if cancel:
                self.callbacks[key] = cancel
        token = _ticket.set(epoch)
        try:
            yield epoch
        finally:
            _ticket.reset(token)
            with self.lock:
                self.callbacks.pop(key, None)

    @contextmanager
    def async_activity(self):
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        with self.operation(lambda: loop.call_soon_threadsafe(task.cancel)) as epoch:
            yield epoch

    def effect(self, callback):
        # Serialize the final check with short Windows launch/close requests.
        with self.lock:
            self.ensure_running()
            result = callback()
            self.ensure_running()
            return result

    def spawn_owned(self, factory, label):
        with self.lock:
            self.ensure_running()
            process = factory()
            self.children[id(process)] = (process, label)
            if self.stopped.is_set():
                self.children.pop(id(process), None)
                self._terminate(process)
                raise StoppedError("Jarvis stopped during process creation.")
            return process

    def release_owned(self, process):
        with self.lock:
            self.children.pop(id(process), None)

    @staticmethod
    def _terminate(process):
        # Use the retained Popen handle. Never look up or kill a process by name/PID.
        if process.poll() is None or getattr(process, 'cleanup_pending', False) is True:
            process.terminate()

    def _persist(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.status()), encoding="utf-8")
        temporary.replace(self.path)

    def stop(self, reason="Emergency Stop"):
        self.stopped.set()  # Deny new activity immediately, before cleanup or disk I/O.
        failures = []
        with self.lock:
            self.stopped.set()
            # Repeat presses cancel safely without advancing an already-stopped epoch.
            changed = self.reason == "" or bool(self.callbacks) or bool(self.children)
            if changed:
                self.epoch += 1
            self.reason = reason[:200] or "Emergency Stop"
            try:
                self._persist()
            except OSError:
                failures.append("Safety latch persistence failed; do not restart until resolved")
            callbacks = list(self.callbacks.values())
            children = list(self.children.values())
            self.callbacks.clear()
            self.children.clear()
        for callback in callbacks:
            try:
                callback()
            except RuntimeError:
                pass
        for process, label in children:
            try:
                self._terminate(process)
            except OSError:
                failures.append("Could not terminate owned helper: " + label)
                with self.lock:
                    self.children[id(process)] = (process, label)
        return {**self.status(), "cleanup_errors": failures}

    def resume(self):
        assert_not_admin()
        with self.lock:
            if self.children:
                raise StoppedError("Owned process cleanup is incomplete. Retry Emergency Stop before resuming.")
            self.epoch += 1
            self.reason = ""
            self.stopped.clear()
            try:
                self._persist()
            except OSError:
                self.stopped.set()
                raise StoppedError("Cannot persist safety state; Jarvis remains stopped.")
        return self.status()


safety = SafetyState(Path(__file__).resolve().parent / "data" / "safety-state.json")
