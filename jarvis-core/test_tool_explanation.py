import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import api
import safety
from test_support import IsolatedSafetyTestCase


def chunk(text='', calls=None):
    return SimpleNamespace(message=SimpleNamespace(content=text,tool_calls=calls or []))


class ToolExplanationTests(IsolatedSafetyTestCase):
    def test_stop_during_followup_closes_stream_and_does_not_save_partial_reply(self):
        async def check():
            waiting=asyncio.Event()
            closed=asyncio.Event()
            async def followup():
                try:
                    yield chunk('Partial explanation')
                    waiting.set()
                    await asyncio.Event().wait()
                finally:
                    closed.set()
            request=api.ChatRequest(message='Open Jarvis project and explain this source',new_side=True)
            call=SimpleNamespace(function=SimpleNamespace(name='open_resource',arguments={'target':'Jarvis project'}))
            outcomes=[{'target':'Jarvis project','action_type':'open_resource','status':'approval_required'}]
            model=AsyncMock(side_effect=[[chunk(calls=[call])],followup()])
            with patch.object(api,'_prepare_chat',return_value=([],[{'role':'system','content':api.SYSTEM_PROMPT},{'role':'user','content':request.message}],None)), \
                    patch.object(api.memory,'log_action'),patch.object(api,'call_model',model), \
                    patch.object(api,'run_calls',return_value=outcomes) as run,patch.object(api,'_save_chat_result') as save:
                response=api.stream_chat(request)
                async def consume():
                    return [item async for item in response.body_iterator]
                task=asyncio.create_task(consume())
                await asyncio.wait_for(waiting.wait(),2)
                safety.safety.stop('during explanation')
                safety.safety.stop('repeat stop')
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(closed.is_set())
                save.assert_not_called()
                run.assert_called_once()
                self.assertEqual(safety.safety.status()['active_operations'],0)
        asyncio.run(check())

    def test_stream_keeps_approval_then_explains_without_more_tools(self):
        async def check():
            request=api.ChatRequest(message='Open Jarvis project and explain dictionaries',new_side=True)
            call=SimpleNamespace(function=SimpleNamespace(name='open_resource',arguments={'target':'Jarvis project'}))
            outcomes=[{'target':'Jarvis project','action_type':'open_resource','status':'approval_required'}]
            model=AsyncMock(side_effect=[[chunk(calls=[call])],[chunk('A dictionary maps keys to values.')]])
            with patch.object(api,'_prepare_chat',return_value=([],[{'role':'system','content':api.SYSTEM_PROMPT},{'role':'user','content':request.message}],None)), \
                    patch.object(api.memory,'log_action'),patch.object(api,'call_model',model), \
                    patch.object(api,'run_calls',return_value=outcomes) as run, \
                    patch.object(api,'_save_chat_result',side_effect=lambda req,recall,answer:{'reply':answer}):
                response=api.stream_chat(request)
                events=[event async for event in response.body_iterator]
            self.assertIn('"type": "tools"',events[0])
            self.assertIn('open your Jarvis project',''.join(events))
            self.assertIn('maps keys to values',''.join(events))
            self.assertEqual(model.await_count,2)
            self.assertEqual(model.await_args_list[1].kwargs['tools'],[])
            followup=model.await_args_list[1].kwargs['messages']
            self.assertTrue(followup[-1]['content'].endswith(request.message))
            self.assertEqual(followup[0]['role'],'system')
            self.assertFalse(any(item['role']=='system' for item in followup[1:]))
            run.assert_called_once()
        asyncio.run(check())

    def test_failed_explanation_preserves_receipt_and_never_dispatches(self):
        async def check():
            with patch.object(api,'call_model',AsyncMock(side_effect=OSError('offline'))),patch.object(api,'run_calls') as run:
                text=''.join([token async for token in api.tool_explanation([{'role':'user','content':'Explain'}],[])])
                self.assertIn('action outcomes above still apply',text)
                run.assert_not_called()
        asyncio.run(check())

    def test_stop_blocks_followup_before_model_and_plain_open_does_not_qualify(self):
        self.assertFalse(api.tool_explanation_requested('Open Jarvis project'))
        async def check():
            safety.safety.stop('between tool and explanation')
            with patch.object(api,'call_model',AsyncMock()) as model:
                with self.assertRaises(safety.StoppedError):
                    _=[token async for token in api.tool_explanation([],[])]
                model.assert_not_called()
        asyncio.run(check())

    def test_unexpected_second_phase_tool_request_is_not_executed(self):
        async def check():
            with patch.object(api,'call_model',AsyncMock(return_value=[chunk(calls=[object()])])),patch.object(api,'run_calls') as run:
                text=''.join([token async for token in api.tool_explanation([],[])])
                self.assertIn('Explanation unavailable',text)
                run.assert_not_called()
        asyncio.run(check())
