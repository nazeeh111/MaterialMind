import fs from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../materialmind/web/camera-fit.js',import.meta.url),'utf8');
const {crystalFit}=await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const dot=(a,b)=>a.reduce((s,x,i)=>s+x*b[i],0);
const normalize=a=>{const n=Math.hypot(...a);return a.map(v=>v/n)};
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
const dir=normalize([.95,.65,1.18]),right=normalize(cross([0,1,0],dir)),up=normalize(cross(dir,right));
for(const [name,dimensions] of [['ordinary',[5,5,5]],['elongated',[3,4,50]],['large imported',[90,60,120]]]){
 for(const aspect of [.5,1,2])test(`${name}, viewport aspect ${aspect}: padded cell remains in view`,()=>{
  const corners=[];for(const x of [-.5,.5])for(const y of [-.5,.5])for(const z of [-.5,.5])corners.push([x*dimensions[0],y*dimensions[1],z*dimensions[2]]);
  const padding=.65,distance=crystalFit(corners,padding,34,aspect),tanV=Math.tan(34*Math.PI/360);
  assert.ok(Number.isFinite(distance)&&distance>0);
  for(const p of corners){const depth=distance-dot(p,dir)-padding;assert.ok(depth>0);assert.ok((Math.abs(dot(p,right))+padding)/depth<=tanV*aspect);assert.ok((Math.abs(dot(p,up))+padding)/depth<=tanV);}
 });
}

function cornersOf(vectors){const corners=[];for(const a of [-.5,.5])for(const b of [-.5,.5])for(const c of [-.5,.5])corners.push([0,1,2].map(i=>a*vectors[0][i]+b*vectors[1][i]+c*vectors[2][i]));return corners;}
const pool=JSON.parse(fs.readFileSync(new URL('../materialmind/data/candidates.json',import.meta.url),'utf8')).candidates;
const selected=pool.find(c=>c.id==='wbm-3-33675');
const elongation=c=>{const l=c.structure.lattice.map(v=>Math.hypot(...v));return Math.max(...l)/Math.min(...l);};
const elongated=pool.filter(c=>c.split==='test').sort((a,b)=>elongation(b)-elongation(a))[0];
for(const c of [selected,elongated])test(`shipped ${c.id} lattice fits phone and desktop`,()=>{
  const corners=cornersOf(c.structure.lattice);
  for(const aspect of [.65,1.5]){
    const pad=.65,d=crystalFit(corners,pad,34,aspect),tanV=Math.tan(34*Math.PI/360);
    for(const p of corners){const depth=d-dot(p,dir)-pad;assert.ok(depth>0);assert.ok((Math.abs(dot(p,right))+pad)/depth<=tanV*aspect);assert.ok((Math.abs(dot(p,up))+pad)/depth<=tanV);}
  }
});

test('viewer resizes an untouched fit but preserves a user-adjusted view', async () => {
  const vm=await import('node:vm');
  let code=fs.readFileSync(new URL('../materialmind/web/crystal.js',import.meta.url),'utf8')
    .replace(/^import .*;\n/gm,'').replace('export function elementColor','function elementColor')
    .replace('export class CrystalViewer','globalThis.CrystalViewer = class CrystalViewer');
  const ctx=vm.createContext({THREE:{MathUtils:{degToRad:d=>d*Math.PI/180}},crystalFit});
  vm.runInContext(code,ctx);
  const viewer=Object.create(ctx.CrystalViewer.prototype),points=cornersOf(selected.structure.lattice);
  let lastDistance=0;
  viewer.available=true;viewer.container={clientWidth:900,clientHeight:600};viewer.fitCorners=points;viewer.fitPadding=.65;viewer.radius=12;
  viewer.renderer={setSize(){}};viewer.camera={fov:34,aspect:1,updateProjectionMatrix(){},position:{set(){return this},normalize(){return this},multiplyScalar(n){lastDistance=n;return this}}};
  viewer.controls={target:{set(){}},update(){}};viewer.render=()=>{};viewer.reset();
  const wide=lastDistance;viewer.container.clientWidth=480;viewer.resize();
  assert.ok(lastDistance>wide);assert.equal(viewer.camera.aspect,.8);
  for(const p of points){const depth=lastDistance-dot(p,dir)-.65;assert.ok((Math.abs(dot(p,right))+.65)/depth<=Math.tan(34*Math.PI/360)*.8);}
  viewer.autoFit=false;const userDistance=lastDistance;viewer.container.clientWidth=900;viewer.resize();
  assert.equal(lastDistance,userDistance);assert.equal(viewer.camera.aspect,1.5);
});
