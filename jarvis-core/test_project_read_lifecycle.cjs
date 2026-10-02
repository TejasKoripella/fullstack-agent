const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('ui/app.js','utf8');
const handler = source.slice(source.indexOf('    document.getElementById("read-form").addEventListener'),source.indexOf('    async function loadApps('));
async function check(change, failure) {
  let resolve, reject, calls=0;
  const pending = new Promise((yes,no)=>{resolve=yes;reject=no;});
  const nodes={};
  const get=id=>nodes[id]||(nodes[id]={value:'README.md',textContent:'current',hidden:true,addEventListener(event,fn){this[event]=fn;}});
  const context={document:{getElementById:get},safeFetch:()=>{calls++;return pending;}};
  vm.createContext(context);
  vm.runInContext('let safetyStopped=false,safetyEpoch=1,conversationVersion=1,projectReadVersion=0,lastReadProjectPath=null;'+handler+';this.change=()=>{'+change+'};',context);
  const request = get('read-form').submit({preventDefault(){}});
  context.change();
  if(failure) reject(new Error('old error'));
  else resolve({ok:true,json:async()=>({content:'old source'})});
  await request;
  assert.equal(get('read-output').textContent,'current');
  assert.equal(get('read-status').textContent,'current');
  assert.equal(get('use-project-file').hidden,true);
  assert.equal(calls,1);
}
(async()=>{
  for(const change of ['safetyStopped=true;','safetyEpoch++;','conversationVersion++;','projectReadVersion++;'])
    for(const failure of [true,false]) await check(change,failure);
  console.log('PASS: stale project text and read errors cannot cross chat, Stop or newer request boundaries');
})().catch(error=>{console.error(error);process.exitCode=1;});
