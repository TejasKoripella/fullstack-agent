"""Disposable loopback UI fixture. No personal files or production history."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import uvicorn
import api
import safety as safety_runtime
from safety import SafetyState
from memory import MemoryStore
from tool_broker import ToolBroker


async def main():
    with TemporaryDirectory(dir=Path(__file__).parent) as folder:
        root = Path(folder)
        manager = SafetyState(root / 'safety.json')
        store = MemoryStore(root / 'test.db')
        with patch.object(safety_runtime, 'safety', manager):
            store.initialize(approved=True)
            (root / 'reference.txt').write_text('The calibration code is cobalt-47.', encoding='utf-8')
            with patch.object(api, 'memory', store), patch.object(api, 'broker', ToolBroker(store)), patch('tool_broker.documents_root', return_value=root):
                server = uvicorn.Server(uvicorn.Config(api.app, host='127.0.0.1', port=8001, log_level='warning'))
                task = asyncio.create_task(server.serve())
                try:
                    await asyncio.sleep(180)
                finally:
                    server.should_exit = True
                    await task
                    manager.stop('verification cleanup')


if __name__ == '__main__':
    asyncio.run(main())
