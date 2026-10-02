const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('ui/app.js', 'utf8');
const handler = source.slice(source.indexOf('    function setAssistantState('), source.indexOf('    function settleTool('));
let pending = true, label;
const context = {
  safetyStopped: false,
  conversation: { querySelector: () => pending ? {} : null },
  document: { body: { dataset: {} }, getElementById: () => ({}) },
  window: { dispatchEvent() {} }, Event: function () {}, setTimeout() {},
  stateLabel: { setAttribute: (_, value) => label = value },
  stateLabels: { idle: 'READY', muted: 'MUTED', approval: 'AWAITING APPROVAL', thinking: 'THINKING', stopped: 'STOPPED' }
};
vm.createContext(context);
vm.runInContext('let assistantStateVersion=0;' + handler + ';this.setState=setAssistantState;', context);
const version = context.setState('idle');
assert.equal(label, 'AWAITING APPROVAL');
assert.equal(context.setState('muted'), version, 'Idle updates must not restart pending approval animation');
context.setState('thinking');
assert.equal(label, 'THINKING', 'An active generation remains visible while another approval waits');
pending = false;
context.setState('muted');
assert.equal(label, 'MUTED', 'Resolved or removed cards cannot keep approval state alive');
pending = true;
context.setState('idle', true);
assert.equal(label, 'READY', 'Developer preview must remain visual only');
context.safetyStopped = true;
context.setState('approval', true);
assert.equal(label, 'STOPPED', 'No pending card or preview can override Emergency Stop');
console.log('PASS: pending approval state, stable animation, active generation priority, card removal and Stop precedence');
