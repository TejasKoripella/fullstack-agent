"""Registered resources stay narrow and require fresh approval."""
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
import api
from memory import MemoryStore
import permissions
import model_tools
import tool_broker
from test_support import IsolatedSafetyTestCase


class ResourceTests(IsolatedSafetyTestCase):
    def test_webpage_requires_fresh_approval_and_uses_default_browser(self):
        with patch('tool_broker.require_browser_launch_context'), patch('tool_broker.os.startfile') as windows:
            pending = permissions.dispatch(self.store, self.broker, 'open_resource', 'Python documentation')
            self.assertEqual(pending['status'], 'approval_required')
            windows.assert_not_called()
            self.assertEqual(permissions.dispatch(self.store, self.broker, 'open_resource', 'Python documentation', 'deny')['status'], 'denied')
            windows.assert_not_called()
            result = permissions.dispatch(self.store, self.broker, 'open_resource', 'Python documentation', 'allow_once')
            self.assertEqual(result['status'], 'executed')
            windows.assert_called_once_with('https://docs.python.org/3/')
            self.assertEqual(self.broker._launched, {})
            import safety
            safety.safety.stop('webpage test')
            with self.assertRaises(safety.StoppedError):
                permissions.dispatch(self.store, self.broker, 'open_resource', 'Python documentation', 'allow_once')
            windows.assert_called_once_with('https://docs.python.org/3/')

    def test_registered_webpage_rejects_commands_credentials_and_local_hosts(self):
        import json
        for url in ('http://docs.python.org/3/', 'file:///C:/Users/vijay koripella/secret.txt',
                    'javascript:alert(1)', 'https://localhost/', 'https://127.0.0.1/',
                    'https://machine.local/', 'https://user:password@docs.python.org/',
                    'https://docs.python.org:8000/', 'https://docs.python.org/?secret=1',
                    'https://docs.python.org/#run', 'https://docs.python.org/\\cmd',
                    'https://docs.python.org/\ncmd', 'https://docs.python.org/"cmd'):
            with self.subTest(url=url), patch.object(Path, 'read_text', return_value=json.dumps(
                    {'Reference': {'kind':'webpage','url':url}})):
                with self.assertRaises(PermissionError):
                    tool_broker.known_resources()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=tool_broker.PROJECT_ROOT)
        self.addCleanup(self.folder.cleanup)
        self.store = MemoryStore(Path(self.folder.name) / "test.db")
        self.store.initialize(approved=True)
        self.broker = tool_broker.ToolBroker(self.store)

    def test_fresh_permission_and_no_process_ownership(self):
        with patch("tool_broker.require_browser_launch_context"), patch("tool_broker.os.startfile") as windows:
            pending = permissions.dispatch(self.store, self.broker, "open_resource", "Jarvis project")
            self.assertEqual(pending["status"], "approval_required")
            windows.assert_not_called()
            result = permissions.dispatch(self.store, self.broker, "open_resource", "Jarvis project", "allow_once")
            self.assertTrue(result["request_sent"])
            windows.assert_called_once()
            self.assertTrue(windows.call_args.args[0].startswith("vscode://file/C:/"))
            self.assertEqual(self.broker._launched, {})
            self.assertEqual(permissions.dispatch(self.store, self.broker, "open_resource", "Jarvis project")["status"], "approval_required")
            permissions.dispatch(self.store, self.broker, "open_resource", "Jarvis project", "always_allow")
            self.assertEqual(permissions.dispatch(self.store, self.broker, "open_resource", "Jarvis project")["source"], "persistent")

    def test_resource_listing_exposes_aliases_not_paths_and_never_launches(self):
        with patch.object(api, "memory", self.store), patch("tool_broker.os.startfile") as windows:
            client = TestClient(api.app, base_url="http://127.0.0.1:8000")
            response = client.get("/tools/resources")
            self.assertEqual(response.status_code, 200)
            entries = response.json()["resources"]
            self.assertTrue(entries)
            self.assertTrue(all(set(item) == {"name", "kind", "available"} for item in entries))
            with patch.object(api, "resource_path", side_effect=PermissionError("blocked path")):
                unavailable = client.get("/tools/resources").json()["resources"]
                self.assertTrue(all(not item["available"] for item in unavailable))
            windows.assert_not_called()

    def test_arbitrary_blocked_and_executable_targets_never_open(self):
        with patch("tool_broker.os.startfile") as windows:
            for target in ("cmd", r"C:\Users\vijay koripella\secret.txt", "../outside"):
                with self.subTest(target=target), self.assertRaises(PermissionError):
                    permissions.validate("open_resource", target)
            for path in (r"C:\Users\vijay koripella\secret.txt", r"C:\Windows\notepad.exe"):
                with patch("tool_broker.known_resources", return_value={"Bad": {"kind": "document", "path": path}}):
                    with self.assertRaises(PermissionError):
                        permissions.validate("open_resource", "Bad")
            windows.assert_not_called()

    def test_ambiguous_or_malformed_registry_fails_closed(self):
        config = tool_broker.PROJECT_ROOT / "config" / "known_resources.json"
        for content in (
            '{"Report":{"kind":"document","path":"a.md"},"report":{"kind":"document","path":"b.md"}}',
            '{"Report":{"kind":"document","path":"a.md"},"Report":{"kind":"document","path":"b.md"}}',
            '{"Report":{"kind":[],"path":"a.md"}}',
        ):
            with self.subTest(content=content), patch.object(Path, "read_text", return_value=content):
                with self.assertRaises(PermissionError):
                    tool_broker.known_resources()

    def test_playlist_is_registered_uri_only_and_does_not_claim_playback(self):
        uri = "spotify:playlist:3cEYpjA9oz9GiPac4AsH4n"
        entries = {"Study": {"kind": "playlist", "uri": uri}}
        with patch("tool_broker.known_resources", return_value=entries), \
                patch("permissions.known_resources", return_value=entries), \
                patch("tool_broker.require_browser_launch_context"), patch("tool_broker.os.startfile") as windows:
            pending = permissions.dispatch(self.store, self.broker, "open_resource", "Study")
            self.assertEqual(pending["status"], "approval_required")
            windows.assert_not_called()
            result = permissions.dispatch(self.store, self.broker, "open_resource", "Study", "allow_once")
            windows.assert_called_once_with(uri)
            self.assertFalse(result["playback_confirmed"])
            self.assertNotIn("playing", model_tools.result_text([result]))
            self.assertEqual(self.broker._launched, {})
            import safety
            safety.safety.stop("playlist regression")
            with self.assertRaises(safety.StoppedError):
                permissions.dispatch(self.store, self.broker, "open_resource", "Study", "allow_once")
            windows.assert_called_once_with(uri)
        import json
        for invalid in ("https://open.spotify.com/playlist/" + uri.split(":")[-1],
                        uri + ":play", "spotify:track:" + uri.split(":")[-1],
                        "file:///C:/Users/vijay koripella/secret.txt", uri + "?command=play"):
            with self.subTest(uri=invalid), patch.object(Path, "read_text", return_value=json.dumps(
                    {"Study": {"kind": "playlist", "uri": invalid}})):
                with self.assertRaises(PermissionError):
                    tool_broker.known_resources()

    def test_endpoint_reuses_existing_approval_pipeline_and_model_request_check(self):
        with patch.object(api, "memory", self.store), patch.object(api, "broker", self.broker), \
                patch("tool_broker.require_browser_launch_context"), patch("tool_broker.os.startfile") as windows:
            client = TestClient(api.app, base_url="http://127.0.0.1:8000")
            pending = client.post("/tools/dispatch", json={"action_type": "open_resource", "target": "Jarvis verification"}).json()
            self.assertEqual(pending["status"], "approval_required")
            result = client.post("/tools/dispatch", json={"action_type": "open_resource", "target": "Jarvis verification", "decision": "allow_once", "safety_epoch": pending["safety_epoch"]})
            self.assertEqual(result.status_code, 200)
            windows.assert_called_once_with(str(tool_broker.PROJECT_ROOT / "LOCAL_VERIFICATION.md"))
        self.assertIn("open_resource", {t["function"]["name"] for t in model_tools.definitions("Open Jarvis project")})
        call = Mock(function=Mock(name="open_resource"))
        call.function.name = "open_resource"
        call.function.arguments = {"target": "Jarvis project"}
        with patch.object(model_tools, "dispatch") as dispatch:
            with self.assertRaises(PermissionError):
                model_tools.run_calls([call], "Open Spotify", self.store, self.broker)
            dispatch.assert_not_called()
