const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('ui/app.js','utf8');
async function check(name,stale,failure){
  const start=source.indexOf('    async function '+name+'(');
  const end=source.indexOf('    document.getElementById(',start);
  const code=source.slice(start,end);
  let resolve,reject;
  const pending=new Promise((yes,no)=>{resolve=yes;reject=no;});
  const status={textContent:'current status'};
  const context={document:{getElementById:()=>status},apiJson:()=>pending,safeFetch:()=>pending};
  vm.createContext(context);
  vm.runInContext('let safetyStopped=false,safetyEpoch=1,spotifyStatusVersion=0,bluetoothStatusVersion=0;'+code+
    ';this.run='+name+';this.change=()=>{'+stale+'};',context);
  const request=context.run();
  context.change();
  if(failure)reject(new Error('old failure'));
  else resolve(name==='checkSpotifyStatus'?{available:true,playing:true}:{ok:true,json:async()=>({radio_available:true})});
  await request;
  assert.equal(status.textContent,'current status',name+' must discard stale responses');
}
(async()=>{
  for(const name of ['checkSpotifyStatus','checkBluetooth'])
    for(const failure of [false,true])
      for(const stale of ['safetyStopped=true;','safetyEpoch++;',name==='checkSpotifyStatus'?'spotifyStatusVersion++;':'bluetoothStatusVersion++;'])
        await check(name,stale,failure);
  console.log('PASS: stale Spotify/Bluetooth status success and failure cannot replace stopped or newer state');
})().catch(error=>{console.error(error);process.exitCode=1;});
