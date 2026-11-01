import * as THREE from 'three';
import { OrbitControls } from './vendor/OrbitControls.js';

const PALETTE = {H:'#e4e9e4',Li:'#bb99d7',Na:'#a6b2e1',K:'#c59cdb',Mg:'#a4d3ad',Ca:'#b3d997',Sr:'#b8cc9a',Ba:'#bfcf87',Al:'#c4cbd2',Si:'#d5c4a6',P:'#e2b276',S:'#dfd58c',O:'#e19b89',F:'#a8d5b3',Cl:'#a2c99f',Br:'#c89983',I:'#c49fcf',Ti:'#c3c4d3',V:'#a4b8c1',Cr:'#a9c9bd',Mn:'#c5a8cd',Fe:'#dbad86',Co:'#9ab6d4',Ni:'#a0c7ab',Cu:'#d7ac7f',Zn:'#aebbc7',Zr:'#b4c4d5',Nb:'#b7c0d4',Mo:'#adbdcf',W:'#b3bdc5',C:'#8fa4a5',N:'#9fb9e0',B:'#d3b8aa',Pb:'#adabd1',Sn:'#b8c9c7',Bi:'#d3bdce',La:'#adccdd',Ce:'#c5c8dc'};
const COVALENT = {H:.31,Li:1.28,Na:1.66,K:2.03,Mg:1.41,Ca:1.76,Sr:1.95,Ba:2.15,Al:1.21,Si:1.11,P:1.07,S:1.05,O:.66,F:.57,Cl:1.02,Ti:1.60,V:1.53,Cr:1.39,Mn:1.39,Fe:1.32,Co:1.26,Ni:1.24,Cu:1.32,Zn:1.22,Zr:1.75,Nb:1.64,Mo:1.54,W:1.62,C:.76,N:.71,B:.84};
export function elementColor(element) {
  if (PALETTE[element]) return PALETTE[element];
  let h = 0; for(const c of element) h = (h*31+c.charCodeAt(0))%360;
  return `hsl(${h},30%,72%)`;
}
export class CrystalViewer {
  constructor(container) {
    this.container=container; this.available=false;
    try {
      this.renderer=new THREE.WebGLRenderer({antialias:true,alpha:true,preserveDrawingBuffer:true});
      this.renderer.setPixelRatio(Math.min(devicePixelRatio,2));
      this.renderer.setClearColor(0x14252b,0); this.renderer.outputColorSpace=THREE.SRGBColorSpace;
      this.renderer.toneMapping=THREE.ACESFilmicToneMapping; this.renderer.toneMappingExposure=1.5;
      container.appendChild(this.renderer.domElement);
      this.scene=new THREE.Scene(); this.camera=new THREE.PerspectiveCamera(34,1,.1,1000);
      this.scene.add(new THREE.AmbientLight(0xdde9e1,1.65));
      const key=new THREE.DirectionalLight(0xfff4df,3.7);key.position.set(5,8,7);this.scene.add(key);
      const fill=new THREE.DirectionalLight(0x86cbb8,1.8);fill.position.set(-8,-1,-3);this.scene.add(fill);
      const rim=new THREE.DirectionalLight(0xb8d2ec,2.2);rim.position.set(-4,4,-7);this.scene.add(rim);
      this.controls=new OrbitControls(this.camera,this.renderer.domElement);this.controls.enableDamping=false;
      this.controls.minDistance=2;this.controls.maxDistance=100;this.controls.enablePan=true;
      this.controls.addEventListener('change',()=>this.render());
      this.resizeObserver=new ResizeObserver(()=>this.resize());this.resizeObserver.observe(container);
      this.cellVisible=true;this.bondsVisible=true;this.available=true;
      container.addEventListener('keydown',e=>this.keyboard(e));
      this.resize();
    } catch(error) { console.warn('Crystal viewer unavailable',error);container.querySelector('.viewer-fallback').hidden=false; }
  }
  resize(){if(!this.available)return;const w=this.container.clientWidth,h=this.container.clientHeight;this.renderer.setSize(w,h,false);this.camera.aspect=w/Math.max(h,1);this.camera.updateProjectionMatrix();this.render();}
  render(){if(this.available)this.renderer.render(this.scene,this.camera);}
  disposeGroup(group){if(!group)return;group.traverse(obj=>{obj.geometry?.dispose();if(Array.isArray(obj.material))obj.material.forEach(x=>x.dispose());else obj.material?.dispose();});this.scene.remove(group);}
  setStructure(structure) {
    if(!this.available||!structure)return;
    this.disposeGroup(this.root);this.root=new THREE.Group();this.scene.add(this.root);
    this.cell=new THREE.Group();this.atoms=new THREE.Group();this.bonds=new THREE.Group();this.root.add(this.cell,this.atoms,this.bonds);
    const lattice=structure.lattice?.matrix||structure.lattice;
    if(!Array.isArray(lattice)||lattice.length!==3)return;
    const vectors=lattice.map(v=>new THREE.Vector3(...v));
    const cart=frac=>new THREE.Vector3().addScaledVector(vectors[0],frac[0]).addScaledVector(vectors[1],frac[1]).addScaledVector(vectors[2],frac[2]);
    const center=cart([.5,.5,.5]);const corners=[];
    for(let i=0;i<8;i++)corners.push(cart([i&1,(i>>1)&1,(i>>2)&1]));
    for(let i=0;i<8;i++)for(const bit of [1,2,4])if(!(i&bit)){
      const geometry=new THREE.BufferGeometry().setFromPoints([corners[i],corners[i|bit]]);
      this.cell.add(new THREE.Line(geometry,new THREE.LineBasicMaterial({color:0x9db8a5,transparent:true,opacity:.38})));}
    // Only periodic boundary images are shown. All positions derive from the CIF lattice.
    const positions=[];const sites=structure.sites||[];
    sites.forEach(site=>{
      const frac=site.frac||site.abc||site.fractional_coordinates;
      const element=site.element||site.label||site.species?.[0]?.element||'X';
      if(!frac||frac.length!==3)return;
      const wrapped=frac.map(x=>((x%1)+1)%1);
      const shifts=wrapped.map(x=>x<1e-5?[0,1]:x>1-1e-5?[-1,0]:[0]);
      for(const i of shifts[0])for(const j of shifts[1])for(const k of shifts[2])positions.push({element,p:cart([wrapped[0]+i,wrapped[1]+j,wrapped[2]+k])});
    });
    const size=new THREE.Box3().setFromPoints(corners).getSize(new THREE.Vector3());
    const maxAtom=Math.max(.24,Math.min(.65,size.length()*.055));
    positions.slice(0,2000).forEach(({element,p})=>{
      const radius=Math.min(maxAtom,Math.max(.19,(COVALENT[element]||1.3)*.30));
      const mesh=new THREE.Mesh(new THREE.SphereGeometry(radius,24,18),new THREE.MeshStandardMaterial({color:elementColor(element),metalness:.15,roughness:.27}));mesh.position.copy(p);this.atoms.add(mesh);
    });
    // Distance contacts are a visual aid, not inferred chemical bond orders.
    if(positions.length<=320){for(let i=0;i<positions.length;i++)for(let j=i+1;j<positions.length;j++){
      const a=positions[i],b=positions[j],d=a.p.distanceTo(b.p);
      if(d>.6&&d<Math.min(3.1,1.15*((COVALENT[a.element]||1.25)+(COVALENT[b.element]||1.25)))){
        const geo=new THREE.CylinderGeometry(.026,.026,d,8);
        const mesh=new THREE.Mesh(geo,new THREE.MeshStandardMaterial({color:0x8cafa1,transparent:true,opacity:.24,roughness:.8}));
        mesh.position.copy(a.p).add(b.p).multiplyScalar(.5);mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),b.p.clone().sub(a.p).normalize());this.bonds.add(mesh);
      }
    }}
    this.root.position.copy(center).multiplyScalar(-1);this.cell.visible=this.cellVisible;this.bonds.visible=this.bondsVisible;
    this.radius=Math.max(2,size.length()*.5+maxAtom);this.reset();this.render();
    const els=[...new Set(positions.map(x=>x.element))].join(', ');
    this.container.setAttribute('aria-label',`Interactive initial crystal with ${sites.length} sites: ${els}. Drag to orbit, scroll to zoom. Arrow keys rotate; plus and minus zoom.`);
  }
  reset(){if(!this.available)return;const radius=this.radius||5;const vertical=THREE.MathUtils.degToRad(this.camera.fov/2);const horizontal=Math.atan(Math.tan(vertical)*this.camera.aspect);const distance=radius/Math.sin(Math.min(vertical,horizontal))*1.12;this.camera.near=Math.max(.01,radius*.001);this.camera.far=distance*12+radius;this.camera.updateProjectionMatrix();this.controls.minDistance=Math.max(.1,radius*.1);this.controls.maxDistance=distance*8;this.camera.position.set(.95,.65,1.18).normalize().multiplyScalar(distance);this.controls.target.set(0,0,0);this.controls.update();this.render();}
  toggleCell(){this.cellVisible=!this.cellVisible;if(this.cell)this.cell.visible=this.cellVisible;this.render();return this.cellVisible;}
  toggleBonds(){this.bondsVisible=!this.bondsVisible;if(this.bonds)this.bonds.visible=this.bondsVisible;this.render();return this.bondsVisible;}
  keyboard(e){if(!this.available)return;const v=this.camera.position.clone().sub(this.controls.target);const q=new THREE.Quaternion();let handled=true;
    if(e.key==='ArrowLeft'||e.key==='ArrowRight'){q.setFromAxisAngle(new THREE.Vector3(0,1,0),e.key==='ArrowLeft'?.12:-.12);v.applyQuaternion(q);}
    else if(e.key==='ArrowUp'||e.key==='ArrowDown'){const right=new THREE.Vector3().crossVectors(v,this.camera.up).normalize();q.setFromAxisAngle(right,e.key==='ArrowUp'?.12:-.12);v.applyQuaternion(q);}
    else if(e.key==='+'||e.key==='=')v.multiplyScalar(.9);else if(e.key==='-')v.multiplyScalar(1.1);else if(e.key==='0'){this.reset();e.preventDefault();return;}else handled=false;
    if(handled){e.preventDefault();this.camera.position.copy(this.controls.target).add(v);this.controls.update();this.render();}}
}
