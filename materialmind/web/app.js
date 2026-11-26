import { CrystalViewer, elementColor } from './crystal.js?v=specimen-workbench-3';

const $=id=>document.getElementById(id);
const state={candidates:[],selected:null,history:[],metadata:{},benchmark:null,curves:[],axis:'count',pickerOpen:false,sessionReady:false,loadingCatalog:false,needsRefresh:false,revealing:false,resetting:false,importing:false,exporting:false,restoring:false,batch:null,batchLoading:false};
let catalogueGeneration=0;
const mutationBusy=()=>state.revealing||state.resetting||state.importing||state.exporting||state.restoring;
const sessionBusy=()=>!state.sessionReady||state.needsRefresh||mutationBusy();
const viewer=new CrystalViewer($('crystal-canvas'));
const numeric=(x,fallback=null)=>Number.isFinite(Number(x))&&x!==null&&x!==''?Number(x):fallback;
const format=(x,n=3)=>numeric(x)===null?'—':Number(x).toFixed(n);
const percent=x=>numeric(x)===null?'—':x>=.999?'>99.9%':x<=.001?'<0.1%':`${(Math.max(0,Math.min(1,x))*100).toFixed(1)}%`;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const formulaHTML=x=>esc(x).replace(/(\d+(?:\.\d+)?)/g,'<sub>$1</sub>');
const canonicalSplit=x=>({cal:'calibration',dev:'development',policy:'development',policy_dev:'development',calibrate:'calibration',import:'imported'}[x]||x||'unassigned');
function normalize(candidate){candidate.prediction=candidate.prediction||candidate.predictions||{};candidate.prediction.width=numeric(candidate.prediction.upper)!==null&&numeric(candidate.prediction.lower)!==null?(candidate.prediction.upper-candidate.prediction.lower)/2:null;candidate.split=canonicalSplit(candidate.split);candidate.nsites=candidate.nsites??candidate.structure?.sites?.length;candidate.elements=candidate.elements||[...new Set((candidate.structure?.sites||[]).map(s=>s.element||s.species?.[0]?.element))].filter(Boolean);return candidate;}
async function api(path,options={}){const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});let result;try{result=await response.json();}catch{const err=new Error(`The research engine returned an unreadable response (${response.status}).`);err.status=response.status;throw err;}if(!response.ok){const detail=result.detail||result.error||`Request failed (${response.status})`;const err=new Error(typeof detail==='string'?detail:JSON.stringify(detail));err.status=response.status;throw err;}return result;}
const definitelyRejected=err=>[409,413,422].includes(err.status);
function requireCatalogRecovery(message){state.needsRefresh=true;renderList();$('catalog-retry').hidden=false;$('session-status').hidden=false;$('session-status').textContent=message;updateRevealState();}
function error(message){const el=$('global-error');el.hidden=!message;el.textContent=message||'';}
function saveFile(filename,content,type='application/json'){const url=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function catalogueCount(){const n=state.candidates.length;$('candidate-count').textContent=n.toLocaleString();$('evaluated-count').textContent=state.history.length;$('dataset-subtitle').textContent=state.metadata.subtitle||state.metadata.scope||`${n.toLocaleString()} existing structures · DFT reference replay`;}
function filteredCandidates(){const q=$('search').value.toLowerCase().trim(),partition=$('partition').value,sort=$('sort').value;return state.candidates.filter(c=>(partition==='all'||c.split===partition)&&(!q||`${c.formula} ${c.id} ${(c.elements||[]).join(' ')}`.toLowerCase().includes(q))).sort((a,b)=>sort==='formula'?String(a.formula).localeCompare(String(b.formula)):sort==='mean'?(numeric(a.prediction.mean,Infinity)-numeric(b.prediction.mean,Infinity)):(numeric(b.prediction[sort],-Infinity)-numeric(a.prediction[sort],-Infinity)));}
function renderList(focusId=null){let focusTarget=null;const list=$('candidate-list'),active=document.activeElement,focusedRow=active&&list.contains(active)?active.closest('.candidate'):null;const keepId=focusId||focusedRow?.getAttribute('data-candidate-id'),scrollTop=list.scrollTop;const candidates=filteredCandidates();const selectedVisible=!state.selected||candidates.some(c=>c.id===state.selected.id);$('picker-filter-notice').hidden=selectedVisible;$('picker-filter-notice').textContent=selectedVisible?'':'Selected crystal is outside the current filters.';$('visible-count').textContent=`${candidates.length.toLocaleString()} / ${state.candidates.length.toLocaleString()} SHOWN`;const fragment=document.createDocumentFragment();if(!candidates.length){const el=document.createElement('div');el.className='empty';el.textContent='No structures match these filters.';fragment.append(el);}else candidates.forEach(candidate=>{const button=document.createElement('button');button.type='button';button.setAttribute('data-candidate-id',candidate.id);button.disabled=state.needsRefresh;button.className=`candidate${candidate.id===state.selected?.id?' selected':''}`;const item=document.createElement('div');item.setAttribute('role','listitem');const revealed=state.history.find(h=>h.id===candidate.id);button.setAttribute('aria-label',`${candidate.formula}, ${candidate.id}, model stability probability ${percent(candidate.prediction.p_stable)}, selection score ${format(candidate.prediction.acquisition)}${revealed?', DFT reference revealed':''}`);button.setAttribute('aria-pressed',String(candidate.id===state.selected?.id));button.innerHTML=`<div><div class="candidate-formula">${formulaHTML(candidate.formula)} ${revealed?'<span title="DFT reference revealed" style="font-size:9px;color:#7e9c70">✓</span>':''}</div><div class="candidate-info">${esc(candidate.id)} · ${esc(candidate.nsites)} sites</div></div><div class="candidate-measures${$('sort').value==='acquisition'?' score-first':''}"><span class="candidate-stability">Stability <b>${percent(candidate.prediction.p_stable)}</b></span><span class="candidate-score">Score <b>${format(candidate.prediction.acquisition)}</b></span></div>`;button.addEventListener('click',()=>{if(!state.needsRefresh&&!state.restoring&&!state.resetting)select(candidate,true);});if(candidate.id===keepId)focusTarget=button;item.append(button);fragment.append(item);});list.replaceChildren(fragment);if(focusTarget){list.scrollTop=scrollTop;focusTarget.focus({preventScroll:true});if(focusedRow&&typeof focusTarget.scrollIntoView==='function')focusTarget.scrollIntoView({block:'nearest'});}}
function select(candidate,keepFocus=false){state.selected=candidate;const p=candidate.prediction;$('picker-formula').textContent=candidate.formula;$('picker-id').textContent=candidate.id;$('picker-review').textContent=`Review ${candidate.formula}`;$('analysis-selection').textContent=`${candidate.formula} · ${candidate.id}`;$('selected-formula').innerHTML=formulaHTML(candidate.formula);$('selected-id').textContent=candidate.id;$('selected-split').textContent=`${candidate.split.toUpperCase()} PARTITION`;$('space-group').textContent=typeof candidate.spacegroup==='object'?(candidate.spacegroup.symbol||candidate.spacegroup.number||'—'):(candidate.spacegroup||'—');$('sites').textContent=candidate.nsites??'—';$('volume').textContent=numeric(candidate.volume)!==null?`${format(candidate.volume,1)} Å³`:'—';$('energy-value').textContent=format(p.mean);$('interval-text').textContent=numeric(p.lower)!==null&&numeric(p.upper)!==null?`90% interval · ${format(p.lower)} to ${format(p.upper)} eV / atom`:'Calibrated interval unavailable';$('p-stable').textContent=percent(p.p_stable);$('probability-fill').style.width=`${numeric(p.p_stable,0)*100}%`;$('acquisition').textContent=format(p.acquisition);$('cost').textContent=numeric(p.relative_cost)!==null?`${format(p.relative_cost,2)}×`:`${format(p.cost,2)} units`;$('novelty').textContent=format(p.novelty,2);
  const values=[0,p.lower,p.upper,p.mean].map(x=>numeric(x)).filter(x=>x!==null);const extent=Math.max(...values)-Math.min(...values);const padding=Math.max(.03,extent*.08);const domainMin=Math.min(...values)-padding,domainMax=Math.max(...values)+padding;const position=x=>100*(numeric(x,0)-domainMin)/(domainMax-domainMin);const low=position(p.lower),high=position(p.upper),zero=position(0);$('energy-range').hidden=numeric(p.lower)===null||numeric(p.upper)===null;$('energy-point').hidden=numeric(p.mean)===null;$('energy-range').style.left=`${low}%`;$('energy-range').style.width=`${Math.max(0,high-low)}%`;$('energy-point').style.left=`${position(p.mean)}%`;$('energy-zero').style.left=`${zero}%`;$('energy-axis').querySelector('.zero-line').style.left=`${zero}%`;$('energy-min').textContent=format(domainMin,2);$('energy-max').textContent=(domainMax>=0?'+':'')+format(domainMax,2);$('energy-axis').setAttribute('aria-label',`Signed hull distance in eV per atom, from ${format(domainMin)} to ${format(domainMax)}. Zero marks the reference hull; values at or below zero are stable against this reference.`);
  const probability=numeric(p.p_stable);const sentence=probability===null?'No calibrated stability probability is available.':probability>=.7?'The model assigns a high probability of stability.':probability>=.35?'Stability remains uncertain; the reference could change this assessment.':'The model favors instability; this may still be informative to evaluate.';
  const weights=p.acquisition_weights;const fittedReason=weights?`Probability ${percent(p.p_stable)}. ${numeric(weights.exploration,0)>0?`Exploration weight ${format(weights.exploration,2)}; `:''}${numeric(weights.diversity,0)>0?`novelty weight ${format(weights.diversity,2)}; `:''}${numeric(weights.cost_exponent,0)>0?`relative-cost exponent ${format(weights.cost_exponent,2)}.`:'no cost penalty.'}${numeric(weights.exploration,0)===0?' No explicit exploration bonus.':''}${numeric(weights.diversity,0)===0?' No novelty bonus.':''}`:null;$('rationale').textContent=p.rationale||fittedReason||p.acquisition_note||(candidate.prediction_status&&probability===null?String(candidate.prediction_status):`${sentence} Inspect the saved method and reference replay before treating this ranking as evidence of discovery.`);
  $('element-legend').innerHTML=(candidate.elements||[]).map(e=>`<span class="element-item"><i style="--element:${elementColor(e)}"></i>${esc(e)}</span>`).join('');
  viewer.setStructure(candidate.structure);updateRevealState();renderList(keepFocus?candidate.id:null);}
function describeReference(entry) {
  const reference = numeric(entry.e_above_hull ?? entry.reference ?? entry.energy);
  if (reference === null) return 'The saved reference has no available energy value.';

  const prediction = entry.prediction_at_selection;
  const low = numeric(prediction?.interval_low);
  const high = numeric(prediction?.interval_high);
  const stable = entry.stable ?? reference <= 0;
  const source = entry.source || 'Previously computed WBM DFT';
  const unit = 'eV/atom';
  const energy = value => format(value, 6);
  let intervalResult = 'Selection-time interval unavailable.';
  let comparison = '';
  if (low !== null && high !== null) {
    const delta = reference > high ? reference - high : low - reference;
    const position = reference > high ? 'above' : 'below';
    comparison = reference >= low && reference <= high ? 'Reference falls within the interval.'
      : `Reference is ${energy(delta)} ${unit} ${position} the interval.`;
    intervalResult = `90% interval at selection: [${energy(low)}, ${energy(high)}] ${unit}.`;
  }
  const mean = numeric(prediction?.predicted_hull);
  const threshold = stable ? 'Stable by the fixed hull criterion (≤ 0 eV/atom).' : 'Above the fixed hull threshold (0 eV/atom).';
  const meanText = mean === null ? '' : `Selection-time estimate: ${energy(mean)} ${unit}.`;
  const sourceText = source[0].toUpperCase() + source.slice(1);
  return [comparison, `${sourceText}: ${energy(reference)} ${unit}.`, intervalResult, meanText, threshold]
    .filter(Boolean).join('\n');
}
function updateRevealState(){const busy=sessionBusy();
  $('batch-open').disabled=busy;$('batch-preview').disabled=busy||state.batchLoading;$('batch-count').disabled=busy||state.batchLoading;
  $('batch-close').disabled=state.revealing;$('batch-reveal').disabled=busy||state.batchLoading||!state.batch?.recommendations?.length;
$('picker-toggle').disabled=!state.sessionReady||state.needsRefresh||state.restoring||state.resetting;$('picker-review').disabled=!state.selected||state.needsRefresh;$('import-submit').disabled=busy;$('restore-submit').disabled=busy;$('replay-submit').disabled=busy;$('reset-session').disabled=busy;$('import-open').disabled=busy;$('restore-open').disabled=busy;$('export-session').disabled=busy||!state.candidates.length;const selected=state.selected,entry=state.history.find(x=>x.id===selected?.id);$('download-cif').disabled=busy||!selected;$('reveal-result').hidden=!entry;$('reveal').disabled=!selected||busy||selected.split==='imported'||Boolean(entry);$('reveal').innerHTML=state.revealing?'Revealing reference…':entry?'Reference already revealed ✓':selected?.split==='imported'?'No reference for imported structure':'Reveal DFT reference <span aria-hidden="true">→</span>';
  if (entry) {
    $('reveal-result').className = `reveal-result${entry.stable === false ? ' unstable' : ''}`;
    $('reveal-result').textContent = describeReference(entry);
  }
}
function renderHistory(){catalogueCount();$('log-evaluations').textContent=state.history.length;$('log-stable').textContent=state.history.filter(h=>{const e=numeric(h.e_above_hull??h.reference??h.energy);return e!==null&&(h.stable??(e<=0));}).length;$('log-cost').textContent=format(state.history.reduce((sum,h)=>sum+numeric(h.cost??state.candidates.find(c=>c.id===h.id)?.prediction.relative_cost,1),0),1);if(!state.history.length){$('history').innerHTML='<div class="empty"><span class="empty-symbol">⌁</span><strong>Your next decision starts here.</strong><p>Inspect a candidate, then reveal its reference. Every choice stays in this session’s exportable research record.</p></div>';return;}$('history').innerHTML=state.history.map((h,i)=>{const c=state.candidates.find(c=>c.id===h.id),energy=numeric(h.e_above_hull??h.reference??h.energy),stable=energy===null?null:(h.stable??(energy<=0));return `<div class="history-row"><span class="history-index">${String(i+1).padStart(2,'0')}</span><div><h4>${formulaHTML(h.formula||c?.formula||h.id)}</h4><p>${esc(h.id)}</p></div><span class="history-energy${stable===false?' unstable':''}">${format(energy)}<small>${stable===null?'REFERENCE UNAVAILABLE':stable?'DFT STABLE':'ABOVE HULL'} · eV / atom</small></span></div>`;}).reverse().join('');}
async function reveal(batch=null){
  if(sessionBusy()||(!batch&&!state.selected))return;
  const selected=state.selected;
  const focusResult = !batch && document.activeElement === $('reveal');
  state.revealing=true;error('');updateRevealState();let committed=false;
  try{
    const path=batch?'/api/recommendations/reveal':'/api/reveal';
    const body=batch?{count:batch.requested_count,snapshot:batch.snapshot}:{ids:[selected.id]};
    const result=await api(path,{method:'POST',body:JSON.stringify(body)});
    committed=true;catalogueGeneration++;state.batch=null;
    if(Array.isArray(result.history))state.history=result.history;
    else for(const row of result.results||[])if(!state.history.some(entry=>entry.id===row.id))state.history.push(row);
    if(result.model_updated||batch){
      const refreshed=await api('/api/catalog');
      state.candidates=(refreshed.candidates||[]).map(normalize);state.metadata=refreshed.metadata||{};
      if(Array.isArray(refreshed.history))state.history=refreshed.history;
      const candidate=state.candidates.find(c=>c.id===(state.selected?.id||selected?.id))||state.candidates[0];
      if(candidate)select(candidate);
    }
    renderHistory();renderList();updateReplayOrigin();
    if (focusResult && state.selected?.id === selected.id && !$('reveal-result').hidden
        && [document.body, $('reveal')].includes(document.activeElement)) $('reveal-result').focus();
    if(batch){$('batch-dialog').close();$('session-status').hidden=false;$('session-status').textContent=`Revealed ${result.results.length} references together. The selection model was updated once.`;}
  }catch(e){
    state.batch=null;
    requireCatalogRecovery(committed?'Reference revealed. Candidate details are stale until refreshed.':'Reveal outcome or session state needs checking. Refresh candidates before continuing.');
    const message=committed?`Reference revealed, but the updated catalog could not be loaded. ${e.message}`:`Could not confirm the reveal. ${e.message}`;
    if(batch){$('batch-dialog').close();$('batch-error').textContent=message;}
    error(`${message} Retry loading candidates to check the session before continuing.`);
  }finally{state.revealing=false;updateRevealState();}
}
let batchGeneration=0;
function cancelBatch(){batchGeneration++;state.batchLoading=false;state.batch=null;updateRevealState();}
$('batch-open').addEventListener('click',()=>{
  if(sessionBusy())return;cancelBatch();$('batch-list').replaceChildren();$('batch-error').hidden=true;
  $('batch-status').textContent='Choose a size, then preview the candidates.';$('batch-dialog').showModal();
});
$('batch-close').addEventListener('click',()=>{if(!state.revealing){cancelBatch();$('batch-dialog').close();}});
$('batch-dialog').addEventListener('cancel',event=>{if(state.revealing)event.preventDefault();else cancelBatch();});
$('batch-dialog').addEventListener('close',cancelBatch);
$('batch-count').addEventListener('change',()=>{cancelBatch();$('batch-list').replaceChildren();$('batch-status').textContent='Size changed. Preview the new batch before revealing.';});
$('batch-preview').addEventListener('click',async()=>{
  if(sessionBusy()||state.batchLoading)return;
  const generation=++batchGeneration,catalogGeneration=catalogueGeneration;
  state.batchLoading=true;state.batch=null;$('batch-list').replaceChildren();$('batch-error').hidden=true;
  $('batch-status').textContent='Selecting candidates without revealing references…';updateRevealState();
  try{
    const result=await api(`/api/recommendations?count=${encodeURIComponent($('batch-count').value)}`);
    if(generation!==batchGeneration||catalogGeneration!==catalogueGeneration||mutationBusy()||state.needsRefresh)return;
    state.batch=result;
    for(const row of result.recommendations){
      const item=document.createElement('li');item.innerHTML=`<div><strong>${formulaHTML(row.formula)}</strong><small>${esc(row.id)}</small><small>Model stability ${percent(row.stable_probability)} · score ${format(row.acquisition)} · novelty ${format(row.novelty,2)} · cost ${format(row.relative_cost,2)}×</small></div>`;
      $('batch-list').append(item);
    }
    $('batch-status').textContent=result.recommendations.length?`${result.recommendations.length} candidates ready. Predictions stay fixed until the whole batch is revealed.`:'All held-out references have already been revealed.';
  }catch(e){if(generation===batchGeneration){$('batch-error').textContent=`Cannot preview this batch. ${e.message} Try again.`;$('batch-error').hidden=false;$('batch-status').textContent='No references were revealed.';}}
  finally{if(generation===batchGeneration){state.batchLoading=false;updateRevealState();}}
});
$('batch-reveal').addEventListener('click',()=>{if(state.batch&&!sessionBusy()&&!state.batchLoading)reveal(state.batch);});
async function exportSession(){if(sessionBusy())return;const context={selected_id:state.selected?.id,inspected_budget:{axis:state.axis,budget:numeric($('budget').value)},filters:{search:$('search').value,partition:$('partition').value,sort:$('sort').value},benchmark:state.benchmark};state.exporting=true;updateRevealState();error('');try{const data=await api('/api/session');Object.assign(data,context);saveFile('materialmind-research-record.json',JSON.stringify(data,null,2));}catch(e){error(`Cannot export the research record. ${e.message}`);}finally{state.exporting=false;updateRevealState();}}
function updateReplayOrigin(){ $('replay-origin').hidden=state.metadata?.replay_origin?.kind!=='replayed_as_new'; }
let restoreSource = null;
$('restore-input').addEventListener('input', () => { restoreSource = null; });
function restoreError(message){$('restore-error').textContent=message;$('restore-error').hidden=!message;}
$('restore-open').addEventListener('click',()=>{if(sessionBusy())return;$('restore-dialog').showModal();$('restore-file').focus();});
$('restore-close').addEventListener('click',()=>{if(!state.restoring)$('restore-dialog').close();});
$('restore-dialog').addEventListener('cancel',event=>{if(state.restoring)event.preventDefault();});
$('restore-file').addEventListener('change',async event=>{
  const file=event.target.files?.[0];if(!file||state.restoring)return;restoreError('');
  if(file.size>16777216){restoreError('Choose a JSON record no larger than 16 MiB. Your pasted input has been kept.');event.target.value='';return;}
  const previous=$('restore-input').value;
  try{
    const bytes=new Uint8Array(await file.arrayBuffer());
    const text=new TextDecoder('utf-8',{fatal:true}).decode(bytes);
    if(file===event.target.files?.[0]&&!state.restoring){
      if($('restore-input').value!==previous)restoreError('Pasted JSON changed while the file was reading. Your edits were kept. Choose the file again to replace them.');
      else{$('restore-input').value=text;restoreSource={bytes,text:$('restore-input').value};$('restore-file-name').textContent=`Loaded ${file.name}. You can choose this file again to reload its original content.`;}
      event.target.value='';
    }
  }catch{if(file===event.target.files?.[0])event.target.value='';restoreError('Cannot read that file. Choose it again or paste the JSON.');}
});
$('restore-form').addEventListener('submit',async event=>{
  event.preventDefault();if(sessionBusy()||!$('restore-confirm').checked)return;restoreError('');
  const replay=event.submitter?.id==='replay-submit';
  if(replay&&!confirm('Reuse the recorded choices and geometry with this installation? Predictions, labels and costs will be recalculated. This does not verify the original model.'))return;
  const text=$('restore-input').value;
  const body=restoreSource?.text===text?restoreSource.bytes:text;
  if(new TextEncoder().encode(text).length>16777216){restoreError('The JSON record exceeds 16 MiB.');return;}
  try{JSON.parse(text);}catch{restoreError('Invalid JSON. Choose an original schema-3 export or correct the pasted input.');return;}
  const selectedId=state.selected?.id;state.restoring=true;updateRevealState();
  for(const id of ['restore-submit','replay-submit','restore-close','restore-file','restore-input','restore-confirm'])$(id).disabled=true;
  $('restore-progress').hidden=false;$('restore-submit').textContent='Rebuilding session…';
  try{
    const result=await api(replay?'/api/session/replay':'/api/session',{method:'POST',body});
    catalogueGeneration++;
    state.candidates=result.candidates.map(normalize);state.metadata=result.metadata;state.history=result.history;
    const candidate=state.candidates.find(c=>c.id===selectedId)||state.candidates[0];
    if(candidate)select(candidate);renderHistory();renderList();error('');
    restoreSource=null;updateReplayOrigin();$('session-status').textContent=replay?'Replayed with current model; original predictions unverified.':`Restored ${state.history.length} revealed references across ${state.metadata.model_revision} original model updates. Search and filters were kept.`;
    $('session-status').hidden=false;$('restore-dialog').close();$('restore-input').value='';$('restore-file').value='';$('restore-file-name').textContent='';$('restore-confirm').checked=false;
  }catch(err){if(!definitelyRejected(err)){requireCatalogRecovery('Restore outcome is unconfirmed. Candidate details may be stale until refreshed.');restoreError(`${err.message} Your input is kept. Close this dialog and retry loading candidates to check the session.`);}else restoreError(`${err.message} Your input is kept; correct it or choose another record.`);}
  finally{
    state.restoring=false;updateRevealState();$('restore-progress').hidden=true;$('restore-submit').textContent='Restore session';
    for(const id of ['replay-submit','restore-close','restore-file','restore-input','restore-confirm'])$(id).disabled=false;updateRevealState();
  }
});
const METHOD_NAMES={materialmind:'MaterialMind',learned:'MaterialMind',learned_acquisition:'MaterialMind',calibrated:'MaterialMind',random:'Random',greedy:'Property greedy',property_greedy:'Adapted greedy',pretrained_greedy:'CHGNet greedy',uncertainty:'Uncertainty',diversity:'Diversity',bo:'GP expected improvement',bayesian_optimization:'GP expected improvement',gp_ei:'GP log-EI',uncalibrated:'Uncalibrated',no_diversity:'No diversity',no_cost:'No cost',no_online_update:'Frozen surrogate'};
const COLORS=['#629366','#c59a76','#7d9ab4','#b1af75','#ad94b1','#8baba1','#bb8f98','#8c9c7a'];
const METHOD_COLORS={materialmind:'#52815b',random:'#b6bdb0',pretrained_greedy:'#bf9865',property_greedy:'#b77f67',uncertainty:'#789ab3',diversity:'#a5a767',gp_ei:'#a58caf',uncalibrated:'#9ebbac',no_diversity:'#b89d9e',no_cost:'#839782',no_online_update:'#b3a47a'};
const methodName=m=>METHOD_NAMES[m]||String(m).replaceAll('_',' ');
function normalizeCurves(data){let curves=[];
  if(Array.isArray(data.curves)){
    if(data.curves[0]?.points)curves=data.curves.map(c=>({method:c.method||c.name,points:c.points}));
    else{const grouped={};data.curves.forEach(p=>{const m=p.method||p.strategy||'unknown';(grouped[m]||=[]).push({budget:p.budget??p.step??p.evaluations,mean:p.mean??p.stable_found??p.discoveries,lower:p.lower??p.ci_lower,upper:p.upper??p.ci_upper});});curves=Object.entries(grouped).map(([method,points])=>({method,points}));}
  }else if(data.curves&&typeof data.curves==='object')curves=Object.entries(data.curves).map(([method,c])=>({method,points:Array.isArray(c)?c:(c.points||c.mean?.map((mean,i)=>({budget:i+1,mean,lower:c.lower?.[i],upper:c.upper?.[i]}))||[])}));
  else if(Array.isArray(data.methods))curves=data.methods.map(c=>({method:c.method||c.name,points:c.curve||c.points||[]}));
  else if(data.summary&&typeof data.summary==='object')Object.entries(data.summary).forEach(([method,c])=>{if(c.curve)curves.push({method,points:c.curve});});
  return curves.map((c,i)=>({...c,color:METHOD_COLORS[c.method]||COLORS[i%COLORS.length],points:c.points.map((p,j)=>typeof p==='number'?{budget:j+1,mean:p}:{budget:numeric(p.budget??p.step??p.evaluations,j+1),mean:numeric(p.mean??p.stable_found??p.discoveries??p.value),lower:numeric(p.lower??p.ci_low??p.ci_lower),upper:numeric(p.upper??p.ci_high??p.ci_upper)}).filter(p=>numeric(p.mean)!==null).sort((a,b)=>a.budget-b.budget)})).filter(c=>c.points.length);}
function renderChart(){const curves=state.curves;if(!curves.length){$('discovery-chart').innerHTML='<div class="empty">No saved benchmark curves are available.<br>Run the documented benchmark to produce measured comparisons.</div>';$('budget').disabled=true;return;}
  $('budget').disabled=false;
  const box=$('discovery-chart').getBoundingClientRect(),W=Math.max(400,box.width-40),H=205,L=40,R=18,T=17,B=35;const maxX=Math.max(...curves.flatMap(c=>c.points.map(p=>p.budget)));const maxY=Math.max(1,...curves.flatMap(c=>c.points.map(p=>p.upper??p.mean)));const ceilY=Math.max(5,Math.ceil(maxY/5)*5);const x=v=>L+(W-L-R)*v/maxX,y=v=>H-B-(H-B-T)*v/ceilY;const line=points=>points.map((p,i)=>`${i?'L':'M'}${x(p.budget).toFixed(2)},${y(p.mean).toFixed(2)}`).join(' ');let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Measured stable candidates discovered versus ${state.axis==='cost'?'normalized proxy cost':'reference evaluations'} for ${curves.map(c=>methodName(c.method)).join(', ')}">`;
  for(let i=0;i<=4;i++){const value=ceilY*i/4;svg+=`<line x1="${L}" x2="${W-R}" y1="${y(value)}" y2="${y(value)}" stroke="#dde4d5" stroke-dasharray="3 4"/><text x="${L-10}" y="${y(value)+3}" text-anchor="end" fill="#304f47" font-family="monospace" font-size="12">${format(value,0)}</text>`;}
  for(let i=0;i<=4;i++){const value=maxX*i/4;svg+=`<text x="${x(value)}" y="${H-17}" text-anchor="middle" fill="#304f47" font-family="monospace" font-size="12">${format(value,0)}</text>`;}
  curves.forEach(c=>{if(c.points.every(p=>p.lower!==null&&p.upper!==null)){const polygon=c.points.map(p=>`${x(p.budget)},${y(p.upper)}`).concat([...c.points].reverse().map(p=>`${x(p.budget)},${y(p.lower)}`)).join(' ');svg+=`<polygon points="${polygon}" fill="${c.color}" opacity=".07"/>`;}svg+=`<path d="${line(c.points)}" fill="none" stroke="${c.color}" stroke-width="${['materialmind','learned','calibrated'].includes(c.method)?2.4:1.2}" stroke-linecap="round"/>`;});
  const selectedBudget=numeric($('budget').value,20);svg+=`<line x1="${x(Math.min(selectedBudget,maxX))}" x2="${x(Math.min(selectedBudget,maxX))}" y1="${T}" y2="${H-B}" stroke="#65855c" stroke-width="1" opacity=".4" stroke-dasharray="3 3"/><text x="${(L+W-R)/2}" y="${H-2}" text-anchor="middle" fill="#304f47" font-family="monospace" font-size="11">${state.axis==='cost'?'NORMALIZED PROXY COST':'REFERENCE EVALUATIONS'}</text></svg>`;$('discovery-chart').innerHTML=svg;$('chart-legend').innerHTML=curves.map(c=>`<span><i style="--line:${c.color}"></i>${esc(methodName(c.method))}</span>`).join('');$('budget').max=maxX;if(numeric($('budget').value)>maxX)$('budget').value=maxX;renderBudget();}
function renderBudget(){const n=numeric($('budget').value,20);$('budget-label').textContent=n;const summaries=state.curves.map(c=>{const p=[...c.points].reverse().find(p=>p.budget<=n);return `${methodName(c.method)}: ${p?format(p.mean,1):'not available'}`;});$('budget-summary').textContent=summaries.length?`${summaries.join('  ·  ')} stable candidates (mean)`:'No measurements available.';}
function setAxis(axis){state.axis=axis;$('count-axis').setAttribute('aria-pressed',axis==='count');$('cost-axis').setAttribute('aria-pressed',axis==='cost');$('budget-kind').textContent=axis==='count'?'Inspect evaluation budget':'Inspect normalized proxy-cost budget';if(!state.benchmark){$('discovery-chart').innerHTML='<div class="empty loading">Loading saved benchmark…</div>';$('budget').disabled=true;return;}state.curves=normalizeCurves({...state.benchmark,curves:axis==='cost'?state.benchmark?.cost_curves:state.benchmark?.curves});renderChart();}
async function loadBenchmark(){try{state.benchmark=await api('/api/benchmark');const meta=state.benchmark.metadata||state.benchmark.protocol||{};const seeds=state.benchmark.n_seeds||state.benchmark.seeds||meta.seeds;if(seeds)$('seed-badge').textContent=`${Array.isArray(seeds)?seeds.length:seeds} SEEDS`;if(meta.description)$('benchmark-context').textContent=meta.description;else if(state.benchmark.study)$('benchmark-context').textContent=state.benchmark.study;if(state.benchmark.note||meta.note)$('benchmark-note').textContent=state.benchmark.note||meta.note;else if(state.benchmark.ci_scope)$('benchmark-note').textContent=`95% intervals. ${state.benchmark.ci_scope}`;setAxis(state.axis);}catch(e){$('discovery-chart').innerHTML=`<div class="empty">Saved benchmark unavailable.<br>${esc(e.message)}</div>`;$('budget').disabled=true;}}
async function load(){
  if(state.loadingCatalog)return;state.loadingCatalog=true;updateRevealState();
  const generation=catalogueGeneration;
  try{
    const result=await api('/api/catalog');
    if(generation===catalogueGeneration){
      $('catalog-retry').hidden=true;error('');const wasStale=state.needsRefresh;
      state.candidates=(result.candidates||[]).map(normalize);state.metadata=result.metadata||{};updateReplayOrigin();state.sessionReady=true;state.needsRefresh=false;if(wasStale)$('session-status').hidden=true;
      if(result.history)state.history=result.history;
      catalogueCount();renderHistory();
      const previousId=state.selected?.id;const sorted=[...state.candidates].sort((a,b)=>numeric(b.prediction.acquisition,-Infinity)-numeric(a.prediction.acquisition,-Infinity));
      if(sorted.length)select(sorted.find(c=>c.id===previousId)||sorted.find(c=>c.split==='test')||sorted[0]);else {state.selected=null;renderList();updateRevealState();}
    }
  }catch(e){
    if(generation===catalogueGeneration){
      error(`Cannot load candidates. ${e.message} Check that the local server is running, then retry.`);$('catalog-retry').hidden=false;
      $('candidate-list').innerHTML='<div class="empty">The research engine is unavailable. Start the MaterialMind server and reload this page.</div>';
    }
  }
  state.loadingCatalog=false;updateRevealState();
  await loadBenchmark();
}
function setPickerOpen(open){
  state.pickerOpen=open;$('candidate-panel').setAttribute('data-picker-open',String(open));
  $('picker-toggle').setAttribute('aria-expanded',String(open));
  $('picker-toggle').textContent=open?'Close picker':'Change crystal';
  if(open){const selected=$('candidate-list').querySelector('.candidate.selected');if(selected&&typeof selected.scrollIntoView==='function')selected.scrollIntoView({block:'nearest'});}
}
$('picker-toggle').addEventListener('click',()=>{if(!state.sessionReady||state.needsRefresh||state.restoring||state.resetting)return;setPickerOpen(!state.pickerOpen);});
$('picker-review').addEventListener('click',()=>{if(!state.selected||state.needsRefresh)return;setPickerOpen(false);$('analysis-heading').focus();$('analysis-heading').scrollIntoView({block:'start'});});
$('catalog-retry').addEventListener('click',()=>{if(!state.loadingCatalog&&!mutationBusy()){$('catalog-retry').hidden=true;$('candidate-list').innerHTML='<div class="empty loading">Loading structures…</div>';load();}});$('search').addEventListener('input',()=>renderList());$('partition').addEventListener('change',()=>renderList());$('sort').addEventListener('change',()=>renderList());$('reveal').addEventListener('click',()=>reveal());$('export-session').addEventListener('click',exportSession);$('download-cif').addEventListener('click',()=>{if(state.selected&&!sessionBusy()){const a=document.createElement('a');a.href=`/api/cif/${encodeURIComponent(state.selected.id)}`;a.download=`${state.selected.id}.cif`;a.click();}});$('reset-view').addEventListener('click',()=>viewer.reset());$('toggle-cell').addEventListener('click',()=>{$('toggle-cell').setAttribute('aria-pressed',viewer.toggleCell());});$('toggle-bonds').addEventListener('click',()=>{$('toggle-bonds').setAttribute('aria-pressed',viewer.toggleBonds());});$('budget').addEventListener('input',renderChart);$('count-axis').addEventListener('click',()=>setAxis('count'));$('cost-axis').addEventListener('click',()=>setAxis('cost'));new ResizeObserver(()=>renderChart()).observe($('discovery-chart'));
$('reset-session').addEventListener('click',async()=>{
  if(sessionBusy())return;
  if(!confirm('Reset this session? Revealed references and imported structures will be removed. Export the record first if you want to restore it later.'))return;
  state.resetting=true;updateRevealState();let committed=false;
  try{
    await api('/api/reset',{method:'POST',body:'{}'});committed=true;catalogueGeneration++;
    state.needsRefresh=true;state.history=[];state.metadata={...state.metadata,replay_origin:null};updateReplayOrigin();renderHistory();renderList();updateRevealState();
    $('session-status').textContent='Session reset. Refreshing the candidate view…';$('session-status').hidden=false;
    const selectedId=state.selected?.id;const refreshed=await api('/api/catalog');
    state.candidates=(refreshed.candidates||[]).map(normalize);state.metadata=refreshed.metadata||{};state.history=refreshed.history||[];state.needsRefresh=false;
    const candidate=state.candidates.find(c=>c.id===selectedId)||filteredCandidates()[0]||state.candidates[0];
    if(candidate)select(candidate);renderHistory();renderList();updateReplayOrigin();error('');$('session-status').hidden=true;
  }catch(e){
    if(committed){error(`Session reset, but the candidate view is out of date. ${e.message} Retry loading candidates before continuing.`);$('catalog-retry').hidden=false;$('session-status').textContent='Session reset. Candidate details below are stale until refreshed.';}
    else{state.needsRefresh=true;renderList();$('catalog-retry').hidden=false;$('session-status').hidden=false;$('session-status').textContent='Reset outcome is unconfirmed. Candidate details may be stale until refreshed.';error(`Could not confirm reset. ${e.message} Retry loading candidates to check the session before continuing.`);}
  }finally{state.resetting=false;updateRevealState();}
});
let cifReadGeneration=0;
$('import-open').addEventListener('click',()=>{if(sessionBusy())return;$('import-dialog').showModal();$('cif-input').focus();});
const invalidateCifRead=()=>{cifReadGeneration++;$('cif-file').value='';};
$('import-close').addEventListener('click',()=>{if(state.importing)return;invalidateCifRead();$('import-dialog').close();});
$('import-dialog').addEventListener('cancel',event=>{if(state.importing){event.preventDefault();return;}invalidateCifRead();});
$('import-dialog').addEventListener('close',invalidateCifRead);
$('cif-file').addEventListener('change',async e=>{
  const generation=++cifReadGeneration,file=e.target.files?.[0];if(!file)return;
  if(file.size>1000000){$('import-error').hidden=false;$('import-error').textContent='Please choose a CIF smaller than 1 MB.';e.target.value='';return;}
  const previous=$('cif-input').value;
  try{
    const text=await file.text();if(generation!==cifReadGeneration)return;
    if($('cif-input').value!==previous){$('import-error').textContent='CIF text changed while the file was reading. Your edits were kept; choose the file again to replace them.';$('import-error').hidden=false;}
    else{$('cif-input').value=text;$('import-error').hidden=true;}
  }catch{if(generation!==cifReadGeneration)return;$('import-error').textContent='Cannot read that file. Your existing CIF text is kept; choose the file again or paste its contents.';$('import-error').hidden=false;}
  finally{if(generation===cifReadGeneration)e.target.value='';}
});$('import-form').addEventListener('submit',async e=>{
  e.preventDefault();if(sessionBusy())return;cifReadGeneration++;
  const submitted=$('cif-input').value;state.importing=true;updateRevealState();
  for(const id of ['import-submit','import-close','cif-file','cif-input'])$(id).disabled=true;
  $('import-submit').textContent='Validating structure…';$('import-error').hidden=true;
  let imported=false;
  try{
    const result=await api('/api/import',{method:'POST',body:JSON.stringify({cif:submitted})});
    catalogueGeneration++;imported=true;
    const refreshed=await api('/api/catalog');
    const candidates=(refreshed.candidates||[]).map(normalize);
    const candidate=candidates.find(c=>c.id===(result.candidate||result).id);
    if(!candidate)throw new Error('The refreshed catalog does not contain the imported structure.');
    state.candidates=candidates;state.metadata=refreshed.metadata||{};state.history=refreshed.history||[];
    $('partition').value='all';$('search').value='';catalogueCount();renderHistory();select(candidate);
    if($('cif-input').value===submitted){$('import-dialog').close();$('cif-input').value='';}else{$('import-error').textContent='The structure was imported. Newer CIF text was kept; close this dialog or submit it separately.';$('import-error').hidden=false;}
  }catch(err){
    if(imported||!definitelyRejected(err)){
      requireCatalogRecovery(imported?'Structure imported. Candidate details are stale until refreshed.':'Import outcome is unconfirmed. Candidate details may be stale until refreshed.');
      $('import-error').textContent=`${imported?'The structure was imported, but the catalog could not be refreshed.':'Could not confirm the import.'} ${err.message} Your input is kept. Close this dialog and retry loading candidates to check the session.`;
    }else $('import-error').textContent=err.message;
    $('import-error').hidden=false;
  }finally{
    state.importing=false;for(const id of ['import-close','cif-file','cif-input'])$(id).disabled=false;updateRevealState();$('import-submit').textContent='Validate structure →';
  }
});
updateRevealState();load();
