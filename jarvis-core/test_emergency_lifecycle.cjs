const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('ui/app.js','utf8');
const cleanup = source.slice(source.indexOf('    function stopLocalActivity('),source.indexOf('    async function emergencyStop('));
const controls = source.slice(source.indexOf('    const stoppedActionControls ='),source.indexOf('    function stopLocalActivity('));
const fetchHandler = source.slice(source.indexOf('    async function safeFetch('),source.indexOf('    const stoppedActionControls ='));
const shortcut = source.slice(source.indexOf('    window.addEventListener("keydown", event => {'),source.indexOf('    window.addEventListener("focus", syncSafety);'));
let focus=true,listener,shortcutStops=0;
const calls=[];
const previewControls=[{disabled:false},{disabled:false}];
const appControls=[{disabled:false},{disabled:true}];
const approval={querySelector(){return {};},replaceChildren(){calls.push('approval');},textContent:''};
const completedApproval={querySelector(){return null;},replaceChildren(){throw new Error('Completed approvals must remain unchanged');},textContent:''};
const context={window:{fetch:async()=>{throw new Error('Network must not be used while stopped');},addEventListener:(name,fn)=>{listener=fn;}},
  document:{hasFocus:()=>focus,querySelectorAll:selector=>selector==='.workflow-actions'?[approval,completedApproval]:selector==='.target-preview button, .target-preview select'?previewControls:selector.startsWith('#open-app,')?appControls:[]},
  endRecording:send=>{assert.equal(send,false);calls.push('mic');},stopWake:()=>calls.push('wake'),
  stopSpeech:()=>calls.push('audio'),clearImage:()=>calls.push('capture'),clearDocument:()=>calls.push('document'),closeChatMenu(){},closeSideActions(){},
  cancelTargetPreviews:()=>calls.push('preview'),
  setAssistantState:state=>calls.push(state),sendButton:{},resumeButton:{},resourceButton:{},
  emergencyStop:source=>{assert.equal(source,'keyboard');shortcutStops++;},AbortController};
vm.createContext(context);
vm.runInContext('let safetyStopped=false,conversationVersion=4,chatAbort={abort:()=>{}};const requestControllers=new Set();'+controls+cleanup+fetchHandler+shortcut+';this.stop=stopLocalActivity;this.request=safeFetch;this.version=()=>conversationVersion;this.restoreControls=()=>setActionControlsStopped(false);',context);
(async()=>{
  context.stop();context.stop();
  assert.equal(context.version(),5,'Repeated stop must not revive or reassign the current turn');
  for(const name of ['mic','wake','audio','capture','preview','approval','stopped']) assert.ok(calls.includes(name));
  assert.equal(context.sendButton.disabled,true);
  assert.ok(previewControls.every(control=>control.disabled),'Stop disables target-preview controls');
  assert.ok(appControls.every(control=>control.disabled),'Stop visibly disables app actions');
  context.restoreControls();
  assert.equal(appControls[0].disabled,false,'Resume restores previously available controls');
  assert.equal(appControls[1].disabled,true,'Resume never enables an unavailable action');
  await assert.rejects(context.request('/tools/dispatch',{method:'POST'}),/stopped/);
  await assert.rejects(context.request('/voice/speak',{method:'POST'}),/stopped/);
  let prevented=0;
  focus=false;listener({ctrlKey:true,altKey:true,code:'KeyJ',preventDefault(){prevented++;}});
  assert.equal(shortcutStops,0,'Background shortcut must do nothing');
  focus=true;listener({ctrlKey:true,altKey:true,code:'KeyJ',preventDefault(){prevented++;}});
  assert.equal(shortcutStops,1);assert.equal(prevented,1);
  let finishHistory,historySignal;
  context.window.fetch=async(url,options)=>{historySignal=options.signal;return await new Promise(resolve=>{finishHistory=resolve;});};
  const history=context.request('/conversations');
  context.stop();
  assert.equal(historySignal.aborted,false,'Stopping must not abort saved history reads');
  finishHistory({status:200});
  assert.equal((await history).status,200);
  console.log('PASS: emergency device/audio/chat cleanup, cancelled approvals, stopped request gate, focused-only shortcut and repeated activation');
})().catch(error=>{console.error(error);process.exitCode=1;});
