const fs = require('fs'), vm = require('vm'), path = require('path');
const POPUP = path.join(__dirname, '..', '..', 'ext', 'shared', 'popup.js');

function mkEl(id) {
  const el = {
    id, textContent: '', className: '', value: '', checked: false,
    dataset: {}, _classes: new Set(),
    classList: {
      add: c => el._classes.add(c),
      remove: c => el._classes.delete(c),
      toggle: (c, on) => { on ? el._classes.add(c) : el._classes.delete(c); },
      contains: c => el._classes.has(c),
    },
    addEventListener() {}, querySelector: sel => el._kids[sel] ||= mkEl(sel),
    _kids: {},
  };
  return el;
}

const els = {};
const STAGES = ['lookup','samples','bpm','render','print'];
const stageLis = STAGES.map(s => { const li = mkEl('li-'+s); li.dataset.stage = s; return li; });

const document = {
  getElementById: id => els[id] ||= mkEl(id),
  querySelectorAll: sel => sel === '#stages li' ? stageLis : [],
};

function makeExtApi() {
  return {
    storage: { local: { get: () => Promise.resolve({}), set() {} } },
    tabs: { query: () => Promise.resolve([{ url: 'https://discogs.com/release/123' }]), create: () => Promise.resolve() },
    runtime: { sendMessage: () => Promise.resolve() },
  };
}

// popup.js resolves `globalThis.browser ?? globalThis.chrome`. Run the whole
// suite under each namespace so the Chrome build is covered too, not just
// assumed to work.
const NAMESPACE = process.env.EXT_NAMESPACE || 'browser';

const ctx = {
  document, console,
  fetch: () => Promise.reject(new Error('no net')),
  setInterval: () => 0, setTimeout: () => 0, clearTimeout() {},
  AbortController: class { constructor(){ this.signal = null; } },
  AbortSignal: { timeout: () => null },
};
ctx[NAMESPACE] = makeExtApi();
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(POPUP, 'utf8'), ctx);

const status = els['status'];
const progress = els['progress'];

let failures = 0;
function expect(label, payload, wantText, wantCls, wantHidden) {
  ctx.renderProgress(payload);
  const got = [status.textContent, status.className, progress._classes.has('hidden')];
  const want = [wantText, wantCls, wantHidden];
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { failures++; console.log(`FAIL [${NAMESPACE}] ${label}\n  want ${JSON.stringify(want)}\n  got  ${JSON.stringify(got)}`); }
  else console.log(`ok   [${NAMESPACE}] ${label}`);
}

const now = Date.now()/1000;
const stages = o => Object.fromEntries(STAGES.map(s => [s, o[s] || {state:'pending'}]));

expect('idle shows nothing', { depth:0, queued:[], recent:[] }, '', '', true);
expect('queued job is visible', { depth:1, queued:[{id:1,release_id:'123',state:'queued',stages:stages({})}], recent:[], current:null }, 'Queued.', '', false);
expect('running wins over queue', { depth:3, queued:[{id:1,release_id:'1',state:'queued',stages:stages({})},{id:2,release_id:'2',state:'queued',stages:stages({})}], recent:[], current:{id:0,release_id:'9',state:'running',title:'A – B',stages:stages({lookup:{state:'done'},samples:{state:'progress',done:2,total:4}})} }, 'Downloading samples 2/4…', '', false);
expect('per-track counts shown', { depth:1, queued:[], recent:[], current:{id:1,release_id:'123',title:'Steve – Reconstructed',state:'running',stages:stages({lookup:{state:'done'},samples:{state:'done'},bpm:{state:'progress',done:3,total:4}})} }, 'Analysing BPM 3/4…', '', false);
expect('printing reported live', { depth:1, queued:[], recent:[], current:{id:1,release_id:'123',state:'running',stages:stages({lookup:{state:'done'},render:{state:'done'},print:{state:'progress',done:1,total:2}})} }, 'Printing 1/2…', '', false);
expect('done replaces Queued', { depth:0, queued:[], current:null, recent:[{id:1,release_id:'123',kind:'print',state:'done',finished:now,stages:stages({print:{state:'done'}})}] }, 'Printed.', 'ok', false);
expect('failure surfaces error', { depth:0, queued:[], current:null, recent:[{id:1,release_id:'123',kind:'print',state:'error',error:'Printer unreachable',finished:now,stages:stages({print:{state:'error'}})}] }, 'Printer unreachable', 'error', false);
expect('stale job clears panel', { depth:0, queued:[], current:null, recent:[{id:1,release_id:'123',kind:'print',state:'done',finished:now-5000,stages:stages({print:{state:'done'}})}] }, '', '', true);

process.exit(failures ? 1 : 0);
