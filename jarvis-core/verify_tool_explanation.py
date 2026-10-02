"""Real-Qwen compound action/help check; temporary history and no Windows launches."""
import json
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
        root=Path(folder)
        manager=safety.SafetyState(root/'safety.json')
        with patch.object(safety,'safety',manager):
            store=MemoryStore(root/'test.db')
            store.initialize(approved=True)
            with patch.object(api,'memory',store),patch.object(api,'broker',ToolBroker(store)),patch('tool_broker.os.startfile') as launch,TestClient(api.app,base_url='http://127.0.0.1:8000') as client:
                response=client.post('/chat/stream',json={'message':'Open Jarvis project and Python documentation using their registered resource tools, and explain how Python dictionaries work.','new_side':True})
                response.raise_for_status()
                events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
                assert events[0]['type']=='tools',events
                result=events[-1]
                assert result['type']=='done',result
                assert {(item['target'],item['status']) for item in result['tool_results']}=={
                    ('Jarvis project','approval_required'),('Python documentation','approval_required')},result
                assert 'key' in result['reply'].lower() and 'value' in result['reply'].lower(),result['reply']
                assert store.list_facts()==[]
                launch.assert_not_called()
                print('PASS: real Qwen returned both fresh approvals before streaming dictionary explanation; no app launches or Side facts.')
                (root/'diagnostic.py').write_text('CALIBRATION_CODE = "silver-29"\n',encoding='utf-8')
                (root/'config').mkdir()
                (root/'config'/'known_resources.json').write_text(json.dumps({
                    'Python documentation':{'kind':'webpage','url':'https://docs.python.org/3/'},
                    'Verification project':{'kind':'project','path':'.'},
                    'Verification playlist':{'kind':'playlist','uri':'spotify:playlist:'+'a'*22}
                }),encoding='utf-8')
                with patch('tool_broker.PROJECT_ROOT',root):
                    source=client.post('/chat/stream',json={
                        'message':'Open Verification project, Python documentation, and Verification playlist using their registered resource tools, and explain what CALIBRATION_CODE equals in the selected project file. Quote the exact value.',
                        'new_side':True,'project_path':'diagnostic.py'})
                source.raise_for_status()
                source_events=[json.loads(line[6:]) for line in source.text.splitlines() if line.startswith('data: ')]
                assert source_events[0]['type']=='tools',source_events
                source_result=source_events[-1]
                assert source_result['type']=='done',source_result
                assert {(item['target'],item['status']) for item in source_result['tool_results']}=={
                    ('Python documentation','approval_required'),('Verification project','approval_required'),
                    ('Verification playlist','approval_required')},source_result
                assert 'silver-29' in source_result['reply'],source_result['reply']
                assert store.list_facts()==[]
                launch.assert_not_called()
                print('PASS: three-resource project/docs/playlist request preserved selected source through tool-free explanation; no launch or Side memory write.')
            manager.stop('verification cleanup')


if __name__=='__main__':
    main()
