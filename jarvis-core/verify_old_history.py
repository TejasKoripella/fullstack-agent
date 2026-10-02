"""Real Qwen recall from older Master history; isolated database only."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from fastapi.testclient import TestClient
import api
from memory import MemoryStore


def main():
    with TemporaryDirectory(dir=Path(__file__).parent) as folder:
        store=MemoryStore(Path(folder)/'test.db')
        store.initialize(approved=True)
        master=store.master_conversation()['id']
        store.add_conversation_message(master,'user','Orion robotics codebase language is Rust.',approved=True)
        for index in range(100):
            store.add_conversation_message(master,'user','Orion robotics status note '+str(index),approved=True)
        assert store.list_facts()==[]
        with patch.object(api,'memory',store),TestClient(api.app,base_url='http://127.0.0.1:8000') as client:
            response=client.post('/chat',json={'message':'What language does the Orion robotics codebase use? Answer with only the language name.','new_side':True})
            response.raise_for_status()
            body=response.json()
            assert 'rust' in body['reply'].lower(),body['reply']
            assert body['saved'] is False
            assert store.list_facts()==[]
            print('PASS: real Qwen Side recalled Rust solely from older Master history beyond 100 newer weak matches; no durable facts written.')


if __name__=='__main__':
    main()
