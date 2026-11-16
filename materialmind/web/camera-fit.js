/* Fit the existing cell, not a replacement geometry, to a perspective viewport. */
const length = v => Math.hypot(...v);
const unit = v => {const n=length(v);return v.map(x=>x/n);};
const dot = (a,b) => a.reduce((s,x,i)=>s+x*b[i],0);
const cross = (a,b) => [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];

// `corners` are centered Cartesian coordinates; padding covers atom radii.
// The camera direction matches CrystalViewer.reset; a margin keeps all corners
// inside both fields of view, including narrow and highly elongated cells.
export function crystalFit(corners, padding, fovDegrees, aspect) {
  const direction=unit([.95,.65,1.18]);
  const right=unit(cross([0,1,0],direction));
  const up=unit(cross(direction,right));
  const tanV=Math.tan(fovDegrees*Math.PI/360);
  const tanH=tanV*Math.max(aspect,.05);
  const margin=1.12;
  let distance=0;
  for(const point of corners){
    const depth=dot(point,direction)+padding;
    distance=Math.max(distance,depth+margin*(Math.abs(dot(point,right))+padding)/tanH,
      depth+margin*(Math.abs(dot(point,up))+padding)/tanV);
  }
  return Math.max(distance,.1);
}
