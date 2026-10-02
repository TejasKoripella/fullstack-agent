"""Disposable retrieval measurement; never reads or changes production memory."""
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import tracemalloc
import json
from memory import MemoryStore
from retrieval import relevant_context


def main():
    with TemporaryDirectory(dir=Path(__file__).parent) as folder:
        path=Path(folder)/'test.db'
        store=MemoryStore(path)
        store.initialize(approved=True)
        with store._connect() as db:
            db.executemany('INSERT INTO memories(kind,content,source) VALUES (?,?,?)',
                [('note','robotics report '+str(index)+' '+('x'*1000),'scale test') for index in range(5000)])
            db.execute("INSERT INTO memories(kind,content,source) VALUES ('note','robotics preferred language Java','scale test')")
        tracemalloc.start()
        start=time.perf_counter()
        results=relevant_context('robotics preferred language Java',db_path=path)
        elapsed=time.perf_counter()-start
        _,peak=tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert len(results)==6
        assert results[0]['text']=='robotics preferred language Java'
        print(json.dumps({'rows':5001,'returned':len(results),'elapsed_ms':round(elapsed*1000), 'peak_python_bytes':peak}))


if __name__=='__main__':
    main()
