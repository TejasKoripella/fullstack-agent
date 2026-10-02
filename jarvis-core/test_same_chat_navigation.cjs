const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('ui/app.js', 'utf8');
const handler = source.slice(source.indexOf('    async function openConversation('), source.indexOf('    async function loadConversations('));
const views = [];
const forbidden = () => { throw new Error('Same-chat navigation must preserve drafts, approvals and in-flight workspace state'); };
const context = {sending:false, openingSide:false, activeSession:{id:17}, conversationVersion:4,
  showView:view=>views.push(view), apiJson:forbidden, cancelTargetPreviews:forbidden,
  endRecording:forbidden, stopSpeech:forbidden, clearImage:forbidden, clearDocument:forbidden};
vm.createContext(context);
vm.runInContext(handler + ';this.open = openConversation;', context);
(async () => {
  await context.open({id:17});
  assert.deepEqual(views, ['home']);
  assert.equal(context.conversationVersion,4);
  assert.equal(context.openingSide,false);
  await context.open({id:17},false);
  assert.deepEqual(views,['home'],'Background hydration must not change the selected view');
  for(const stopped of [false,true]) {
    let finish;
    const pending=new Promise(resolve=>{finish=resolve;});
    let view='control';
    const switching={sending:false,openingSide:false,activeSession:{id:17},conversationVersion:4,safetyStopped:false,
      messageInput:{value:'',disabled:false},sendButton:{disabled:false},conversation:{replaceChildren(){}},
      showView:next=>{view=next;},apiJson:()=>pending,cancelTargetPreviews(){},
      endRecording(){},stopSpeech(){},clearImage(){},clearDocument(){},
      updateChatHeader(){},updateConversationLayout(){},renderChatList(){},
      localStorage:{setItem(){}},addMessage(){}};
    vm.createContext(switching);
    vm.runInContext(handler+';this.open=openConversation;',switching);
    const load=switching.open({id:18});
    assert.equal(view,'home','Chat navigation happens at click time');
    assert.equal(switching.messageInput.disabled,true,'Cannot type into the wrong chat during loading');
    assert.equal(switching.sendButton.disabled,true,'Cannot send into the old workspace during loading');
    switching.showView('control');
    switching.safetyStopped=stopped;
    finish({kind:'side',messages:[]});
    await load;
    assert.equal(view,'control','Late chat history must not undo a later Settings click');
    assert.equal(switching.sendButton.disabled,stopped,'History completion cannot bypass Stop');
    assert.equal(switching.messageInput.disabled,false);
    assert.equal(switching.activeSession.id,18);
  }
  console.log('PASS: returning to the same chat preserves draft, approval and workspace state');
})().catch(error=>{console.error(error);process.exitCode=1;});
