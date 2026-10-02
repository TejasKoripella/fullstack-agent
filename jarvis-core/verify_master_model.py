"""Optional live Qwen acceptance check using an isolated disposable database."""
import tempfile
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import api
from memory import MemoryStore


def main():
    with tempfile.TemporaryDirectory(prefix="jarvis-live-master-") as folder:
        store = MemoryStore(Path(folder) / "acceptance.db")
        store.initialize(approved=True)
        with patch.object(api, "memory", store), TestClient(api.app, base_url="http://127.0.0.1:8000") as client:
            response = client.post("/chat", json={"message": "My robotics codebase uses Java. Reply with only remembered."})
            response.raise_for_status()
            assert store.list_facts()[0]["value"] == "Java"
            print("Master fact saved: Java", flush=True)
            question = "What language does my robotics codebase use? Answer with only the language name."
            for kind, payload in (("Master", {"message": question}), ("Side", {"message": question, "new_side": True, "save": True})):
                response = client.post("/chat", json=payload)
                response.raise_for_status()
                result = response.json()
                assert "java" in result["reply"].lower(), result["reply"]
                if kind == "Side":
                    assert result["saved"] is False
                print(kind + " retrieved: " + result["reply"], flush=True)
            assert len(store.list_conversations("master")) == 1
            assert store.recent_messages() == []
            store.set_fact('music service','Spotify',approved=True)
            response=client.post('/chat',json={'message':'What do you know about me? List only saved facts.','new_side':True})
            response.raise_for_status()
            result=response.json()
            assert 'spotify' in result['reply'].lower(),result['reply']
            assert result['saved'] is False
            print('General Side question recalled the bounded saved profile without a topic keyword.',flush=True)
            print("Live Qwen acceptance passed; production facts unchanged.", flush=True)


if __name__ == "__main__":
    main()
