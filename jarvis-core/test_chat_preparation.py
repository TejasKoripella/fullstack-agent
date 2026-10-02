import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import api
import safety
from test_support import IsolatedSafetyTestCase


class ChatPreparationTests(IsolatedSafetyTestCase):
    def test_stop_then_resume_during_preparation_cannot_revive_old_request(self):
        def slow_context(request):
            time.sleep(.2)
            return [],[],None
        async def check():
            with patch.object(api,'_prepare_chat',side_effect=slow_context), \
                    patch.object(api.memory,'log_action'), patch.object(api,'call_model',new=AsyncMock()) as model:
                with safety.safety.operation():
                    request=asyncio.create_task(api.chat(api.ChatRequest(message='Hello')))
                    await asyncio.sleep(.01)
                    safety.safety.stop('preparation race')
                    safety.safety.resume()
                    with self.assertRaises(safety.StoppedError):
                        await request
                model.assert_not_called()
        asyncio.run(check())

    def test_context_preparation_does_not_block_safety_event_loop(self):
        def slow_context(request):
            time.sleep(.3)
            return [],[],None
        async def check():
            response=SimpleNamespace(message=SimpleNamespace(tool_calls=[],content='ready'))
            with patch.object(api,'_prepare_chat',side_effect=slow_context), \
                    patch.object(api.memory,'log_action'), patch.object(api,'call_model',new=AsyncMock(return_value=response)), \
                    patch.object(api,'_save_chat_result',return_value={}):
                request=asyncio.create_task(api.chat(api.ChatRequest(message='Hello')))
                await asyncio.sleep(.01)
                # The safety loop must run while context is still preparing.
                self.assertFalse(request.done(),'Context preparation blocked the event loop until generation completed')
                await request
        asyncio.run(check())
