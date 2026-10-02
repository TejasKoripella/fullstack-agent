const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('ui/app.js','utf8');
const handler = source.slice(source.indexOf('    async function requestTool('),source.indexOf('    async function streamReply('));
async function check(failure) {
  let resolve;const pending=new Promise(r=>resolve=r);const status={textContent:''};let settled=0,errors=0;
  const context={conversation:{},activeSession:{id:42},setAssistantState:state=>{if(state==='error')errors++;return 1;},settleTool:()=>settled++,
    document:{getElementById:()=>({textContent:''})},safeFetch:()=>pending};
  Object.assign(context,{safetyStopped:false,safetyEpoch:0,chatAbort:null,AbortController,deviceReady:async()=>true});vm.createContext(context);vm.runInContext('let conversationVersion=0;'+handler+';this.request=requestTool;this.switchChat=()=>{conversationVersion++;};',context);
  const request=context.request('open_app','Spotify',status);
  context.switchChat();status.textContent='New chat status';
  resolve({ok:!failure,json:async()=>failure?{detail:'Old request failed'}:{status:'executed'}});
  await request;
  assert.equal(status.textContent,'New chat status');assert.equal(settled,0);assert.equal(errors,0);
}
(async()=>{await check(false);await check(true);console.log('PASS: late tool success and failure cannot overwrite another chat');})().catch(error=>{console.error(error);process.exitCode=1;});
