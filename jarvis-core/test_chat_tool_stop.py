"""Tool cancellation must preserve STOPPED rather than become authorization denial."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from fastapi.testclient import TestClient
import api
import safety
from memory import MemoryStore
from test_support import IsolatedSafetyTestCase


class ChatToolStopTests(IsolatedSafetyTestCase):
    def test_stop_between_model_response_and_tool_dispatch(self):
        chunk = SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[object()]))
        async def chunks():
            yield chunk
        async def model(**kwargs):
            return chunks() if kwargs.get("stream") else chunk
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            store = MemoryStore(Path(folder) / "test.db")
            store.initialize(approved=True)
            with patch.object(api, "memory", store), patch.object(api, "call_model", side_effect=model), \
                    patch.object(api, "run_calls", side_effect=safety.StoppedError("Jarvis stopped; tool cancelled.")), \
                    patch.object(api, "_save_chat_result") as save:
                client = TestClient(api.app, base_url="http://127.0.0.1:8000")
                response = client.post("/chat", json={"message": "Open Spotify"})
                self.assertEqual(response.status_code, 423)
                stream = client.post("/chat/stream", json={"message": "Open Spotify"})
                self.assertIn('"type": "error"', stream.text)
                self.assertIn('"state": "STOPPED"', stream.text)
                self.assertNotIn('"type": "done"', stream.text)
                save.assert_not_called()
