const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('ui/app.js','utf8');
const handler = source.slice(source.indexOf('    async function requestTool('),source.indexOf('    async function streamReply('));
class Element {
  constructor(tag='div') { this.tag=tag;this.children=[];this.listeners={};this.textContent='';this.disabled=false; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children=children; }
  addEventListener(name,callback) { this.listeners[name]=callback; }
  querySelectorAll(selector) { return this.children.flatMap(child=>[...(selector==='button'&&child.tag==='button'?[child]:[]),...child.querySelectorAll(selector)]); }
}
async function check(choice) {
  const requests=[],status=new Element(),card=new Element(),meta=new Element(),activePreviews=new Map();
  card.querySelector=()=>meta;
  const fields=new Map();let state='idle';
  const context={console,conversation:new Element(),activeSession:{id:42},safetyStopped:false,safetyEpoch:4,
    document:{body:{dataset:{view:'home'}},getElementById:id=>{if(!fields.has(id))fields.set(id,new Element());return fields.get(id);},createElement:tag=>new Element(tag)},
    activePreviews,addMessage:()=>card,setAssistantState:value=>{state=value;return 1;},settleTool:()=>{},
    safeFetch:async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});
      assert.equal(activePreviews.size,choice==='Allow Once'?1:0);
      return {ok:true,json:async()=>choice==='Deny'?{cancelled:true}:{message:'The selected pane scrolled down.',outcome:'verified'}};}};
  vm.createContext(context);vm.runInContext('let conversationVersion=7;'+handler+';this.request=requestTool;',context);
  const proposal={status:'approval_required',persistent_eligible:false,safety_epoch:4,reference:'r',workspace_scope:'42:7',control_id:'c',control_label:'Playlist',action:'scroll_down'};
  await context.request('scroll_control','Spotify',status,context.conversation,proposal);
  const buttons=card.querySelectorAll('button');
  assert.deepEqual(buttons.map(button=>button.textContent),['Allow Once','Deny']);
  assert.equal(requests.length,0);assert.equal(state,'approval');
  await buttons.find(button=>button.textContent===choice).listeners.click();
  assert.equal(requests.length,1);
  assert.equal(requests[0].url,choice==='Deny'?'/tools/preview-cancel':'/tools/scroll-control');
  assert.equal(requests[0].body.reference,'r');assert.equal(requests[0].body.workspace_scope,'42:7');
  assert.equal(requests[0].body.decision,choice==='Deny'?'deny':'allow_once');
  assert.equal(activePreviews.size,0);assert.equal(card.querySelectorAll('button').length,0);
  assert.equal(status.textContent,choice==='Deny'?'Okay, I won’t scroll that pane.':'The selected pane scrolled down.');
}
(async()=>{await check('Allow Once');await check('Deny');console.log('PASS: model scroll proposals require fresh approval and reuse scoped execution/cancellation endpoints');})().catch(error=>{console.error(error);process.exitCode=1;});
