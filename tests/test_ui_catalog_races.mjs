// Exercise actual UI logic with controlled transport and rendering stubs.
// Server validation and numerical replay are covered by test_server.py.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';

const source = fs.readFileSync(new URL('../materialmind/web/app.js', import.meta.url), 'utf8')
  .replace("import { CrystalViewer, elementColor } from './crystal.js?v=specimen-workbench-3';", '');
const candidate = id => ({id, formula: 'NaCl', split: 'test', structure: {sites: []},
  prediction: {p_stable: .5, mean: .01, lower: -.02, upper: .03, acquisition: .2, relative_cost: 1}});
const catalog = (revision, history = [], ids = ['a', 'b', 'c']) => ({
  candidates: ids.map(candidate), metadata: {model_revision: revision}, history,
});
const revealed = ['a', 'b', 'c'].map(id => ({id, e_above_hull: .01, cost: 1}));
const response = (value, ok = true) => ({ok, status: ok ? 200 : 422, json: async () => value});
const settle = () => new Promise(resolve => setTimeout(resolve, 0));

class Element {
  constructor() { this.value = ''; this.checked = false; this.hidden = false; this.style = {}; this.handlers = {}; this.attributes = {}; this.children = []; }
  addEventListener(name, handler) { this.handlers[name] = handler; }
  setAttribute(name, value) { this.attributes[name] = value; }
  getAttribute(name) { return this.attributes[name]; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children.flatMap(child => child.isFragment ? child.children : [child]); }
  contains(target) { return this===target || this.children.some(child=>child.contains?.(target)); }
  closest(selector) { return selector==='.candidate'&&this.className?.includes('candidate')?this:null; }
  querySelector(selector) { if(selector==='.candidate.selected')return this.children.flatMap(x=>x.children).find(x=>x.className?.includes(' selected'))||null;return new Element(); }
  getBoundingClientRect() { return {width: 640, height: 320}; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  focus() { this.focused=true;if(this.ownerDocument)this.ownerDocument.activeElement=this; }
  scrollIntoView() { this.scrolled=true; }
}

function ui({preReady=true,deferBenchmark=false}={}) {
  const elements = new Map(), pending = [];
  const doc={activeElement:null};
  const make=()=>Object.assign(new Element(),{ownerDocument:doc});
  const get = id => { if (!elements.has(id)) elements.set(id, make()); return elements.get(id); };
  Object.assign(doc,{getElementById:get,createElement:make,createDocumentFragment:()=>Object.assign(make(),{isFragment:true}),body:make()});
  get('partition').value = 'all'; get('sort').value = 'acquisition';
  const context = vm.createContext({
    document: doc,
    CrystalViewer: class {setStructure() {}}, elementColor: () => '#fff',
    ResizeObserver: class {observe() {}}, TextEncoder, TextDecoder, URL, Blob, console, setTimeout, confirm: () => true,
    fetch: (path, options = {}) => {
      if (path === '/api/benchmark' && !deferBenchmark) return Promise.resolve(response({curves: []}));
      let resolve, reject;
      const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
      pending.push({path, options, resolve, reject});
      return promise;
    },
  });
  vm.runInContext(source, context);
  if(preReady)vm.runInContext('state.sessionReady=true;updateRevealState()',context);
  assert.equal(pending[0].path, '/api/catalog');
  return {get, pending, context, state: () => JSON.parse(vm.runInContext(
    'JSON.stringify({history:state.history,metadata:state.metadata,ids:state.candidates.map(c=>c.id)})', context))};
}

async function restore(u, reply = catalog(2, revealed)) {
  u.get('restore-input').value = '{"schema_version":3}';
  u.get('restore-confirm').checked = true;
  const done = u.get('restore-form').handlers.submit({preventDefault() {}});
  assert.equal(u.pending[1].path, '/api/session');
  u.pending[1].resolve(response(reply));
  await done;
}

test('late startup success preserves completed restore and its status', async () => {
  const u = ui();
  await restore(u);
  const message = u.get('session-status').textContent;
  u.pending[0].resolve(response(catalog(0)));
  await settle();
  assert.equal(u.state().history.length, 3);
  assert.equal(u.state().metadata.model_revision, 2);
  assert.equal(u.get('session-status').textContent, message);
});

test('late startup error cannot replace a successfully restored view', async () => {
  const u = ui();
  await restore(u);
  u.pending[0].reject(new Error('old startup request failed'));
  await settle();
  assert.equal(u.state().history.length, 3);
  assert.equal(u.get('global-error').hidden, true);
  assert.doesNotMatch(u.get('candidate-list').innerHTML || '', /unavailable/);
});

test('startup catalog cannot undo reset while its new catalog is loading', async () => {
  const u = ui();
  const done = u.get('reset-session').handlers.click();
  assert.equal(u.pending[1].path, '/api/reset');
  u.pending[1].resolve(response({reset: true}));
  await settle();
  assert.equal(u.pending[2].path, '/api/catalog');
  u.pending[0].resolve(response(catalog(2, revealed)));
  await settle();
  assert.equal(u.state().history.length, 0);
  u.pending[2].resolve(response(catalog(0)));
  await done;
  assert.equal(u.state().history.length, 0);
  assert.equal(u.state().metadata.model_revision, 0);
});

test('startup catalog cannot discard a successful imported structure', async () => {
  const u = ui();
  u.get('cif-input').value = 'mock CIF request';
  const done = u.get('import-form').handlers.submit({preventDefault() {}});
  assert.equal(u.pending[1].path, '/api/import');
  u.pending[1].resolve(response({candidate: {...candidate('imported'), split: 'import'}}));
  await settle();
  assert.equal(u.pending[2].path, '/api/catalog');
  const complete=catalog(0);
  complete.candidates.push({...candidate('imported'), split: 'import'});
  u.pending[2].resolve(response(complete));
  await done;
  u.pending[0].resolve(response(catalog(0)));
  await settle();
  assert.deepEqual(u.state().ids, ['a', 'b', 'c', 'imported']);
});

test('post-import refresh failure preserves previous catalog and input, and retry recovers', async () => {
  const u=ui();
  u.pending[0].resolve(response(catalog(0)));
  await settle();
  u.get('cif-input').value='mock CIF request';
  const first=u.get('import-form').handlers.submit({preventDefault() {}});
  const imported={candidate: {...candidate('imported'), split: 'import'}};
  u.pending[1].resolve(response(imported));
  await settle();
  u.pending[2].reject(new Error('refresh connection lost'));
  await first;
  assert.deepEqual(u.state().ids, ['a','b','c']);
  assert.equal(u.get('cif-input').value,'mock CIF request');
  assert.match(u.get('import-error').textContent,/was imported.*could not be refreshed/);
  assert.equal(u.get('export-session').disabled,true);
  u.get('import-close').handlers.click();
  u.get('catalog-retry').handlers.click();
  assert.equal(u.pending[3].path,'/api/catalog');
  const complete=catalog(1,revealed);
  complete.candidates.push(imported.candidate);
  u.pending[3].resolve(response(complete));
  await settle();
  assert.deepEqual(u.state().ids,['a','b','c','imported']);
  assert.equal(u.state().history.length,3);
  assert.equal(u.state().metadata.model_revision,1);
  assert.equal(u.get('cif-input').value,'mock CIF request');
  assert.equal(u.get('export-session').disabled,false);
});

test('startup catalog cannot undo a completed reference reveal', async () => {
  const u = ui();
  vm.runInContext('select(' + JSON.stringify(candidate('a')) + ')', u.context);
  const done = u.get('reveal').handlers.click();
  assert.equal(u.pending[1].path, '/api/reveal');
  u.pending[1].resolve(response({history: revealed, results: revealed, model_updated: false}));
  await done;
  u.pending[0].resolve(response(catalog(0)));
  await settle();
  assert.equal(u.state().history.length, 3);
});

test('failed mutation retains input and permits original startup to complete', async () => {
  const u = ui();
  u.get('restore-input').value = '{"schema_version":3}';
  u.get('restore-confirm').checked = true;
  const done = u.get('restore-form').handlers.submit({preventDefault() {}});
  u.pending[1].resolve(response({detail: 'incompatible record'}, false));
  await done;
  u.pending[0].resolve(response(catalog(0)));
  await settle();
  assert.equal(u.state().ids.length, 3);
  assert.equal(u.get('restore-input').value, '{"schema_version":3}');
  assert.match(u.get('restore-error').textContent, /incompatible/);
});

test('failed initial catalog offers a retry and keeps the error until it succeeds', async () => {
  const u = ui();
  u.pending[0].reject(new Error('server offline'));
  await settle();
  assert.equal(u.get('catalog-retry').hidden, false);
  assert.match(u.get('global-error').textContent, /server offline/);
  u.get('catalog-retry').handlers.click();
  assert.equal(u.pending[1].path, '/api/catalog');
  u.pending[1].resolve(response(catalog(0)));
  await settle();
  assert.equal(u.get('catalog-retry').hidden, true);
  assert.equal(u.get('global-error').hidden, true);
  assert.deepEqual(u.state().ids, ['a', 'b', 'c']);
});

test('benchmark omits missing values and does not invent an origin', () => {
  const u = ui();
  const got = vm.runInContext(`normalizeCurves({curves:[{method:'random',points:[{budget:2,mean:3},{budget:4,mean:null},{budget:6,mean:5}]}]})`, u.context);
  assert.equal(got[0].points.length, 2);
  assert.equal(got[0].points[0].budget, 2);
  vm.runInContext(`state.curves=normalizeCurves({curves:[{method:'random',points:[{budget:2,mean:3},{budget:6,mean:5}]}]}); document.getElementById('budget').value=1; renderChart()`, u.context);
  assert.match(u.get('budget-summary').textContent, /not available/);
  assert.doesNotMatch(u.get('discovery-chart').innerHTML, /M40,170 L/);
});

test('missing reference energy is not displayed as stable', () => {
  const u = ui();
  vm.runInContext(`state.history=[{id:'a',stable:true}]; state.selected={id:'a',split:'test'}; renderHistory(); updateRevealState()`, u.context);
  assert.match(u.get('history').innerHTML, /REFERENCE UNAVAILABLE/);
  assert.doesNotMatch(u.get('history').innerHTML, /DFT STABLE/);
  assert.match(u.get('reveal-result').textContent, /no available energy/);
  assert.equal(u.get('log-stable').textContent, 0);
});

test('reference comparison uses the archived selection rather than the current model', () => {
  const u = ui();
  const record = JSON.parse(fs.readFileSync(new URL('../docs/presentation/reveal.json', import.meta.url), 'utf8')).history[0];
  vm.runInContext(`state.history=[${JSON.stringify(record)}]; state.selected={id:'wbm-5-6788',split:'test',prediction:{lower:-2,upper:-1}}; updateRevealState()`, u.context);
  const result = u.get('reveal-result').textContent;
  assert.match(result, /WBM DFT: -1\.951794 eV\/atom/);
  assert.match(result, /\[-2\.284320, -2\.112779\]/);
  assert.match(result, /0\.160985 eV\/atom above the interval/);
  assert.match(result, /Stable by the fixed hull criterion/);
});

test('committed reveal with failed catalog refresh says what succeeded', async () => {
  const u = ui();
  u.pending[0].resolve(response(catalog(0))); await settle();
  const done = u.get('reveal').handlers.click();
  u.pending[1].resolve(response({results:[revealed[0]],model_updated:true}));
  await settle();
  u.pending[2].reject(new Error('offline'));
  await done;
  assert.match(u.get('global-error').textContent, /Reference revealed/);
  assert.match(u.get('global-error').textContent, /Retry loading/);
  assert.equal(u.get('export-session').disabled, true);
  assert.equal(u.state().history.length, 1);
});

test('unreadable CIF file preserves text and explains retry', async () => {
  const u = ui();
  u.get('cif-input').value = 'existing text';
  await u.get('cif-file').handlers.change({target:{files:[{size:20,text:async()=>{throw Error('read failed')}}]}});
  assert.equal(u.get('cif-input').value, 'existing text');
  assert.equal(u.get('import-error').hidden, false);
  assert.match(u.get('import-error').textContent, /choose the file again/);
});


test('canceling reset keeps the current session and makes no request', async () => {
  const u = ui();
  u.pending[0].resolve(response(catalog(1, revealed))); await settle();
  u.context.confirm = () => false;
  await u.get('reset-session').handlers.click();
  assert.equal(u.pending.length, 1);
  assert.equal(u.state().history.length, 3);
});

test('initial catalog must establish session before restore or import', async () => {
  const u=ui({preReady:false});
  assert.equal(u.get('restore-open').disabled,true);
  assert.equal(u.get('import-open').disabled,true);
  u.get('restore-input').value='{"schema_version":3}';u.get('restore-confirm').checked=true;
  await u.get('restore-form').handlers.submit({preventDefault(){}});
  assert.equal(u.pending.length,1);
  u.pending[0].resolve(response(catalog(0)));await settle();
  assert.equal(u.get('restore-open').disabled,false);
});

test('late benchmark honors the selected cost axis', async () => {
  const u=ui({deferBenchmark:true});
  u.pending[0].resolve(response(catalog(0)));await settle();
  assert.equal(u.pending[1].path,'/api/benchmark');
  u.get('cost-axis').handlers.click();
  u.pending[1].resolve(response({curves:[{method:'random',points:[{budget:1,mean:.2}]}],cost_curves:[{method:'random',points:[{budget:1,mean:.1}]}]}));
  await settle();u.get('budget').value=1;vm.runInContext('renderChart()',u.context);
  assert.match(u.get('budget-summary').textContent,/Random: 0.1/);
  assert.match(u.get('discovery-chart').innerHTML,/normalized proxy cost/);
  u.get('count-axis').handlers.click();
  assert.match(u.get('budget-summary').textContent,/Random: 0.2/);
  assert.match(u.get('discovery-chart').innerHTML,/reference evaluations/);
});

test('reveal refresh keeps the candidate chosen while the request was pending', async () => {
  const u=ui();u.pending[0].resolve(response(catalog(0)));await settle();
  vm.runInContext(`select(${JSON.stringify(candidate('a'))})`,u.context);
  const done=u.get('reveal').handlers.click();
  u.pending[1].resolve(response({results:[revealed[0]],model_updated:true}));await settle();
  vm.runInContext(`select(${JSON.stringify(candidate('b'))})`,u.context);
  u.pending[2].resolve(response(catalog(1,[revealed[0]])));await done;
  assert.equal(vm.runInContext('state.selected.id',u.context),'b');
  assert.equal(u.state().history[0].id,'a');
});

test('reset refresh failure marks stale view and blocks export until catalog retry', async () => {
  const u=ui();u.pending[0].resolve(response(catalog(1,revealed)));await settle();
  const done=u.get('reset-session').handlers.click();u.pending[1].resolve(response({reset:true}));await settle();
  u.pending[2].reject(new Error('offline'));await done;
  assert.match(u.get('global-error').textContent,/Session reset.*out of date/);
  assert.match(u.get('session-status').textContent,/stale/);
  assert.equal(u.get('log-evaluations').textContent,0);
  assert.equal(u.get('export-session').disabled,true);
  assert.equal(u.get('download-cif').disabled,true);
  u.get('catalog-retry').handlers.click();assert.equal(u.pending[3].path,'/api/catalog');
  u.pending[3].resolve(response(catalog(0)));await settle();
  assert.equal(u.get('export-session').disabled,false);
  assert.equal(u.state().history.length,0);
});

test('slow CIF read cannot overwrite newer text, file, or closed dialog', async () => {
  const u=ui();let resolveFirst;const first={size:1,text:()=>new Promise(r=>resolveFirst=r)};
  const input=u.get('cif-file');input.files=[first];input.value='first';
  const old=input.handlers.change({target:input});u.get('cif-input').value='new edits';
  resolveFirst('old file');await old;assert.equal(u.get('cif-input').value,'new edits');
  let resolveSecond;const second={size:1,text:()=>new Promise(r=>resolveSecond=r)};
  input.files=[second];const later=input.handlers.change({target:input});
  const third={size:1,text:async()=> 'new file'};input.files=[third];await input.handlers.change({target:input});
  resolveSecond('stale file');await later;assert.equal(u.get('cif-input').value,'new file');
  let resolveClosed;input.files=[{size:1,text:()=>new Promise(r=>resolveClosed=r)}];
  const closing=input.handlers.change({target:input});u.get('import-close').handlers.click();resolveClosed('after close');await closing;
  assert.equal(u.get('cif-input').value,'new file');
});


test('saved benchmark honors count selected during delayed response', async () => {
  const u=ui({deferBenchmark:true});u.pending[0].resolve(response(catalog(0)));await settle();
  u.get('cost-axis').handlers.click();u.get('count-axis').handlers.click();
  const data=JSON.parse(fs.readFileSync(new URL('../materialmind/artifacts/summary.json',import.meta.url),'utf8'));
  u.pending[1].resolve(response(data));await settle();u.get('budget').value=1;vm.runInContext('renderChart()',u.context);
  assert.match(u.get('budget-summary').textContent,/Random: 0.2/);
  u.get('cost-axis').handlers.click();
  assert.match(u.get('budget-summary').textContent,/Random: 0.1/);
});


test('unconfirmed reset prevents stale export until catalog recovery', async () => {
  const u=ui();u.pending[0].resolve(response(catalog(1,revealed)));await settle();
  const done=u.get('reset-session').handlers.click();u.pending[1].reject(new Error('connection lost'));await done;
  assert.match(u.get('session-status').textContent,/unconfirmed/);
  assert.equal(u.get('export-session').disabled,true);
  u.get('catalog-retry').handlers.click();u.pending[2].resolve(response(catalog(0)));await settle();
  assert.equal(u.get('export-session').disabled,false);
  assert.equal(u.state().history.length,0);
});

test('in-flight CIF import freezes controls and keeps a newer draft if changed', async () => {
  const u=ui();u.pending[0].resolve(response(catalog(0)));await settle();
  u.get('cif-input').value='draft A';u.get('import-dialog').showModal();
  const done=u.get('import-form').handlers.submit({preventDefault(){}});
  assert.equal(u.get('cif-input').disabled,true);assert.equal(u.get('cif-file').disabled,true);assert.equal(u.get('import-close').disabled,true);
  u.get('import-close').handlers.click();assert.equal(u.get('import-dialog').open,true);
  let prevented=false;u.get('import-dialog').handlers.cancel({preventDefault(){prevented=true;}});assert.equal(prevented,true);
  u.get('cif-input').value='draft B';
  const imported={candidate:{...candidate('imported'),split:'import'}};
  u.pending[1].resolve(response(imported));await settle();
  const updated=catalog(1);updated.candidates.push(imported.candidate);u.pending[2].resolve(response(updated));await done;
  assert.equal(u.get('cif-input').value,'draft B');assert.equal(u.get('import-dialog').open,true);
  assert.match(u.get('import-error').textContent,/Newer CIF text was kept/);
  assert.equal(u.get('cif-input').disabled,false);
});

test('lost restore response gates export until authoritative catalog recovery', async () => {
  const u=ui();u.pending[0].resolve(response(catalog(0)));await settle();
  u.get('restore-input').value='{"schema_version":3}';u.get('restore-confirm').checked=true;
  const done=u.get('restore-form').handlers.submit({preventDefault(){}});
  u.pending[1].reject(new Error('connection lost'));await done;
  assert.equal(u.get('export-session').disabled,true);assert.equal(u.get('restore-submit').disabled,true);assert.match(u.get('restore-error').textContent,/Close this dialog/);
  assert.equal(u.get('restore-input').value,'{"schema_version":3}');
  u.get('restore-close').handlers.click();u.get('catalog-retry').handlers.click();
  u.pending[2].resolve(response(catalog(1,revealed)));await settle();
  assert.equal(u.get('export-session').disabled,false);assert.equal(u.state().history.length,3);
});

test('rejected restore remains editable without requiring recovery', async () => {
  const u=ui();u.pending[0].resolve(response(catalog(0)));await settle();
  u.get('restore-input').value='{"schema_version":3}';u.get('restore-confirm').checked=true;
  const done=u.get('restore-form').handlers.submit({preventDefault(){}});
  u.pending[1].resolve(response({detail:'invalid record'},false));await done;
  assert.equal(u.get('export-session').disabled,false);assert.match(u.get('restore-error').textContent,/correct it/);
});

test('unknown import outcome requires catalog recovery without resubmission', async () => {
  const u=ui();u.pending[0].resolve(response(catalog(0)));await settle();
  u.get('cif-input').value='draft A';const done=u.get('import-form').handlers.submit({preventDefault(){}});
  u.pending[1].reject(new Error('connection lost'));await done;
  assert.equal(u.get('export-session').disabled,true);assert.equal(u.get('import-submit').disabled,true);assert.equal(u.get('cif-input').value,'draft A');
  assert.match(u.get('import-error').textContent,/outcome|confirm/i);
  u.get('import-close').handlers.click();u.get('catalog-retry').handlers.click();
  assert.equal(u.pending[2].path,'/api/catalog');u.pending[2].resolve(response(catalog(0)));await settle();
  assert.equal(u.get('export-session').disabled,false);assert.equal(u.get('cif-input').value,'draft A');
});

test('compact picker retains selected crystal and filters through review and reopen', async () => {
  const u=ui();u.pending[0].resolve(response(catalog(0)));await settle();
  const crystal={...candidate('b'),formula:'ErI4'};
  vm.runInContext(`select(${JSON.stringify(crystal)})`,u.context);
  assert.equal(u.get('picker-formula').textContent,'ErI4');
  assert.equal(u.get('picker-id').textContent,'b');
  assert.match(u.get('analysis-selection').textContent,/ErI4.*b/);
  u.get('search').value='NaCl';u.get('picker-toggle').focus();u.get('picker-toggle').handlers.click();
  assert.equal(u.get('picker-toggle').attributes['aria-expanded'],'true');
  assert.equal(u.context.document.activeElement,u.get('picker-toggle'));
  assert.equal(u.get('candidate-list').querySelector('.candidate.selected').scrolled,true);
  assert.equal(u.get('picker-review').textContent,'Review ErI4');
  u.get('picker-review').handlers.click();
  assert.equal(u.get('picker-toggle').attributes['aria-expanded'],'false');
  assert.equal(u.get('analysis-heading').focused,true);
  assert.equal(u.get('search').value,'NaCl');
  u.get('picker-toggle').handlers.click();
  assert.equal(u.get('picker-toggle').attributes['aria-expanded'],'true');
  assert.equal(u.get('search').value,'NaCl');
});

test('candidate list identifies score and stability and emphasizes the active score order', async () => {
  const u=ui();u.pending[0].resolve(response(catalog(0)));await settle();
  let first=u.get('candidate-list').children[0].children[0];
  assert.match(first.innerHTML,/candidate-measures score-first/);
  assert.match(first.innerHTML,/Stability/);assert.match(first.innerHTML,/Score/);
  u.get('sort').value='formula';u.get('sort').handlers.change();
  first=u.get('candidate-list').children[0].children[0];
  assert.doesNotMatch(first.innerHTML,/candidate-measures score-first/);
});

test('rerender preserves the focused candidate without stealing search focus', async () => {
  const u=ui();u.pending[0].resolve(response(catalog(0)));await settle();
  const list=u.get('candidate-list');let b=list.children.flatMap(x=>x.children).find(x=>x.getAttribute('data-candidate-id')==='b');
  b.focus();list.scrollTop=71;
  vm.runInContext('renderList()',u.context);
  const replacement=list.children.flatMap(x=>x.children).find(x=>x.getAttribute('data-candidate-id')==='b');
  assert.notEqual(replacement,b);assert.equal(u.context.document.activeElement,replacement);
  assert.equal(list.scrollTop,71);assert.equal(replacement.scrolled,true);
  u.get('search').focus();vm.runInContext('renderList()',u.context);
  assert.equal(u.context.document.activeElement,u.get('search'));
});

test('reveal refresh retains focus on newer selected candidate', async () => {
  const u=ui();u.pending[0].resolve(response(catalog(0)));await settle();
  vm.runInContext(`select(${JSON.stringify(candidate('a'))})`,u.context);
  const done=u.get('reveal').handlers.click();u.pending[1].resolve(response({results:[revealed[0]],model_updated:true}));await settle();
  const b=u.get('candidate-list').children.flatMap(x=>x.children).find(x=>x.getAttribute('data-candidate-id')==='b');
  b.focus();b.handlers.click();u.pending[2].resolve(response(catalog(1,[revealed[0]])));await done;
  assert.equal(vm.runInContext('state.selected.id',u.context),'b');
  assert.equal(u.context.document.activeElement.getAttribute('data-candidate-id'),'b');
});


test('replay submits unchanged selected file bytes despite textarea newline normalization', async () => {
  const u=ui();u.pending[0].resolve(response(catalog(0)));await settle();
  const input=u.get('restore-input');let value='';
  Object.defineProperty(input,'value',{get:()=>value,set:next=>{value=String(next).replace(/\r\n?/g,'\n');}});
  const raw=new TextEncoder().encode('\uFEFF{\r\n  "schema_version":3\r\n}');
  const file={size:raw.length,name:'original.json',arrayBuffer:async()=>raw.buffer};
  const picker=u.get('restore-file');picker.files=[file];
  await picker.handlers.change({target:picker});
  assert.ok(input.value.includes('\n')&&!input.value.includes('\r'));
  u.get('restore-confirm').checked=true;
  const done=u.get('restore-form').handlers.submit({preventDefault(){},submitter:{id:'replay-submit'}});
  assert.deepEqual(Buffer.from(u.pending[1].options.body),Buffer.from(raw));
  u.pending[1].resolve(response(catalog(0)));await done;
});

test('editing a selected file submits the edited input rather than its original bytes', async () => {
  const u=ui();u.pending[0].resolve(response(catalog(0)));await settle();
  const raw=new TextEncoder().encode('{"schema_version":2}');
  const file={size:raw.length,name:'old.json',arrayBuffer:async()=>raw.buffer};
  const picker=u.get('restore-file');picker.files=[file];await picker.handlers.change({target:picker});
  const edited='{"schema_version":3}';u.get('restore-input').value=edited;
  u.get('restore-input').handlers.input();u.get('restore-confirm').checked=true;
  const done=u.get('restore-form').handlers.submit({preventDefault(){},submitter:{id:'replay-submit'}});
  assert.equal(u.pending[1].options.body,edited);
  u.pending[1].resolve(response(catalog(0)));await done;
});

test('confirmed reset clears replay origin even if subsequent catalog refresh fails', async () => {
  const u=ui();const initial=catalog(1,revealed.slice(0,1));
  initial.metadata.replay_origin={kind:'replayed_as_new'};
  u.pending[0].resolve(response(initial));await settle();
  assert.equal(u.get('replay-origin').hidden,false);
  const done=u.get('reset-session').handlers.click();
  u.pending[1].resolve(response({reset:true}));await settle();
  assert.equal(u.get('replay-origin').hidden,true);
  u.pending[2].reject(new Error('catalog unavailable'));await done;
  assert.equal(u.get('replay-origin').hidden,true);
  assert.match(u.get('session-status').textContent,/stale/);
});

const batchPreview=()=>({requested_count:3,snapshot:'a'.repeat(64),model_revision:0,recommendations:['a','b','c'].map((id,i)=>({id,formula:'NaCl',batch_position:i+1,stable_probability:.5,acquisition:.2,novelty:.3,relative_cost:1}))});
async function readyBatch(){const u=ui();u.pending[0].resolve(response(catalog(0)));await settle();u.get('batch-count').value='3';u.get('batch-open').handlers.click();return u;}
test('cancelled batch preview suppresses late response and permits a new preview',async()=>{
 const u=await readyBatch();const first=u.get('batch-preview').handlers.click();
 assert.equal(u.pending[1].path,'/api/recommendations?count=3');
 await u.get('batch-preview').handlers.click();assert.equal(u.pending.length,2);
 u.get('batch-close').handlers.click();u.pending[1].resolve(response(batchPreview()));await first;
 assert.equal(u.get('batch-list').children.length,0);assert.equal(u.get('batch-reveal').disabled,true);
 u.get('batch-open').handlers.click();const second=u.get('batch-preview').handlers.click();u.pending[2].resolve(response(batchPreview()));await second;
 assert.equal(u.get('batch-list').children.length,3);assert.equal(u.get('batch-reveal').disabled,false);
});
test('batch commit submits only snapshot/count once and recovers an uncertain outcome',async()=>{
 const u=await readyBatch();const preview=u.get('batch-preview').handlers.click();u.pending[1].resolve(response(batchPreview()));await preview;
 u.get('batch-reveal').handlers.click();assert.equal(u.pending[2].path,'/api/recommendations/reveal');
 assert.deepEqual(JSON.parse(u.pending[2].options.body),{snapshot:'a'.repeat(64),count:3});
 u.get('batch-reveal').handlers.click();assert.equal(u.pending.length,3);
 assert.equal(u.get('reset-session').disabled,true);assert.equal(u.get('batch-close').disabled,true);
 u.pending[2].reject(new Error('response lost'));await settle();
 assert.equal(u.get('batch-dialog').open,false);assert.equal(u.get('export-session').disabled,true);
 assert.equal(u.get('catalog-retry').hidden,false);
 u.get('catalog-retry').handlers.click();u.pending[3].resolve(response(catalog(1,revealed)));await settle();
 assert.equal(u.state().history.length,3);assert.equal(u.get('export-session').disabled,false);
});
test('batch read failure is retryable without making the session stale',async()=>{
 const u=await readyBatch();const request=u.get('batch-preview').handlers.click();u.pending[1].reject(new Error('offline'));await request;
 assert.match(u.get('batch-error').textContent,/No|Cannot/);assert.equal(u.get('export-session').disabled,false);
 assert.equal(u.get('batch-reveal').disabled,true);assert.equal(u.get('batch-preview').disabled,false);
});
