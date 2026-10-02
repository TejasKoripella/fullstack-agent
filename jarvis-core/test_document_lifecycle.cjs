const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('ui/app.js', 'utf8');
const functions = source.slice(source.indexOf('    async function listDocuments('), source.indexOf('    function clearDocument('));
async function check(method, failure, change) {
  let resolve, reject, rendered = 0;
  const pending = new Promise((yes,no)=>{resolve=yes;reject=no;});
  const status={textContent:'current status'}, output={hidden:true,textContent:'current document'};
  const context={postApproved:()=>pending,renderDocuments:()=>{rendered++;},
    document:{getElementById:id=>id==='document-output'?output:status}};
  vm.createContext(context);
  vm.runInContext('let safetyStopped=false,safetyEpoch=1,conversationVersion=1,documentRequestVersion=0;'+functions+
    ';this.run=()=>'+method+'("Report");this.change=()=>{'+change+'};',context);
  const request=context.run();
  context.change();
  if(failure) reject(new Error('old failure'));
  else resolve({entries:[{name:'old file'}],content:'old private transcript'});
  await request;
  assert.equal(status.textContent,'current status');
  assert.equal(output.textContent,'current document');
  assert.equal(output.hidden,true);
  assert.equal(rendered,0);
}
(async()=>{
  for(const method of ['listDocuments','readDocument'])
    for(const failure of [false,true])
      for(const change of ['conversationVersion++;','safetyEpoch++;','safetyStopped=true;','documentRequestVersion++;'])
        await check(method,failure,change);
  console.log('PASS: stale document listings, contents and errors cannot overwrite chat, stop or newer requests');
})().catch(error=>{console.error(error);process.exitCode=1;});
