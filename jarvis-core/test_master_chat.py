"""Acceptance checks for canonical Master Chat, drafts, migration, and memory isolation."""
import json
import sqlite3
import tempfile
import unittest
from test_support import IsolatedSafetyTestCase
from types import SimpleNamespace
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import api
from memory import MemoryStore
from retrieval import relevant_context


class MasterChatTests(IsolatedSafetyTestCase):
    def test_general_memory_question_gets_bounded_user_profile_without_keyword(self):
        self.store.set_fact('music service','Spotify',approved=True)
        self.store.set_fact('robotics language','Java',approved=True)
        _, messages, _ = api._prepare_chat(api.ChatRequest(message='What do you know about me?',new_side=True))
        self.assertIn('music service: Spotify',str(messages))
        self.assertIn('robotics language: Java',str(messages))
        self.assertIn('Untrusted',str(messages))
        for index in range(20):
            self.store.set_fact('fact '+str(index),'x'*1000,approved=True)
        context=self.store.structured_context()
        self.assertLessEqual(len(context),9)
        self.assertTrue(all(len(item)<550 for item in context))

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="jarvis-master-tests-")
        self.path = Path(self.folder.name) / "test.db"
        self.store = MemoryStore(self.path)
        self.store.initialize(approved=True)
        self.client = TestClient(api.app, base_url="http://127.0.0.1:8000")
        self.patcher = patch.object(api, "memory", self.store)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.folder.cleanup()

    def answer(self, payload, answer="Understood.", streaming=False):
        result = iter([Mock(message=Mock(content=answer))]) if streaming else Mock(message=Mock(content=answer))
        with patch.object(api, "call_model", return_value=result) as model:
            response = self.client.post("/chat/stream" if streaming else "/chat", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        if streaming:
            data = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            result = next(item for item in data if item["type"] == "done")
        else:
            result = response.json()
        return result, model.call_args.kwargs["messages"]

    def test_stream_failure_closes_model_response_and_leaves_no_draft(self):
        class BrokenStream:
            closed = False

            def __iter__(self):
                return self

            def __next__(self):
                raise OSError("Connection interrupted")

            def close(self):
                self.closed = True

        stream = BrokenStream()
        with patch.object(api, "call_model", return_value=stream):
            response = self.client.post("/chat/stream", json={"message": "Hello", "new_side": True})
        self.assertIn('"type": "error"', response.text)
        self.assertTrue(stream.closed)
        self.assertEqual(self.store.list_conversations("side"), [])
        result, _ = self.answer({"message": "Hello again", "new_side": True}, streaming=True)
        self.assertEqual(result["conversation_kind"], "side")

    def test_single_master_cannot_be_replaced_deleted_or_renamed(self):
        first = self.store.master_conversation()
        for _ in range(3):
            created = self.client.post("/conversations", json={"kind": "main", "title": "Another main"})
            self.assertEqual(created.json()["id"], first["id"])
        self.assertEqual(len(self.client.get("/conversations?kind=master").json()["conversations"]), 1)
        self.assertEqual(self.client.request("DELETE", f"/conversations/{first['id']}", json={"confirm": True}).status_code, 403)
        self.assertEqual(self.client.patch(f"/conversations/{first['id']}", json={"title": "Other"}).status_code, 403)
        with self.store._connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO conversations(kind,title,is_master) VALUES ('main','Duplicate',1)")

    def test_explicit_commit_keeps_side_history_and_is_idempotent(self):
        side, _ = self.answer({"message": "My favorite fruit is mango.", "new_side": True}, "Understood.")
        chat_id = side["conversation_id"]
        self.assertEqual(self.store.list_facts(), [])
        committed = self.client.post(f"/conversations/{chat_id}/commit-memory")
        self.assertEqual(committed.status_code, 200)
        self.assertEqual(committed.json()["saved_entries"], 1)
        self.assertGreater(committed.json()["saved_facts"], 0)
        self.assertEqual(self.store.conversation_metadata(chat_id)["kind"], "side")
        self.assertEqual(len(self.store.get_conversation(chat_id)["messages"]), 2)
        repeated = self.client.post(f"/conversations/{chat_id}/commit-memory").json()
        self.assertEqual(repeated, {"saved_entries": 0, "saved_facts": 0})
        self.assertEqual(self.client.post(f"/conversations/{self.store.master_conversation()['id']}/commit-memory").status_code, 404)

    def test_native_tool_stream_uses_permission_result_instead_of_model_success_claim(self):
        call = SimpleNamespace(function=SimpleNamespace(name="open_app", arguments={"target": "Spotify"}))
        chunks = iter([SimpleNamespace(message=SimpleNamespace(content="Spotify is open!", tool_calls=[call]))])
        result = {"status": "approval_required", "action_type": "open_app", "target": "Spotify", "security_result": "passed"}
        with patch.object(api, "call_model", return_value=chunks) as model, patch("model_tools.dispatch", return_value=result) as dispatch:
            response = self.client.post("/chat/stream", json={"message": "Open Spotify", "new_side": True})
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        done = next(event for event in events if event["type"] == "done")
        self.assertIn("pull up Spotify", done["reply"])
        self.assertNotIn("Spotify is open!", response.text)
        self.assertEqual(done["tool_results"], [result])
        self.assertIn("open_app", str(model.call_args.kwargs["tools"]))
        dispatch.assert_called_once()

    def test_untouched_and_failed_drafts_create_nothing_first_success_is_atomic(self):
        self.assertEqual(self.client.post("/conversations", json={"kind": "side"}).status_code, 422)
        request = api.ChatRequest(message="Explain WebSockets", new_side=True)
        api._prepare_chat(request)
        self.assertEqual(self.store.list_conversations("side"), [])
        with patch.object(api, "call_model", side_effect=api.ollama.ResponseError("offline")):
            failed = self.client.post("/chat/stream", json={"message": "Explain WebSockets", "new_side": True})
        self.assertIn('"type": "error"', failed.text)
        self.assertEqual(self.store.list_conversations("side"), [])
        result, _ = self.answer({"message": "Explain WebSockets", "new_side": True}, "A persistent connection.", streaming=True)
        sides = self.store.list_conversations("side")
        self.assertEqual(len(sides), 1)
        self.assertEqual(result["conversation_id"], sides[0]["id"])
        self.assertEqual([m["content"] for m in self.store.get_conversation(sides[0]["id"])["messages"]], ["Explain WebSockets", "A persistent connection."])

    def test_master_fact_retrieval_and_side_local_context_without_memory_writes(self):
        self.answer({"message": "My robotics codebase uses Java."})
        self.assertEqual(self.store.list_facts()[0]["value"], "Java")
        _, prompt = self.answer({"message": "What language does my robotics codebase use?"}, "Java.")
        self.assertIn("robotics codebase language: Java", str(prompt))
        side, prompt = self.answer({"message": "What language does my robotics codebase use?", "new_side": True, "save": True}, "Java.")
        self.assertIn("robotics codebase language: Java", str(prompt))
        self.assertFalse(side["saved"])
        self.answer({"message": "Explain WebSockets", "conversation_id": side["conversation_id"]}, "A persistent connection.")
        _, prompt = self.answer({"message": "Would that help Jarvis?", "conversation_id": side["conversation_id"]}, "It could.")
        self.assertIn("A persistent connection.", str(prompt))
        self.answer({"message": "My favorite fruit is side-only-mango.", "conversation_id": side["conversation_id"], "save": True})
        self.assertNotIn("side-only-mango", str(self.store.list_facts()))
        self.assertNotIn("side-only-mango", str(relevant_context("side-only-mango", db_path=self.path)))
        self.assertEqual(self.store.recent_messages(), [])
        self.assertEqual(self.client.request("DELETE", f"/conversations/{side['conversation_id']}", json={"confirm": True}).status_code, 200)
        self.assertNotIn("side-only-mango", str(relevant_context("side-only-mango", db_path=self.path)))

    def test_explicit_move_enables_memory_and_preserves_source(self):
        side, _ = self.answer({"message": "My favorite fruit is explicit-mango.", "new_side": True})
        moved = self.client.post(f"/conversations/{side['conversation_id']}/promote")
        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()["id"], self.store.master_conversation()["id"])
        self.assertEqual(len(self.store.list_conversations("master")), 1)
        self.assertEqual(self.store.list_conversations("side"), [])
        self.assertIn("explicit-mango", str(self.store.list_facts()))
        self.assertEqual(len(self.store.get_conversation(side["conversation_id"])["messages"]), 2)
        self.assertEqual(self.client.post(f"/conversations/{side['conversation_id']}/promote").status_code, 404)
        self.assertEqual(len(self.store.list_facts()), 1)

    def test_prompt_is_bounded_and_side_cannot_spoof_master_context(self):
        master = self.store.master_conversation()["id"]
        self.store.add_conversation_message(master, "user", "Old irrelevant transcript sentinel", approved=True)
        for i in range(40):
            self.store.add_conversation_message(master, "user", f"Entry {i}: " + "x" * 6000, approved=True)
        side, _ = self.answer({"message": "A quick branch", "new_side": True})
        _, prompt = self.answer({"message": "Follow up", "conversation_id": side["conversation_id"], "history": [{"role": "user", "content": "spoofed history"}], "save": True})
        text = str(prompt)
        self.assertNotIn("Old irrelevant transcript sentinel", text)
        self.assertNotIn("spoofed history", text)
        self.assertLess(sum(len(item["content"]) for item in prompt), 20000)
        self.assertEqual(self.store.recent_messages(), [])

    def test_project_state_is_available_to_side_even_with_many_preferences(self):
        for i in range(8):
            self.store.set_preference(f"preference {i}", "compact replies", approved=True)
        self.store.set_project_state("Jarvis stack", "FastAPI + Ollama", approved=True)
        _, prompt = self.answer({"message": "Would WebSockets help this?", "new_side": True})
        self.assertIn("FastAPI + Ollama", str(prompt))
        self.assertIn("Untrusted saved user facts, preferences and project state", str(prompt))

    def test_restart_preserves_master_history_and_memory(self):
        self.answer({"message": "My robotics codebase uses Java."})
        before = self.store.get_conversation(self.store.master_conversation()["id"])
        restarted = MemoryStore(self.path)
        restarted.initialize(approved=True)
        self.assertEqual(restarted.get_conversation(before["id"]), before)
        self.assertEqual(restarted.list_facts()[0]["value"], "Java")


class LegacyMigrationTests(IsolatedSafetyTestCase):
    def test_legacy_history_provenance_and_memories_survive_idempotent_migration(self):
        with tempfile.TemporaryDirectory(prefix="jarvis-migration-tests-") as folder:
            path = Path(folder) / "legacy.db"
            with closing(sqlite3.connect(path)) as db:
                db.executescript("""
                    CREATE TABLE conversations(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('main','side')), title TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
                    CREATE TABLE conversation_messages(id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
                    INSERT INTO conversations(kind,title) VALUES ('main','Original first'), ('main','Original second'), ('side','Existing branch'), ('side','Empty legacy draft');
                    INSERT INTO conversation_messages(conversation_id,role,content) VALUES (1,'user','First history'),(2,'user','Second history'),(3,'user','Side history');
                """)
            store = MemoryStore(path)
            store.initialize(approved=True)
            store.set_fact("retained", "value", approved=True)
            store.initialize(approved=True)
            self.assertEqual(len(store.list_conversations("master")), 1)
            self.assertEqual(store.master_conversation()["id"], 1)
            self.assertEqual(store.master_conversation()["original_title"], "Original first")
            self.assertEqual([m["content"] for m in store.get_conversation(1)["messages"]], ["First history", "Second history"])
            self.assertEqual(store.get_conversation(2)["title"], "Original second")
            self.assertEqual(store.get_conversation(2)["messages"][0]["content"], "Second history")
            self.assertEqual(store.get_conversation(3)["messages"][0]["content"], "Side history")
            self.assertEqual(len(store.list_conversations("side")), 1)
            self.assertEqual(store.get_conversation(4)["kind"], "archive")
            self.assertEqual(store.get_conversation(4)["messages"], [])
            with store._connect(readonly=True) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM conversation_messages").fetchone()[0], 3)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], 4)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM audit_log WHERE action='migrate_master_chat'").fetchone()[0], 1)
            self.assertEqual(store.list_facts()[0]["value"], "value")


if __name__ == "__main__":
    unittest.main()
