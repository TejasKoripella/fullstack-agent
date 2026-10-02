"""Opt-in live resource requests; opens this project and its verification file."""
from pathlib import Path
import tempfile
from unittest.mock import patch
from fastapi.testclient import TestClient
import api
from memory import MemoryStore
import safety as safety_runtime
from safety import SafetyState
from security import require_browser_launch_context
from tool_broker import ToolBroker


def main():
    require_browser_launch_context()
    with tempfile.TemporaryDirectory(prefix="jarvis-resource-verification-") as folder:
        manager = SafetyState(Path(folder) / "safety.json")
        store = MemoryStore(Path(folder) / "test.db")
        store.initialize(approved=True)
        broker = ToolBroker(store)
        with patch.object(safety_runtime, "safety", manager), patch.object(api, "memory", store), \
                patch.object(api, "broker", broker), TestClient(api.app, base_url="http://127.0.0.1:8000") as client:
            for target,phrase in (("Jarvis project","Open Jarvis in VS Code"),("Default playlist","Put on my playlist")):
                response = client.post("/chat", json={"message": phrase, "new_side": True})
                response.raise_for_status()
                calls = response.json()["tool_results"]
                pending = next(item for item in calls if item["action_type"] == "open_resource" and item["target"] == target)
                assert pending["status"] == "approval_required", pending
                print("Qwen requested", target, "; fresh approval pending", flush=True)
                response = client.post("/tools/dispatch", json={"action_type": "open_resource", "target": target,
                    "decision": "allow_once", "safety_epoch": pending["safety_epoch"]})
                response.raise_for_status()
                assert response.json()["request_sent"]
                assert not broker._launched and not manager.children
                print("Windows accepted", target, "; no process ownership", flush=True)
            assert store.list_facts() == []
            assert store.recent_messages() == []


if __name__ == "__main__":
    main()
