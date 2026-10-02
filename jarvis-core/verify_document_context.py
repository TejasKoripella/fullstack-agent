"""Opt-in real Qwen selected-document check with disposable files and memory."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import zipfile
from fastapi.testclient import TestClient
import api
import safety as safety_runtime
from safety import SafetyState
from memory import MemoryStore
from tool_broker import ToolBroker


def main():
    with TemporaryDirectory(dir=Path(__file__).parent) as folder:
        root = Path(folder)
        store = MemoryStore(root / 'test.db')
        manager = SafetyState(root / 'safety.json')
        with patch.object(safety_runtime, 'safety', manager):
            store.initialize(approved=True)
            (root / 'reference.txt').write_text('The calibration code is cobalt-47.', encoding='utf-8')
            with zipfile.ZipFile(root / 'reference.docx', 'w') as archive:
                archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>The calibration code is amber-62.</w:t></w:r></w:p></w:body></w:document>')
            with patch.object(api, 'memory', store), patch.object(api, 'broker', ToolBroker(store)), patch('tool_broker.documents_root', return_value=root), TestClient(api.app, base_url='http://127.0.0.1:8000') as client:
                response = client.post('/chat', json={'message': 'What calibration code is stated in the selected document? Reply only the code.', 'new_side': True, 'document_path': 'reference.txt'})
                response.raise_for_status()
                result = response.json()
                assert 'cobalt-47' in result['reply'].lower(), result['reply']
                assert result['saved'] is False
                assert store.list_facts() == []
                print('PASS: real Qwen used explicitly selected document; Side wrote no durable facts.')
                streamed = client.post('/chat/stream', json={'message': 'What calibration code is stated in the selected document? Reply only the code.', 'new_side': True, 'document_path': 'reference.txt'})
                streamed.raise_for_status()
                assert 'cobalt-47' in streamed.text.lower(), streamed.text
                assert store.list_facts() == []
                print('PASS: real Qwen streaming used the same selected document; no durable facts written.')
                word = client.post('/chat/stream', json={'message': 'What calibration code is stated in the selected document? Reply only the code.', 'new_side': True, 'document_path': 'reference.docx'})
                word.raise_for_status()
                assert 'amber-62' in word.text.lower(), word.text
                assert store.list_facts() == []
                print('PASS: real Qwen streaming read extracted Word text; Side memory remained isolated.')
                (root / 'calibration.py').write_text('CALIBRATION_CODE = "silver-29"\n', encoding='utf-8')
                with patch('tool_broker.PROJECT_ROOT', root):
                    project = client.post('/chat/stream', json={'message': 'What calibration code is stated in the selected project file? Reply only the code.', 'new_side': True, 'project_path': 'calibration.py'})
                project.raise_for_status()
                assert 'silver-29' in project.text.lower(), project.text
                assert store.list_facts() == []
                print('PASS: real Qwen streaming used guarded project source; Side memory remained isolated.')
            manager.stop('verification cleanup')


if __name__ == '__main__':
    main()
