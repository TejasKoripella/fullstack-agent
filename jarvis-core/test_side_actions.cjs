const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('ui/app.js','utf8');
const code=source.slice(source.indexOf('    document.getElementById("promote-side-chat").addEventListener('),source.indexOf('    function openSideDraft('));
async function check(action,failure){
  let finish,reject,opened=0,messages=0;
  const pending=new Promise((yes,no)=>{finish=yes;reject=no;});
  const handlers={};
  const chats=[{id:1},{id:2}];
  const context={document:{getElementById:id=>({addEventListener:(event,fn)=>handlers[id]=fn})},
    apiJson:()=>pending,closeSideActions(){},chatSessions:chats,renderChatList(){},
    openConversation:async()=>{opened++;},addMessage:()=>{messages++;},loadFacts(){}};
  vm.createContext(context);
  vm.runInContext('let sideSession={id:1},sending=false,safetyStopped=false,safetyEpoch=1,conversationVersion=1;'+code+
    ';this.switchChat=()=>{sideSession={id:2};conversationVersion++;};',context);
  const request=handlers[action]();
  context.switchChat();
  if(failure)reject(new Error('old error'));
  else finish(action==='promote-side-chat'?{id:100}:{saved_entries:1,saved_facts:0});
  await request;
  assert.equal(opened,0,'Old promotion must not replace the current workspace');
  assert.equal(messages,0,'Old receipt or error must not enter another chat');
  if(action==='promote-side-chat'&&!failure)assert.deepEqual(chats.map(item=>item.id),[2],'Only the promoted chat leaves the sidebar');
}
(async()=>{for(const action of ['promote-side-chat','commit-side-chat'])for(const failure of [false,true])await check(action,failure);
const loader=source.slice(source.indexOf('    async function loadConversations('),source.indexOf('    function requestChatDeletion('));
const button={disabled:false};
const context={sendButton:button,apiJson:async()=>({conversations:[]}),openConversation:async()=>{},chatSessions:[],renderChatList(){},addMessage(){}};
vm.createContext(context);
vm.runInContext('let safetyStopped=true,sending=false,sideSession=null;'+loader+';this.load=loadConversations;',context);
await context.load();
assert.equal(button.disabled,true,'Loading saved history must not enable sending while STOPPED');
console.log('PASS: Side actions retain their original chat; late receipts/errors do not enter another workspace');})().catch(error=>{console.error(error);process.exitCode=1;});
