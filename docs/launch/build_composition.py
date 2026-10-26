"""Assemble launch media exclusively from current authentic artifacts."""
from pathlib import Path
import hashlib
import json
import shutil

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ASSETS = HERE / 'composition/assets'
ASSETS.mkdir(parents=True, exist_ok=True)
summary_path = REPO / 'materialmind/artifacts/summary.json'
summary = json.loads(summary_path.read_text())
inputs = {
    'brand.svg': REPO / 'docs/media/brand.svg',
    'lab.png': REPO / 'docs/media/lab.png',
    'lab-revealed.png': REPO / 'docs/media/lab-revealed.png',
    'discovery.png': REPO / 'materialmind/artifacts/figures/discovery.png',
}
manifest = {'summary_sha256': hashlib.sha256(summary_path.read_bytes()).hexdigest(), 'inputs': {}}
for name, path in inputs.items():
    data = path.read_bytes()
    manifest['inputs'][name] = {'source': str(path.relative_to(REPO)), 'sha256': hashlib.sha256(data).hexdigest()}
    shutil.copyfile(path, ASSETS / name)
(HERE / 'sources.json').write_text(json.dumps(manifest, indent=2) + '\n')
html = r'''<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><title>MATERIALMIND · launch film</title>
<script src="assets/gsap.min.js"></script>
<style>
*{box-sizing:border-box}body{margin:0;width:1920px;height:1080px;overflow:hidden;background:#14252b;font-family:Arial,Helvetica,sans-serif;color:#cbe1d2}.scene{position:absolute;inset:0;width:1920px;height:1080px;overflow:hidden;background:#14252b}.content{width:100%;height:100%;padding:44px 72px;display:flex;flex-direction:column;gap:18px;box-sizing:border-box}.eyebrow{font:14px monospace;letter-spacing:3px;color:#a4b9aa;margin:0;white-space:nowrap}h1{font-size:54px;font-weight:400;letter-spacing:-1.5px;line-height:1.1;margin:0;color:#e0eddf}.caption{font-size:19px;letter-spacing:.2px;color:#9fb2a3;line-height:1.4;margin:0}.scene:not(#scene1){opacity:0}#scene1{background:#eef0ec;z-index:1}#scene2{z-index:2;opacity:0}#scene3{z-index:3;opacity:0}#scene4{z-index:4;opacity:0}.cover{padding:0;justify-content:center;gap:0}.cover img{width:1920px;height:960px;object-fit:contain}.screen-wrap{flex:1;min-height:0;width:100%;display:flex;align-items:center;justify-content:center;overflow:hidden;border:1px solid #4b6256;border-radius:8px;background:#eef0ec;box-shadow:0 18px 60px #0003}.screen{width:100%;height:100%;object-fit:contain}.foot{display:flex;justify-content:space-between;align-items:center;font:12px monospace;letter-spacing:1px;color:#9fb5a4;line-height:1.4;min-height:21px}.foot strong{font-weight:400;color:#cbe1d2}.evidence-layout{display:flex;gap:42px;flex:1;align-items:center;min-height:0}.figure-wrap{width:1330px;flex-shrink:0;background:#fafaf6;border:1px solid #809383;border-radius:8px;overflow:hidden;padding:12px}.figure{display:block;width:100%;height:auto}.measurements{flex:1;display:flex;flex-direction:column;gap:36px}.measurement{padding:0 0 22px;border-bottom:1px solid #4f6759}.measurement strong{font-size:55px;font-weight:400;letter-spacing:-2px;color:#d4e9d7;display:block;font-variant-numeric:tabular-nums}.measurement span{font:15px monospace;letter-spacing:1px;color:#a9bcaa;line-height:1.6;display:block;margin-top:8px}.caution{color:#a5b7a6;max-width:340px;font-size:18px;line-height:1.55;margin:0}.label-emphasis{color:#d4e9d7}
</style></head><body>
<div id="root" data-composition-id="main" data-width="1920" data-height="1080" data-start="0" data-duration="20">
<section id="scene1" class="scene"><div class="content cover"><img id="brand" src="assets/brand.svg" alt="MATERIALMIND LAB. Make the next evaluation count."></div></section>
<section id="scene2" class="scene"><div class="content"><p id="s2-label" class="eyebrow">01 / EXAMINE THE CANDIDATE</p><h1 id="s2-title">Inspect the structure. Read the uncertainty.</h1><div id="s2-screen" class="screen-wrap" data-layout-allow-overflow><img class="screen" src="assets/lab.png" alt="Actual MATERIALMIND laboratory with a selected crystal and calibrated stability prediction"></div><div id="s2-foot" class="foot"><span>ACTUAL APPLICATION / FROZEN CHGNET FEATURES + ADAPTED STABILITY MODEL</span><strong>MATERIALMIND LAB</strong></div></div></section>
<section id="scene3" class="scene"><div class="content"><p id="s3-label" class="eyebrow">02 / QUERY THE REFERENCE</p><h1 id="s3-title">Reveal a reference. Update the model.</h1><div id="s3-screen" class="screen-wrap" data-layout-allow-overflow><img class="screen" src="assets/lab-revealed.png" alt="Actual reference reveal and updated model in MATERIALMIND"></div><div id="s3-foot" class="foot"><span>PREVIOUSLY COMPUTED DFT / RETROSPECTIVE REPLAY</span><strong>SELECT → REVEAL → REFIT</strong></div></div></section>
<section id="scene4" class="scene"><div class="content"><p id="s4-label" class="eyebrow">03 / EVALUATE THE STRATEGY</p><h1 id="s4-title">Compare. Reproduce. Question.</h1><p id="s4-caption" class="caption">Actual experiment outputs. Shared budgets. Paired initialization seeds.</p><div class="evidence-layout"><div id="s4-figure" class="figure-wrap"><img class="figure" src="assets/discovery.png" alt="Measured multi-seed discovery curves under evaluation and cost budgets"></div><aside class="measurements"><div id="metric1" class="measurement"><strong>__TEST_COUNT__</strong><span>HELD-OUT CANDIDATES</span></div><div id="metric2" class="measurement"><strong>__SEEDS__</strong><span>PAIRED SEEDS</span></div><div id="metric3" class="measurement"><strong>__BUDGET__</strong><span>EVALUATION BUDGET</span></div><p id="s4-caution" class="caution">Results describe <span class="label-emphasis">one bounded WBM study.</span> Independent pretraining generalization is not established.</p></aside></div><div id="s4-foot" class="foot"><span>RETROSPECTIVE RESEARCH / NO NEW DFT OR SYNTHESIS</span><strong>OPEN SOURCE · REPRODUCIBLE RECORDS</strong></div></div></section>
<audio id="score" data-start="0" data-duration="20" data-track-index="10" data-volume="1" src="assets/score.wav"></audio>
</div>
<script>
window.__timelines = window.__timelines || {};
var tl = gsap.timeline({paused:true});
tl.from('#brand',{opacity:0,y:12,duration:.65,ease:'sine.out'},.1);
function shot(n,at){
 tl.from('#s'+n+'-label',{opacity:0,y:10,duration:.35,ease:'power2.out'},at+.12);
 tl.from('#s'+n+'-title',{opacity:0,y:19,duration:.5,ease:'power3.out'},at+.18);
 tl.from('#s'+n+'-screen',{opacity:0,scale:.985,duration:.65,ease:'sine.out'},at+.25);
 tl.from('#s'+n+'-foot',{opacity:0,y:7,duration:.4,ease:'power1.out'},at+.42);
}
// Container crossfades are the scene transitions. No content exits before them.
tl.to('#scene1',{opacity:0,duration:.55,ease:'sine.inOut'},3.6);
tl.to('#scene2',{opacity:1,duration:.55,ease:'sine.inOut'},3.6);
shot(2,3.6);
tl.to('#s2-screen .screen',{scale:1.012,duration:5.2,ease:'none'},4.5);
tl.to('#scene2',{opacity:0,duration:.55,ease:'sine.inOut'},9.6);
tl.to('#scene3',{opacity:1,duration:.55,ease:'sine.inOut'},9.6);
shot(3,9.6);
tl.to('#s3-screen .screen',{scale:1.008,duration:4.1,ease:'none'},10.5);
tl.to('#scene3',{opacity:0,duration:.55,ease:'sine.inOut'},14.6);
tl.to('#scene4',{opacity:1,duration:.55,ease:'sine.inOut'},14.6);
tl.from('#s4-label',{opacity:0,y:10,duration:.35,ease:'power2.out'},14.72);
tl.from('#s4-title',{opacity:0,y:19,duration:.5,ease:'power3.out'},14.78);
tl.from('#s4-caption',{opacity:0,y:8,duration:.45,ease:'sine.out'},14.92);
tl.from('#s4-figure',{opacity:0,scale:.99,duration:.65,ease:'power1.out'},15.05);
tl.from('#metric1',{opacity:0,x:15,duration:.4,ease:'power2.out'},15.15);
tl.from('#metric2',{opacity:0,x:15,duration:.4,ease:'power3.out'},15.28);
tl.from('#metric3',{opacity:0,x:15,duration:.4,ease:'sine.out'},15.4);
tl.from('#s4-caution',{opacity:0,y:7,duration:.45,ease:'power1.out'},15.5);
tl.from('#s4-foot',{opacity:0,y:7,duration:.4,ease:'power1.out'},15.5);
window.__timelines.main = tl;
</script></body></html>'''
html = html.replace('__TEST_COUNT__', str(summary['counts']['test'])).replace('__SEEDS__', str(summary['n_seeds'])).replace('__BUDGET__', str(summary['budget']))
(HERE / 'composition/index.html').write_text(html)
print('Composition built from verified file inputs', manifest)
