"""Persistent memory checks using a disposable database, never live chat data."""
import tempfile
import unittest
from pathlib import Path
from memory import MemoryStore

class PersistentMemoryTests(unittest.TestCase):
    def test_memory_preferences_and_project_state_survive_reopen(self):
        with tempfile.TemporaryDirectory(prefix="jarvis-memory-tests-") as folder:
            path = Path(folder) / "test.db"
            store = MemoryStore(path)
            store.initialize(approved=True)
            store.add_memory("system", "Jarvis uses local Qwen.", source="test", approved=True)
            store.set_preference("assistant_name", "Jarvis", approved=True)
            store.set_project_state("phase", "test", approved=True)
            reopened = MemoryStore(path)
            self.assertEqual(reopened.get_preference("assistant_name"), "Jarvis")
            self.assertEqual(reopened.get_project_state("phase"), "test")
            self.assertEqual(len(reopened.search_memories("Qwen")), 1)

    def test_unapproved_memory_write_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="jarvis-memory-tests-") as folder:
            store = MemoryStore(Path(folder) / "test.db")
            store.initialize(approved=True)
            with self.assertRaises(PermissionError):
                store.add_memory("system", "Do not persist this.")
            self.assertEqual(store.search_memories("persist"), [])

if __name__ == "__main__":
    unittest.main()
