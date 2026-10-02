from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import zipfile
from fastapi.testclient import TestClient
from fastapi import HTTPException
import api
from memory import MemoryStore
from tool_broker import ToolBroker
from test_support import IsolatedSafetyTestCase


class DocumentContextTests(IsolatedSafetyTestCase):
    def test_project_reference_is_scoped_bounded_and_one_at_a_time(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            store = MemoryStore(root/'test.db')
            store.initialize(approved=True)
            (root/'README.md').write_text('project-only-marker '+('a'*6500))
            with patch.object(api,'memory',store),patch.object(api,'broker',ToolBroker(store)),patch('tool_broker.PROJECT_ROOT',root):
                _, messages, _ = api._prepare_chat(api.ChatRequest(message='Explain selected source',new_side=True,project_path='README.md'))
                self.assertIn('project-only-marker', messages[-1]['content'])
                self.assertIn('truncated', messages[-1]['content'])
                self.assertLess(len(messages[-1]['content']),6400)
                _, later, _ = api._prepare_chat(api.ChatRequest(message='New question',new_side=True))
                self.assertNotIn('project-only-marker', str(later))
                self.assertEqual(store.list_facts(),[])
                for path in ('../outside.md','.env',r'C:\Users\vijay koripella\secret.txt'):
                    with self.assertRaises(HTTPException) as error:
                        api._prepare_chat(api.ChatRequest(message='Explain',new_side=True,project_path=path))
                    self.assertEqual(error.exception.status_code,403)
                with self.assertRaises(HTTPException) as error:
                    api._prepare_chat(api.ChatRequest(message='Explain',new_side=True,project_path='README.md',document_path='note.txt'))
                self.assertEqual(error.exception.status_code,422)

    def test_docx_contents_and_malformed_xml_recovery(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root = Path(folder)
            store = MemoryStore(root/'test.db')
            store.initialize(approved=True)
            for name, xml in [('good.docx', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>calibration cobalt-47</w:t></w:r></w:p></w:body></w:document>'), ('bad.docx', '<broken')]:
                with zipfile.ZipFile(root/name, 'w') as archive:
                    archive.writestr('word/document.xml', xml)
            with patch.object(api,'memory',store),patch.object(api,'broker',ToolBroker(store)),patch('tool_broker.documents_root',return_value=root):
                _, messages, _ = api._prepare_chat(api.ChatRequest(message='Summarize',new_side=True,document_path='good.docx'))
                self.assertIn('calibration cobalt-47', messages[-1]['content'])
                with TestClient(api.app, base_url='http://127.0.0.1:8000') as client:
                    read = client.post('/tools/read-document', json={'path':'bad.docx','approved':True})
                    self.assertEqual(read.status_code, 422)
                    chat = client.post('/chat/stream', json={'message':'Summarize','new_side':True,'document_path':'bad.docx'})
                    self.assertEqual(chat.status_code, 422)
                    recovered = client.post('/tools/read-document', json={'path':'good.docx','approved':True})
                    self.assertEqual(recovered.status_code, 200)
                    self.assertIn('cobalt-47', recovered.json()['content'])

    def test_explicit_document_context_is_bounded_one_shot_and_not_memory(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            root=Path(folder)
            store=MemoryStore(root/'test.db')
            store.initialize(approved=True)
            (root/'note.txt').write_text('reference-only-secret '+('a'*6500))
            with patch.object(api,'memory',store),patch.object(api,'broker',ToolBroker(store)),patch('tool_broker.documents_root',return_value=root):
                _,messages,_=api._prepare_chat(api.ChatRequest(message='Explain this reference',new_side=True,document_path='note.txt'))
                reference=next(item['content'] for item in messages if 'Explicitly selected document reference' in item['content'])
                self.assertIn('Untrusted',reference)
                self.assertIn('truncated',reference)
                self.assertLess(len(reference),6300)
                self.assertIn('reference-only-secret',reference)
                _,later,_=api._prepare_chat(api.ChatRequest(message='Another question',new_side=True))
                self.assertNotIn('reference-only-secret',str(later))
                self.assertEqual(store.list_facts(),[])
                for path in ('../outside.txt',r'C:\Users\vijay koripella\secret.txt'):
                    with self.assertRaises(HTTPException) as error:
                        api._prepare_chat(api.ChatRequest(message='Read',new_side=True,document_path=path))
                    self.assertEqual(error.exception.status_code,403)
