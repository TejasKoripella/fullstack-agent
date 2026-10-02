const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('ui/app.js', 'utf8');
const loader = source.slice(source.indexOf('    async function loadResources('), source.indexOf('    document.getElementById("find-documents-form").addEventListener('));
async function check(stale) {
  let finish;
  const result = new Promise(resolve => {finish = resolve;});
  const select = {options:[],replaceChildren(){this.options=[];},append(option){this.options.push(option);}};
  const button = {},status = {};
  const context = {resourceSelect:select,resourceButton:button,apiJson:()=>result,
    document:{getElementById:()=>status,createElement:()=>({})}};
  vm.createContext(context);
  vm.runInContext('let safetyStopped=false,safetyEpoch=1;'+loader+';this.load=loadResources;this.changeEpoch=()=>{safetyEpoch++;};',context);
  const request = context.load();
  if (stale) {
    context.changeEpoch();
    select.options=[{value:'new state'}];
  }
  finish({resources:[{name:'Missing',available:false},{name:'Jarvis project',available:true}]});
  await request;
  if (stale) assert.equal(select.options[0].value,'new state','Old safety epoch must not replace the current choices');
  else {
    assert.equal(select.value,'Jarvis project');
    assert.equal(select.options[0].disabled,true);
    assert.equal(button.disabled,false);
  }
}
(async()=>{await check(false);await check(true);console.log('PASS: unavailable resources disabled; old safety epochs cannot replace saved choices');})().catch(error=>{console.error(error);process.exitCode=1;});
