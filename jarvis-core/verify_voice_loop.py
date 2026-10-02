"""Opt-in offline software voice loop; no microphone or speaker is activated."""
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient
import api
from memory import MemoryStore
import safety as safety_runtime
from safety import SafetyState


def main():
    with tempfile.TemporaryDirectory(prefix="jarvis-voice-verification-") as folder:
        store = MemoryStore(Path(folder) / "test.db")
        store.initialize(approved=True)
        manager = SafetyState(Path(folder) / "safety.json")
        with patch.object(api, "memory", store), patch.object(safety_runtime, "safety", manager), \
                TestClient(api.app, base_url="http://127.0.0.1:8000") as client:
            try:
                audio = client.post("/voice/speak", json={"text": "What is two plus two? Reply with only the answer."})
                audio.raise_for_status()
                assert audio.content.startswith(b"RIFF") and audio.content[8:12] == b"WAVE"
                transcript = client.post("/transcribe", content=audio.content, headers={"content-type": "audio/wav"})
                transcript.raise_for_status()
                text = transcript.json()["text"]
                assert "two" in text.lower() or "2" in text, text
                print("Local transcription:", text, flush=True)
                stream = client.post("/chat/stream", json={"message": text, "new_side": True})
                stream.raise_for_status()
                events = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith("data: ")]
                assert any(event["type"] == "token" for event in events)
                final = next(event for event in events if event["type"] == "done")
                reply = final["reply"]
                assert "4" in reply or "four" in reply.lower(), reply
                assert not final["saved"]
                spoken = client.post("/voice/speak", json={"text": reply})
                spoken.raise_for_status()
                assert spoken.content.startswith(b"RIFF") and spoken.content[8:12] == b"WAVE"
                assert store.list_facts() == []
                assert store.recent_messages() == []
                assert len(store.list_conversations("side")) == 1
                print("PASS: synthetic audio -> local Whisper -> streamed Qwen -> local WAV; Side memory isolation", flush=True)
            finally:
                manager.stop("voice verification cleanup")


if __name__ == "__main__":
    main()
