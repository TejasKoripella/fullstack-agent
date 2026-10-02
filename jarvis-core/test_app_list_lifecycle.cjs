const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('ui/app.js','utf8');
const loader=source.slice(source.indexOf('    async function loadApps('),source.indexOf('    async function openAppByName('));
async function check(stale,failure){
  let finish,fail;
  const pending=new Promise((resolve,reject)=>{finish=resolve;fail=reject;});
  const select={value:'Spotify',options:[{value:'current'}],disabled:true,replaceChildren(){throw Error('Stale result changed apps');}};
  const button={disabled:true},close={disabled:true},status={textContent:'STOPPED'};
  const context={safeFetch:()=>pending,document:{getElementById:id=>({'app-select':select,'open-app':button,'close-app':close,'app-status':status})[id]}};
  vm.createContext(context);
  vm.runInContext('let safetyStopped=false,safetyEpoch=1,appListVersion=0;'+loader+';this.load=loadApps;this.change=()=>{'+stale+'};',context);
  const request=context.load();
  context.change();
  if(failure) fail(Error('Old app list failed'));
  else finish({ok:true,json:async()=>({apps:['Spotify'],packaged_apps:[],closable:[]})});
  await request;
  assert.equal(select.disabled,true);assert.equal(button.disabled,true);assert.equal(close.disabled,true);
  assert.equal(status.textContent,'STOPPED','Late app load must not overwrite current safety state');
}
(async()=>{
  for(const stale of ['safetyStopped=true;','safetyEpoch++;','appListVersion++;'])
    for(const failure of [false,true]) await check(stale,failure);
  console.log('PASS: late app-list success/failure cannot re-enable stopped or newer app controls');
})().catch(error=>{console.error(error);process.exitCode=1;});
