from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, Mock
from contextlib import nullcontext
from types import SimpleNamespace
from fastapi.testclient import TestClient
import api
import safety
from memory import MemoryStore
from tool_broker import ToolBroker
from test_support import IsolatedSafetyTestCase


class DocumentSearchTests(IsolatedSafetyTestCase):
    def test_linked_and_reparse_entries_are_never_resolved_or_traversed(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            store = MemoryStore(root / 'test.db')
            store.initialize(approved=True)
            link = Mock(name='linked-entry')
            link.name = 'linked'
            link.is_symlink.return_value = True
            junction = Mock(name='junction-entry')
            junction.name = 'junction'
            junction.is_symlink.return_value = False
            junction.stat.return_value = SimpleNamespace(st_file_attributes=0x400)
            with patch('tool_broker.documents_root',return_value=root), \
                    patch('tool_broker.os.scandir',return_value=nullcontext(iter([link,junction]))) as scan:
                result=ToolBroker(store).find_documents('secret',approved=True)
                self.assertEqual(result['matches'],[])
                scan.assert_called_once_with(root.resolve())
                link.stat.assert_not_called()
                junction.is_dir.assert_not_called()

    def test_stop_during_enumeration_produces_no_success_audit(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            store = MemoryStore(root / 'test.db')
            store.initialize(approved=True)
            def interrupted():
                safety.safety.stop('stop during search')
                yield Mock()
            with patch('tool_broker.documents_root',return_value=root), \
                    patch('tool_broker.os.scandir',return_value=nullcontext(interrupted())), \
                    patch.object(store,'log_action') as audit:
                with self.assertRaises(safety.StoppedError):
                    ToolBroker(store).find_documents('notes',approved=True)
                self.assertFalse(audit.call_args.kwargs['allowed'])

    def test_unavailable_folder_is_reported_incomplete(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            store = MemoryStore(root / 'test.db')
            store.initialize(approved=True)
            with patch('tool_broker.documents_root',return_value=root), \
                    patch('tool_broker.os.scandir',side_effect=PermissionError('unavailable')):
                result=ToolBroker(store).find_documents('notes',approved=True)
                self.assertTrue(result['partial'])
                self.assertEqual(result['matches'],[])

    def test_search_scope_limits_approval_and_stop(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            store = MemoryStore(root / "test.db")
            store.initialize(approved=True)
            broker = ToolBroker(store)
            (root / "nested").mkdir()
            (root / "nested" / "Robotics notes.txt").write_text("private contents")
            (root / ".hidden").mkdir()
            (root / ".hidden" / "robotics.txt").write_text("hidden")
            with patch('tool_broker.documents_root', return_value=root), patch.object(api,'broker',broker):
                client = TestClient(api.app,base_url='http://127.0.0.1:8000')
                self.assertEqual(client.post('/tools/find-documents',json={'query':'robotics'}).status_code,403)
                result = client.post('/tools/find-documents',json={'query':'ROBOTICS','approved':True}).json()
                self.assertEqual(result['matches'],[{'name':'Robotics notes.txt','path':'nested/Robotics notes.txt'}])
                self.assertFalse(result['partial'])
                self.assertNotIn('private contents',str(result))
                for query in ('../secret','C:\\Users\\vijay koripella','.', ' '):
                    self.assertEqual(client.post('/tools/find-documents',json={'query':query,'approved':True}).status_code,403)
                for index in range(55):
                    (root / ('robotics-%02d.txt' % index)).touch()
                result=broker.find_documents('robotics',approved=True)
                self.assertEqual(len(result['matches']),50)
                self.assertTrue(result['partial'])
                safety.safety.stop('search test')
                self.assertEqual(client.post('/tools/find-documents',json={'query':'robotics','approved':True}).status_code,423)
