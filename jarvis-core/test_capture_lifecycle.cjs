const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('ui/app.js', 'utf8');
const handlers = source.slice(source.indexOf('    function clearImage()'), source.indexOf('    document.getElementById("camera").addEventListener'));
const deferred = () => { let resolve; const promise = new Promise(r=>{resolve=r;});return {promise,resolve}; };
function setup(media, audit, playing) {
  let stopped=0,drawn=0;
  const requested=deferred();
  const stream={getTracks:()=>[{stop:()=>{stopped++;}}]};
  const context={navigator:{mediaDevices:{getDisplayMedia:()=>{requested.resolve();return media||Promise.resolve(stream);},getUserMedia:()=>{requested.resolve();return media||Promise.resolve(stream);}}},
    imagePreview:{style:{},removeAttribute(){}},captureStatus:{textContent:''},auditBrowserAction:()=>{if(audit){audit.entered.resolve();return audit.promise;}return Promise.resolve();},
    document:{createElement:tag=>tag==='video'?{play:()=>{if(playing){playing.entered.resolve();return playing.promise;}return Promise.resolve();},videoWidth:100,videoHeight:100}:{getContext:()=>({drawImage(){drawn++;}}),toDataURL:()=> 'data:image/jpeg;base64,TEST'}}};
  Object.assign(context,{safetyStopped:false,safetyEpoch:0,chatAbort:null,AbortController,deviceReady:async()=>true});vm.createContext(context);
  vm.runInContext('let pendingImage=null,imageCaptureVersion=0,imageCaptureStream=null;'+handlers+';this.capture=captureOnce;this.clear=clearImage;this.image=()=>pendingImage;',context);
  return {context,stream,requested:requested.promise,stopped:()=>stopped,drawn:()=>drawn};
}
(async()=>{
  for(const kind of ['camera','screen']) {
    const permission=deferred();
    const first=setup(permission.promise);
    const capturing=first.context.capture(kind);
    await first.requested;
    first.context.clear();
    permission.resolve(first.stream);
    await capturing;
    assert.equal(first.context.image(),null);
    assert.equal(first.drawn(),0,'Cancelled request must not take a frame');
    assert.equal(first.stopped(),1,'Late stream must be stopped');
    const audit=deferred();
    audit.entered=deferred();
    const second=setup(null,audit);
    const finishing=second.context.capture(kind);
    await audit.entered.promise;
    assert.equal(second.stopped(),1,'One-shot stream must stop before audit finishes');
    second.context.clear();
    audit.resolve();
    await finishing;
    assert.equal(second.context.image(),null,'Clear must prevent delayed attachment');
    assert.equal(second.context.captureStatus.textContent,'OFF');
    const playing=deferred();playing.entered=deferred();
    const third=setup(null,null,playing);
    const liveCapture=third.context.capture(kind);
    await playing.entered.promise;
    third.context.clear();
    assert.equal(third.stopped(),1,'Clear must immediately release an active capture');
    playing.resolve();
    await liveCapture;
    assert.equal(third.drawn(),0);
    assert.equal(third.context.image(),null);
    const success=setup();
    await success.context.capture(kind);
    assert.equal(success.drawn(),1,'Successful capture must take exactly one frame');
    assert.equal(success.stopped(),1);
    assert.equal(success.context.image(),'TEST');
  }
  console.log('PASS: camera and screen late permission cancellation, one-shot release, and stale frame isolation');
})().catch(error=>{console.error(error);process.exitCode=1;});
