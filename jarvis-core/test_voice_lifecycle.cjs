// Exercise the real recording handlers with delayed browser/model responses.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('ui/app.js', 'utf8');
const handlers = source.slice(source.indexOf('    async function beginRecording('), source.indexOf('    async function refreshMicrophones('));
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };
function setup(media, transcription) {
  let stopped = 0;
  const requested = deferred();
  const stream = {getTracks: () => [{stop: () => {stopped++;}}]};
  const recorders = [];
  class Recorder {
    constructor() { this.state = 'inactive'; this.mimeType = 'audio/webm'; recorders.push(this); }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; this.finished = this.onstop(); }
  }
  const context = {navigator: {mediaDevices: {getUserMedia: () => { requested.resolve(); return media || Promise.resolve(stream); }}}, window: {MediaRecorder:Recorder}, MediaRecorder:Recorder,
    microphoneSelect:{value:''}, messageInput:{value:'',focus(){}}, setMicState(){}, setAssistantState(){}, stopWake(){}, auditBrowserAction:async()=>{}, refreshMicrophones:async()=>{},
    safeFetch: () => transcription.promise, Blob, setTimeout:()=>1, clearTimeout(){} };
  Object.assign(context,{safetyStopped:false,safetyEpoch:0,chatAbort:null,AbortController,deviceReady:async()=>true});vm.createContext(context);
  vm.runInContext('let releaseRecordingStream=()=>{};let micRequested=false,recorder=null,wakeStream=null,recordingVersion=0,conversationVersion=0,micTimer=null,sendRecordedAudio=false;'+handlers+';this.begin=beginRecording;this.end=endRecording;this.switchChat=()=>{conversationVersion++;endRecording(false);};', context);
  return {context, stream, recorders, requested:requested.promise, stopped:()=>stopped};
}
(async()=>{
  const permission = deferred();
  const first = setup(permission.promise, deferred());
  const starting = first.context.begin();
  await first.requested;
  first.context.end(false);
  permission.resolve(first.stream);
  await starting;
  assert.equal(first.recorders.length,0,'Cancel during permission request must not begin recording');
  assert.equal(first.stopped(),1,'Acquired stream must be released');
  const transcription = deferred();
  const second = setup(null,transcription);
  await second.context.begin();
  const recorder = second.recorders[0];
  recorder.ondataavailable({data:new Blob(['audio'])});
  second.context.end(true);
  assert.equal(second.stopped(),1,'Microphone must be released before transcription finishes');
  second.context.switchChat();
  transcription.resolve({ok:true,json:async()=>({text:'Old chat transcript'})});
  await recorder.finished;
  assert.equal(second.context.messageInput.value,'','Stale transcription must not enter another chat');
  console.log('PASS: pending recording cancellation, microphone release, and stale transcript isolation');
})().catch(error=>{console.error(error);process.exitCode=1;});
