"""Stop-latch acceptance tests. All databases and state files are disposable."""
import asyncio
from contextlib import ExitStack
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi.testclient import TestClient
import api
from memory import MemoryStore
import permissions
import safety as safety_runtime
from safety import SafetyState, StoppedError
from tool_broker import ToolBroker
from owned_workers import PrivateWorker


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="jarvis-safety-tests-")
        root = Path(self.folder.name)
        self.state = SafetyState(root / "safety.json")
        self.store = MemoryStore(root / "test.db")
        self.store.initialize(approved=True)
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(safety_runtime, "safety", self.state))
        self.stack.enter_context(patch.object(api, "memory", self.store))
        self.client = TestClient(api.app, base_url="http://127.0.0.1:8000")

    def tearDown(self):
        self.state.stop("test cleanup")
        self.stack.close()
        self.folder.cleanup()

    def test_latch_persists_across_restart_and_old_epoch_never_resumes(self):
        epoch = self.state.ensure_running()
        self.state.stop()
        restarted = SafetyState(self.state.path)
        with self.assertRaises(StoppedError):
            restarted.ensure_running()
        restarted.resume()
        with self.assertRaises(StoppedError):
            restarted.ensure_running(epoch)
        self.assertEqual(restarted.status()["state"], "RUNNING")

    def test_invalid_state_fails_closed(self):
        self.state.path.write_text("invalid", encoding="utf-8")
        with self.assertRaises(StoppedError):
            SafetyState(self.state.path).ensure_running()

    def test_speech_cancel_is_423_not_worker_failure(self):
        def cancelled(*args):
            self.state.stop("speech cancellation")
            self.state.ensure_running()
        with patch.object(api, "run_worker", side_effect=cancelled):
            response = self.client.post("/voice/speak", json={"text": "cancelled speech"})
        self.assertEqual(response.status_code, 423)
        self.assertEqual(self.state.status()["state"], "STOPPED")
        self.assertNotIn(b"RIFF", response.content)

    def test_stop_during_speech_worker_creation_is_cancellation(self):
        import owned_workers
        def interrupted_creation(*args):
            self.state.stop("worker creation cancelled")
            raise OSError("Private worker initialization interrupted")
        with patch.dict(owned_workers._workers, {}, clear=True), \
                patch.object(owned_workers, "PrivateWorker", side_effect=interrupted_creation):
            response = self.client.post("/voice/speak", json={"text": "cancel before inference"})
        self.assertEqual(response.status_code, 423)
        self.assertEqual(self.state.children, {})

    def test_normal_shutdown_closes_only_private_helpers(self):
        helper, browser = Mock(), Mock()
        helper.poll.return_value = browser.poll.return_value = None
        self.state.spawn_owned(lambda: helper, "local speak")
        self.state.spawn_owned(lambda: browser, "app window")
        async def shutdown():
            async with api.safety_lifespan(api.app):
                pass
        asyncio.run(shutdown())
        helper.terminate.assert_called_once()
        browser.terminate.assert_not_called()
        self.assertEqual(self.state.status()["state"], "RUNNING")

    def test_voice_discovery_cancel_is_not_reported_as_empty_success(self):
        def cancelled(*args):
            self.state.stop("voice discovery cancellation")
            self.state.ensure_running()
        with patch.object(api, "run_worker", side_effect=cancelled):
            response = self.client.get("/voice/voices")
        self.assertEqual(response.status_code, 423)

    def test_tool_cancel_during_dispatch_is_423_not_permission_denial(self):
        def cancelled(*args):
            self.state.stop("tool cancellation")
            self.state.ensure_running()
        with patch.object(api, "dispatch", side_effect=cancelled):
            response = self.client.post("/tools/dispatch", json={"action_type": "open_app", "target": "Chrome"})
        self.assertEqual(response.status_code, 423)
        self.assertEqual(response.json()["state"], "STOPPED")

    def test_stop_during_browser_handoff_never_acquires_browser_ownership(self):
        entered, release = threading.Event(), threading.Event()
        failures = []
        broker = ToolBroker(self.store)
        def handoff(*args):
            entered.set()
            self.assertTrue(release.wait(3))
        def launch():
            try:
                broker.open_app("Chrome", approved=True)
            except StoppedError:
                failures.append("cancelled")
        with patch("tool_broker.require_browser_launch_context"), \
                patch("tool_broker.os.startfile", side_effect=handoff) as windows, \
                patch("tool_broker.subprocess.Popen") as spawn:
            thread = threading.Thread(target=launch)
            thread.start()
            self.assertTrue(entered.wait(2))
            stop = threading.Thread(target=self.state.stop)
            stop.start()
            self.assertTrue(self.state.stopped.wait(2))
            release.set()
            thread.join(3)
            stop.join(3)
            self.assertFalse(thread.is_alive())
            self.assertFalse(stop.is_alive())
            self.assertEqual(failures, ["cancelled"])
            self.assertEqual(broker._launched, {})
            self.assertEqual(self.state.children, {})
            windows.assert_called_once()
            spawn.assert_not_called()

    def test_repeated_stop_terminates_only_retained_owned_handle_once(self):
        owned = Mock()
        owned.poll.return_value = None
        unrelated = Mock()
        self.state.spawn_owned(lambda: owned, "private helper")
        first = self.state.stop()
        second = self.state.stop()
        owned.terminate.assert_called_once()
        unrelated.terminate.assert_not_called()
        self.assertEqual(first["epoch"], second["epoch"])
        with self.assertRaises(StoppedError):
            self.state.spawn_owned(Mock(), "should not launch")

    def test_stopped_overrides_persistent_permission_and_direct_broker_calls(self):
        self.store.grant_permission("open_app", "Chrome", approved=True)
        self.state.stop()
        broker = ToolBroker(self.store)
        with patch("tool_broker.os.startfile") as launch, patch("tool_broker.subprocess.Popen") as spawn:
            with self.assertRaises(StoppedError):
                permissions.dispatch(self.store, broker, "open_app", "Chrome")
            with self.assertRaises(StoppedError):
                broker.open_app("Chrome", approved=True)
            launch.assert_not_called()
            spawn.assert_not_called()

    def test_cleanup_failure_keeps_handle_and_blocks_resume(self):
        owned = Mock()
        owned.poll.return_value = None
        owned.terminate.side_effect = OSError("Cannot close owned helper")
        self.state.spawn_owned(lambda: owned, "private helper")
        self.assertTrue(self.state.stop()["cleanup_errors"])
        with self.assertRaises(StoppedError):
            self.state.resume()
        owned.terminate.side_effect = None
        self.state.stop()
        self.assertEqual(self.state.resume()["state"], "RUNNING")

    def test_actual_private_worker_is_terminated_without_any_shared_app_handle(self):
        worker = self.state.spawn_owned(lambda: PrivateWorker("voices"), "local voices")
        self.assertIsNone(worker.poll())
        self.state.stop()
        self.assertIsNotNone(worker.process.wait(timeout=3))
        self.assertEqual(self.state.children, {})
        worker.process.stdin.close()
        worker.process.stdout.close()

    def test_stop_resume_require_user_action_and_cancel_old_approvals(self):
        pending = self.client.post("/tools/dispatch", json={"action_type": "open_app", "target": "Chrome"}).json()
        self.assertEqual(pending["status"], "approval_required")
        self.assertEqual(self.client.post("/safety/stop", json={}).status_code, 403)
        self.assertEqual(self.client.post("/safety/stop", json={"approved": True, "source": "local-test"}).status_code, 200)
        for route, payload in [("/chat", {"message": "hello"}), ("/voice/speak", {"text": "hello"}),
                               ("/wake/check", {}), ("/tools/dispatch", {"action_type": "open_app", "target": "Chrome"})]:
            self.assertEqual(self.client.post(route, json=payload).status_code, 423)
        self.assertEqual(self.client.post("/safety/resume", json={}).status_code, 403)
        self.assertEqual(self.client.post("/safety/resume", json={"approved": True}).status_code, 200)
        with patch("tool_broker.os.startfile") as launch:
            stale = self.client.post("/tools/dispatch", json={"action_type": "open_app", "target": "Chrome",
                                    "decision": "allow_once", "safety_epoch": pending["safety_epoch"]})
            self.assertEqual(stale.status_code, 423)
            launch.assert_not_called()
        with self.store._connect(readonly=True) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM audit_log WHERE action='emergency_stop'").fetchone()[0], 1)

    def test_tool_waiting_on_permission_cannot_execute_after_stop_and_resume(self):
        entered, release = threading.Event(), threading.Event()
        failures = []
        def permission(*args):
            entered.set()
            release.wait(2)
            return True
        def request():
            try:
                with self.state.operation():
                    permissions.dispatch(self.store, Mock(), "open_app", "Chrome")
            except StoppedError:
                failures.append("cancelled")
        with patch.object(self.store, "has_permission", side_effect=permission), patch.object(permissions, "execute") as execute:
            thread = threading.Thread(target=request)
            thread.start()
            self.assertTrue(entered.wait(2))
            self.state.stop()
            self.state.resume()
            release.set()
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failures, ["cancelled"])
            execute.assert_not_called()

    def test_model_generation_cancelled_and_no_failed_side_saved(self):
        async def scenario():
            entered = asyncio.Event()
            cancelled = asyncio.Event()
            async def model(**kwargs):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            transport = httpx.ASGITransport(app=api.app)
            with patch.object(api, "call_model", side_effect=model):
                async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
                    request = asyncio.create_task(client.post("/chat", json={"message": "Hello", "new_side": True}))
                    await asyncio.wait_for(entered.wait(), 2)
                    stopped = await client.post("/safety/stop", json={"approved": True, "source": "local-test"})
                    self.assertEqual(stopped.status_code, 200)
                    response = await asyncio.wait_for(request, 2)
                    self.assertEqual(response.status_code, 423)
                    self.assertTrue(cancelled.is_set())
        asyncio.run(scenario())
        self.assertEqual(self.store.list_conversations("side"), [])

    def test_stream_cancellation_closes_generator_without_saving(self):
        async def scenario():
            waiting, closed = asyncio.Event(), asyncio.Event()
            async def stream():
                try:
                    yield SimpleNamespace(message=SimpleNamespace(content="First", tool_calls=None))
                    waiting.set()
                    await asyncio.Event().wait()
                finally:
                    closed.set()
            with patch.object(api, "call_model", new=AsyncMock(return_value=stream())):
                response = api.stream_chat(api.ChatRequest(message="Hello", new_side=True))
                tokens = []
                async def consume():
                    async for item in response.body_iterator:
                        tokens.append(item)
                next_token = asyncio.create_task(consume())
                await asyncio.wait_for(waiting.wait(), 2)
                self.assertIn('"type": "token"', tokens[0])
                self.state.stop()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(next_token, 2)
                self.assertTrue(closed.is_set())
        asyncio.run(scenario())
        self.assertEqual(self.store.list_conversations("side"), [])


if __name__ == "__main__":
    unittest.main()
