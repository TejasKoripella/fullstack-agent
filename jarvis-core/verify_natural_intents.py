"""Opt-in real Qwen wording/typo checks, disposable history, no app launches."""
from pathlib import Path
import tempfile
from unittest.mock import patch
import sys
from fastapi.testclient import TestClient
import api
import safety
from memory import MemoryStore
from tool_broker import ToolBroker

CASES=[('Open Spotify','Spotify'),('Pull up Spotify','Spotify'),('Bring Spotify up','Spotify'),
       ('Can you open Spotify for me?','Spotify'),('Can you get Spotify open?','Spotify'),
       ('Spotify please','Spotify'),('Could you pull Spotify up for me?','Spotify'),
       ('open spotfy','Spotify'),('pull up spoitfy','Spotify'),('Open Chrome','Chrome'),
       ('pull up chrome','Chrome'),('Open my Jarvis project','Jarvis project'),
       ('pull up my jarvis project','Jarvis project'),('play my playlist','Default playlist'),
       ('put my playlist on','Default playlist')]

def main():
    with tempfile.TemporaryDirectory() as folder:
        manager=safety.SafetyState(Path(folder)/'safety.json')
        store=MemoryStore(Path(folder)/'test.db')
        with patch.object(safety,'safety',manager):
            store.initialize(approved=True)
            with patch.object(api,'memory',store),patch.object(api,'broker',ToolBroker(store)),patch('tool_broker.os.startfile') as launch,TestClient(api.app,base_url='http://127.0.0.1:8000') as client:
                for phrase,target in ([] if '--focused' in sys.argv else CASES):
                    response=client.post('/chat',json={'message':phrase,'new_side':True})
                    assert response.status_code==200,(phrase,response.text)
                    result=response.json()
                    outcomes=result['tool_results']
                    assert len(outcomes)==1 and outcomes[0]['target']==target and outcomes[0]['status']=='approval_required',(phrase,result)
                    print('PASS:',phrase,'->',target,flush=True)
                response=client.post('/chat',json={'message':'Can you pull up Spotify and put my playlist on?','new_side':True})
                assert response.status_code==200,response.text
                outcomes=response.json()['tool_results']
                assert {(item['target'],item['status']) for item in outcomes}=={('Spotify','approval_required'),('Default playlist','approval_required')},response.text
                launch.assert_not_called()
                assert not store.list_facts()
                print('PASS: multi-intent request; no external launch or Side facts.',flush=True)
                first=client.post('/chat',json={'message':'Open Spotify','new_side':True})
                first.raise_for_status()
                chat_id=first.json()['conversation_id']
                resumed=client.post('/chat',json={'message':'bring that back up','conversation_id':chat_id})
                resumed.raise_for_status()
                assert [(item['target'],item['status']) for item in resumed.json()['tool_results']]==[('Spotify','approval_required')],resumed.text
                print('PASS: same-chat contextual reopening remains behind the broker.',flush=True)
            manager.stop('verification cleanup')

if __name__=='__main__': main()
