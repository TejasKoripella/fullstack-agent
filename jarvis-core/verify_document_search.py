"""Opt-in real Qwen search verification with disposable files and isolated history."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from fastapi.testclient import TestClient
import api
import safety
from memory import MemoryStore
from tool_broker import ToolBroker


def main():
    with TemporaryDirectory(dir=Path(__file__).parent) as folder:
        root = Path(folder)
        store = MemoryStore(root / 'test.db')
        store.initialize(approved=True)
        state = safety.SafetyState(root / 'safety.json')
        (root / 'robotics-notes.txt').write_text('Contents must never enter a filename result.')
        try:
            with patch.object(api,'memory',store), patch.object(api,'broker',ToolBroker(store)), \
                    patch.object(safety,'safety',state), patch('tool_broker.documents_root',return_value=root):
                client = TestClient(api.app,base_url='http://127.0.0.1:8000')
                result = client.post('/chat',json={'message':'Find filenames containing robotics in Windows Documents. Use the filename search tool.','new_side':True,'save':False})
                assert result.status_code == 200, result.text
                body = result.json()
                assert body['tool_results'][0]['status'] == 'searched', body
                assert body['tool_results'][0]['matches'] == [{'name':'robotics-notes.txt','path':'robotics-notes.txt'}], body
                assert 'Contents must never' not in body['reply'], body
                print('PASS: real Qwen requested scoped filename search; matching filename returned, contents excluded; temporary Side history only.')
        finally:
            state.stop('verification cleanup')


if __name__ == '__main__':
    main()
