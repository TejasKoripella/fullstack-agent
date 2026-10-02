"""Real-Qwen coordination check: approvals only, no application launches."""
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
        manager = safety.SafetyState(root / 'safety.json')
        (root / 'robotics.txt').write_text('Private test contents excluded from search')
        try:
            with patch.object(api,'memory',store), patch.object(api,'broker',ToolBroker(store)), \
                    patch.object(safety,'safety',manager), patch('tool_broker.os.startfile') as launch, \
                    patch('tool_broker.documents_root',return_value=root):
                client = TestClient(api.app,base_url='http://127.0.0.1:8000')
                response = client.post('/chat',json={'message':'Open Jarvis project and Jarvis verification. Request both using tools.','new_side':True})
                assert response.status_code == 200,response.text
                calls=response.json()['tool_results']
                assert {(item['action_type'],item['target']) for item in calls} == {
                    ('open_resource','Jarvis project'),('open_resource','Jarvis verification')},calls
                assert all(item['status']=='approval_required' for item in calls),calls
                launch.assert_not_called()
                assert store.list_facts()==[]
                print('PASS: real Qwen requested both registered resources; independent fresh approvals; no apps launched or long-term facts saved.')
                response=client.post('/chat',json={'message':'Find filenames containing robotics in Windows Documents and open Jarvis project. Request both tools.','new_side':True})
                assert response.status_code==200,response.text
                calls=response.json()['tool_results']
                assert any(item['action_type']=='open_resource' and item['status']=='approval_required' for item in calls),calls
                search=next(item for item in calls if item['action_type']=='find_documents')
                assert search['matches']==[{'name':'robotics.txt','path':'robotics.txt'}],calls
                assert 'Private test contents' not in response.json()['reply']
                launch.assert_not_called()
                print('PASS: real Qwen coordinated opening approval plus filename search; separate outcomes, no contents or app launches.')
                response=client.post('/chat/stream',json={'message':'Open Python documentation using its registered resource.','new_side':True})
                assert response.status_code==200,response.text
                import json
                done=next(json.loads(line[6:]) for line in response.text.splitlines()
                          if line.startswith('data: ') and json.loads(line[6:]).get('type')=='done')
                assert [(item['action_type'],item['target'],item['status']) for item in done['tool_results']] == [
                    ('open_resource','Python documentation','approval_required')],done
                launch.assert_not_called()
                assert store.list_facts()==[]
                print('PASS: real Qwen streaming requested registered webpage; fresh approval required, no launch or memory write.')
        finally:
            manager.stop('compound verification cleanup')


if __name__=='__main__':
    main()
