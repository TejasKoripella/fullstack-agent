from pathlib import Path
from tempfile import TemporaryDirectory
from test_support import IsolatedSafetyTestCase
from memory import MemoryStore
import retrieval


class RetrievalScaleTests(IsolatedSafetyTestCase):
    def test_strong_old_master_match_survives_many_recent_weak_matches(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path=Path(folder)/'test.db'
            store=MemoryStore(path)
            store.initialize(approved=True)
            master=store.master_conversation()['id']
            old='robotics codebase language is Java'
            store.add_conversation_message(master,'user',old,approved=True)
            for index in range(100):
                store.add_conversation_message(master,'user','robotics status note '+str(index),approved=True)
            results=retrieval.relevant_context('What language does my robotics codebase use?',db_path=path)
            self.assertEqual(results[0]['text'],old)

    def test_streamed_top_results_match_exhaustive_ranking_and_deduplication(self):
        with TemporaryDirectory(dir=Path(__file__).parent) as folder:
            path=Path(folder)/'test.db'
            store=MemoryStore(path)
            store.initialize(approved=True)
            notes=['robotics Java preferred language']+[
                ('robotics Java' if index%3==0 else 'robotics')+' report '+str(index%45)
                for index in range(300)]
            notes+=['  ROBOTICS JAVA preferred language  ']
            with store._connect() as db:
                db.executemany('INSERT INTO memories(kind,content) VALUES (?,?)',[('note',text) for text in notes])
            for query in ('robotics Java preferred language','robotics','unmatched'):
                for limit in (1,6,20):
                    tokens=retrieval._tokens(query)
                    candidates=[]
                    for index,text in enumerate(notes,1):
                        score=retrieval._match_score(tokens,text)
                        if score:
                            candidates.append({'score':score+.5,'id':index,'text':text,'source':'memory:note'})
                    candidates.sort(key=lambda item:(item['score'],item['id']),reverse=True)
                    seen=set()
                    expected=[]
                    for item in candidates:
                        key=item['text'].strip().lower()
                        if key not in seen:
                            seen.add(key)
                            expected.append(item)
                    with self.subTest(query=query,limit=limit):
                        self.assertEqual(retrieval.relevant_context(query,limit=limit,db_path=path),expected[:limit])
