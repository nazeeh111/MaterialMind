"""Source-derived initial-cell orthographic projection, interval and query arithmetic."""
from pathlib import Path
import json,math,html,itertools
P=Path(__file__).parent
before=json.loads((P/'before.json').read_text());reveal=json.loads((P/'reveal.json').read_text());sid=reveal['results'][0]['id'];r=next(r for r in before['candidates']if r['id']==sid);p=r['prediction'];ref=reveal['results'][0]['e_above_hull'];st=r['structure'];palette={'Pa':'#d4b27c','Mn':'#bba2d6','F':'#a8d5b3'}
assert abs((p['p_stable']+.2*p['novelty'])/p['relative_cost']**.5-p['acquisition'])<1e-12
assert ref>p['upper'] and ref<0
# Orthonormal camera basis, common physical scale for all atoms and cell edges.
e1=(1/math.sqrt(2),-1/math.sqrt(2),0);e2=(1/math.sqrt(6),1/math.sqrt(6),-2/math.sqrt(6))
def cart(f):return [sum(f[i]*st['lattice'][i][j]for i in range(3))for j in range(3)]
def proj(v):return [sum(a*b for a,b in zip(v,e))for e in(e1,e2)]
corners=list(itertools.product((0,1),repeat=3));xy=[proj(cart(c))for c in corners];edges=[(i,j)for i in range(8)for j in range(i+1,8)if sum(a!=b for a,b in zip(corners[i],corners[j]))==1]
def make(mobile):
 W,H=(420,1010)if mobile else(1160,680);o=[]
 def add(s):o.append(s)
 def text(x,y,s,size=16,color='#dbe5df',weight=400):add(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}">{html.escape(str(s))}</text>')
 def line(x,y,X,Y,c='#52676a',w=1):add(f'<line x1="{x:.8f}" y1="{y:.8f}" x2="{X:.8f}" y2="{Y:.8f}" stroke="{c}" stroke-width="{w}"/>')
 desc='PaMnF6 initial WBM unit cell, projected with an orthonormal camera basis. The pre-reveal model interval misses the archived DFT energy, while both energies remain below the fixed reference hull. The fitted score uses probability and novelty divided by the square root of relative cost, with zero explicit exploration weight. The volume-edited cell has geometry only, not a new stability prediction.'
 add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc"><title id="title">A confident query, an interval miss</title><desc id="desc">{desc}</desc><style>text{{font-family:Arial,"DejaVu Sans",sans-serif}}</style><rect width="100%" height="100%" fill="#121f25"/>')
 text(28,34,'MATERIALMIND / REFERENCE REPLAY',12,'#a8c6b7',600);text(28,72,'A confident query,',26 if mobile else 34,'#f3ead8',600);text(28,107,'an interval miss.',26 if mobile else 34,'#f3ead8',600)
 cx,cy,cw,ch=(28,145,364,230)if mobile else(28,150,395,285)
 scale=min((cw-70)/(max(v[0]for v in xy)-min(v[0]for v in xy)),(ch-70)/(max(v[1]for v in xy)-min(v[1]for v in xy)))
 mx=(min(v[0]for v in xy)+max(v[0]for v in xy))/2;my=(min(v[1]for v in xy)+max(v[1]for v in xy))/2
 def screen(v):q=proj(cart(v));return(cx+cw/2+(q[0]-mx)*scale,cy+ch/2-(q[1]-my)*scale)
 for i,j in edges:line(*screen(corners[i]),*screen(corners[j]),'#6f8687',1.4)
 for i,site in enumerate(st['sites']):
  x,y=screen(site['frac']);add(f'<circle data-site="{i}" cx="{x:.8f}" cy="{y:.8f}" r="{9 if site["element"]=="F"else 12}" fill="{palette[site["element"]]}" stroke="#121f25" stroke-width="2"/>')
 text(cx,cy+ch+22,f'{r["formula"]} · {r["nsites"]} sites · {r["spacegroup"]}',16,'#f3ead8',600);text(cx,cy+ch+45,'Initial cell, not a relaxed DFT geometry.',12,'#aabcb7')
 for i,(el,c)in enumerate(palette.items()):add(f'<circle cx="{cx+8+i*90}" cy="{cy+ch+66}" r="5" fill="{c}"/>');text(cx+20+i*90,cy+ch+71,el,13)
 ex,ey,ew=(28,490,364)if mobile else(480,180,640)
 text(ex,ey,'SIGNED DISTANCE TO FIXED DFT HULL',12,'#a8c6b7',600)
 lo,hi=-2.45,.1
 def X(v):return ex+(v-lo)/(hi-lo)*ew
 for val in(-2.4,-1.8,-1.2,-.6,0):line(X(val),ey+22,X(val),ey+155,'#30474b');text(X(val)-12,ey+178,f'{val:g}',12,'#aabcb7')
 line(X(0),ey+18,X(0),ey+155,'#d4b27c',2)
 line(X(p['lower']),ey+52,X(p['upper']),ey+52,'#a8d5b3',8);add(f'<circle data-value="mean" cx="{X(p["mean"]):.8f}" cy="{ey+52}" r="6" fill="#edf5ed"/>')
 add(f'<circle data-value="reference" cx="{X(ref):.8f}" cy="{ey+115}" r="7" fill="#d4b27c"/>')
 text(ex,ey+207,f'Model: {p["mean"]:.4f} eV/atom',15,'#dbe5df',600);text(ex,ey+232,f'90% interval [{p["lower"]:.4f}, {p["upper"]:.4f}]',13)
 text(ex,ey+258,f'Archived DFT: {ref:.6f} eV/atom',15,'#d4b27c',600)
 sy=ey+290;text(ex,sy,'Reference outside interval; both below zero.',13,'#d4b27c')
 qy=845 if mobile else 535
 text(28,qy,'WHY IT WAS RANKED FIRST',12,'#a8c6b7',600)
 text(28,qy+30,f'(0.9991 + 0.2 × 1.4587) / √1.0000 = {p["acquisition"]:.4f}',14 if mobile else 22,'#f3ead8',600)
 text(28,qy+57,'P(stable) + weighted novelty; zero exploration bonus.',12,'#aabcb7')
 text(28,qy+83,'Cost is a site-count proxy, not measured DFT time.',12,'#aabcb7')
 text(28,H-23,'Existing WBM DFT label. No new calculation or synthesis.',12,'#aabcb7');add('</svg>');(P/('query-mobile.svg'if mobile else'query.svg')).write_text(''.join(o))
make(False);make(True)
(P/'figure-data.json').write_text(json.dumps({'id':sid,'initial_structure':st,'pre_reveal_prediction':p,'archived_reference_ev_atom':ref,'orthonormal_camera_basis':[e1,e2],'cell_edges':edges,'reference_outside_interval':True,'acquisition_recomputed':(p['p_stable']+.2*p['novelty'])/math.sqrt(p['relative_cost'])},indent=2)+'\n')
