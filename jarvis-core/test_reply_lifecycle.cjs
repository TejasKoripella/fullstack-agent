const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('ui/app.js', 'utf8');
const streamHandler = source.slice(source.indexOf('    async function streamReply('), source.indexOf('    async function showModelTools('));
const speechHandler = source.slice(source.indexOf('    async function speakReply('), source.indexOf('    function renderDocuments('));
const stopHandler = source.slice(source.indexOf('    function stopSpeech('), source.indexOf('    let assistantStateVersion'));
const deferred = () => { let resolve;const promise=new Promise(r=>resolve=r);return {resolve,promise}; };
// Double Enter after a send must not submit an empty required field.
let enterHandler,submissions=0;
const composerContext={messageInput:{value:'',addEventListener:(_,fn)=>enterHandler=fn},form:{requestSubmit:()=>submissions++}};
vm.createContext(composerContext);
vm.runInContext(source.slice(source.indexOf('    messageInput.addEventListener("keydown"'),source.indexOf('    async function postApproved(')),composerContext);
enterHandler({key:'Enter',preventDefault(){}});
assert.equal(submissions,0);
composerContext.messageInput.value='Open Spotify';
enterHandler({key:'Enter',preventDefault(){}});
assert.equal(submissions,1);
async function streamTest(events, expectedError, expectedTools=0) {
  let cancelled=0,released=0,tokens=[],toolEvents=[];
  const chunks=events.map(event=>({value:new TextEncoder().encode(event),done:false}));
  const reader={read:async()=>chunks.shift()||{done:true},cancel:async()=>{cancelled++;},releaseLock:()=>{released++;}};
  const context={TextDecoder,safeFetch:async()=>({ok:true,body:{getReader:()=>reader}})};
  Object.assign(context,{safetyStopped:false,safetyEpoch:0,chatAbort:null,AbortController,deviceReady:async()=>true});vm.createContext(context);vm.runInContext(streamHandler+';this.reply=streamReply;',context);
  if(expectedError) await assert.rejects(context.reply({},t=>tokens.push(t)),expectedError);
  else assert.equal((await context.reply({},t=>tokens.push(t),results=>toolEvents.push(results))).reply,'Complete');
  assert.equal(cancelled,1);assert.equal(released,1);
  assert.equal(toolEvents.length,expectedTools);
  return tokens;
}
(async()=>{
  const valid='data: '+JSON.stringify({type:'token',text:'Hello'})+'\n\ndata: '+JSON.stringify({type:'done',reply:'Complete'})+'\n\n';
  assert.deepEqual(await streamTest([valid.slice(0,12),valid.slice(12)]),['Hello']);
  assert.deepEqual(await streamTest(['data: {"type":"tools","tool_results":[{"status":"approval_required"}]}\n\n'+valid],undefined,1),['Hello']);
  await streamTest(['data: broken\n\n'],/JSON|Unexpected/);
  await streamTest(['data: {"type":"error","detail":"Offline"}\n\n'],/Offline/);
  await streamTest(['data: {"type":"token","text":"Partial"}\n\n'],/before completion/);
  const pending=deferred();let paused=0,revoked=0,players=[],states=[],utterances=[];
  const context={window:{},speechSynthesis:{cancel(){}},AbortController,
    speakInput:{checked:true},document:{getElementById:()=>({textContent:''})},
    safeFetch:()=>pending.promise,URL:{createObjectURL:()=> 'blob:test',revokeObjectURL:()=>{revoked++;}},
    Audio:function(){this.pause=()=>paused++;this.play=async()=>{};players.push(this);},
    SpeechSynthesisUtterance:function(){utterances.push(this);},
    setAssistantState:state=>states.push(state)};
  Object.assign(context,{safetyStopped:false,safetyEpoch:0,chatAbort:null,AbortController,deviceReady:async()=>true});vm.createContext(context);
  vm.runInContext('let speechVersion=0,speechAbort=null,currentAudio=null,currentAudioUrl=null,localVoice=null;'+stopHandler+speechHandler+';this.speak=speakReply;this.stop=stopSpeech;this.browserVoice=()=>localVoice={};',context);
  const first=context.speak('Old');context.speakInput.checked=false;context.stop();
  pending.resolve({ok:true,blob:async()=>({})});await first;
  assert.equal(players.length,0,'Muting pending synthesis must prevent late playback');
  context.speakInput.checked=true;await context.speak('New');
  const oldCallback=players[0].onended;
  players[0].onplaying();assert.equal(states.at(-1),'speaking');
  context.stop();oldCallback();assert.equal(states.at(-1),'speaking','Old callback must not overwrite state');
  assert.equal(paused,1);assert.ok(revoked>=1);
  context.window.speechSynthesis = context.speechSynthesis;
  context.speechSynthesis.speak = () => {};
  context.browserVoice();
  await context.speak('Browser fallback');
  assert.equal(utterances.length,1);
  await utterances[0].onerror();
  assert.equal(players.length,2,'Failed browser voice must retry through offline WAV playback');
  await context.speak('Cancelled browser voice');
  context.stop();
  await utterances[1].onerror();
  assert.equal(players.length,2,'Cancelled browser callback must not start fallback');
  console.log('PASS: split SSE, malformed/error/incomplete stream cleanup; TTS mute, playback cleanup and stale callbacks');
})().catch(error=>{console.error(error);process.exitCode=1;});
