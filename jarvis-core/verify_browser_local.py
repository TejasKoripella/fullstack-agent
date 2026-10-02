"""Opt-in live browser verification. Opens Chrome; never closes any browser.

Run under a normal non-administrator Windows account. Uses a temporary database,
safety latch, and loopback server. The production Jarvis server is untouched.
"""
import asyncio
import json
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import httpx
import uvicorn
import api
from memory import MemoryStore
from safety import SafetyState
import safety as safety_runtime
from security import require_browser_launch_context
from tool_broker import ToolBroker


def chrome_ids():
    return set(subprocess.check_output([
        "powershell", "-NoProfile", "-Command",
        "Get-Process chrome -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id",
    ], text=True).split())


def chrome_roots():
    raw = subprocess.check_output([
        "powershell", "-NoProfile", "-Command",
        "@(Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        "Where-Object { $_.CommandLine -and $_.CommandLine -notmatch '--type=' } | "
        "Select-Object -ExpandProperty ProcessId) | ConvertTo-Json -Compress",
    ], text=True).strip()
    values = json.loads(raw or "[]")
    return set(values if isinstance(values, list) else [values])


async def verify():
    require_browser_launch_context()
    with tempfile.TemporaryDirectory(prefix="jarvis-browser-verification-") as folder:
        manager = SafetyState(Path(folder) / "safety.json")
        store = MemoryStore(Path(folder) / "test.db")
        store.initialize(approved=True)
        with patch.object(safety_runtime, "safety", manager), patch.object(api, "memory", store), \
                patch.object(api, "broker", ToolBroker(store)):
            server = uvicorn.Server(uvicorn.Config(api.app, host="127.0.0.1", port=8001, log_level="warning"))
            task = asyncio.create_task(server.serve())
            before = chrome_roots()
            try:
                for _ in range(100):
                    if server.started:
                        break
                    if task.done():
                        await task
                    await asyncio.sleep(.02)
                assert server.started
                async with httpx.AsyncClient(base_url="http://127.0.0.1:8001", timeout=30) as client:
                    async def launch():
                        return await client.post("/tools/dispatch", json={"action_type": "open_app", "target": "Chrome",
                            "decision": "allow_once", "safety_epoch": manager.epoch})
                    response = await launch()
                    assert response.status_code == 200, response.text
                    print("Chrome request:", response.json())
                    await asyncio.sleep(2)
                    launched_roots=chrome_roots()
                    assert launched_roots, 'Chrome has no live browser root after launch'
                    print('Zero-process baseline:', not before, '; roots after launch:', launched_roots)
                    for _ in range(2):
                        page=await client.post('/tools/dispatch',json={'action_type':'open_resource','target':'Python documentation','decision':'allow_once','safety_epoch':manager.epoch})
                        assert page.status_code==200,page.text
                    assert launched_roots<=chrome_roots(), 'Launched Chrome root vanished during repeated URLs'
                    print('Repeated documentation URL requests: PASS; browser roots retained')
                    request = asyncio.create_task(launch())
                    await asyncio.sleep(.005)
                    stopped = await client.post("/safety/stop", json={"approved": True, "source": "local-test"})
                    response = await request
                    assert response.status_code in (200, 423), response.text
                    assert stopped.json()["state"] == "STOPPED"
                    assert not stopped.json()["cleanup_errors"]
                    print("Racing launch HTTP:", response.status_code, "; STOPPED; no cleanup errors")
                    assert (await launch()).status_code == 423
                    assert manager.children == {}, "Browser must never be owned"
                    assert before <= chrome_roots(), "Existing browser root vanished"
                    manager.resume()  # Explicit manual test harness action, no model path.
                    assert (await client.get("/voice/voices")).status_code == 200
                helpers = list(manager.children.values())
                shutdown_before = chrome_roots()
                server.should_exit = True
                await asyncio.wait_for(task, 10)
                for worker, _ in helpers:
                    worker.process.wait(timeout=3)
                    worker.process.stdin.close()
                    worker.process.stdout.close()
                assert shutdown_before <= chrome_roots()
                print("Graceful HTTP shutdown: PASS; all", len(shutdown_before), "Chrome browser roots retained")
            finally:
                server.should_exit = True
                if not task.done():
                    await asyncio.wait_for(task, 10)
                manager.stop("verification cleanup")


if __name__ == "__main__":
    asyncio.run(verify())
