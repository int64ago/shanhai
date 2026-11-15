"""Independent GLB byte/index protection and geometric-edge audit (stdlib only).
python3 -I THIS CANDIDATE_DIR. Does not import or alter meshes.
"""
import json,struct,hashlib,collections,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
out=Path(sys.argv[1]).resolve();assert out.is_relative_to(ROOT/'raw/_build')
source=ROOT/'raw/lingyu-production-20261115-corrected-human-limbs-v12-high/base_high_pbr.glb'
candidate=out/'lingyu-donor-forefeet.glb'
def read(path):
 b=path.read_bytes();n=struct.unpack_from('<I',b,12)[0];g=json.loads(b[20:20+n]);return g,b[28+n:]
def arr(g,b,idx):
 a=g['accessors'][idx];v=g['bufferViews'][a['bufferView']];k={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']];fmt={5126:'f',5125:'I',5123:'H'}[a['componentType']];off=v.get('byteOffset',0)+a.get('byteOffset',0);return list(struct.iter_unpack('<'+k*fmt,b[off:off+struct.calcsize(fmt)*k*a['count']]))
def topology(g,b,primitives=None):
 vertices=[];faces=[]
 for p in primitives if primitives is not None else g['meshes'][0]['primitives']:
  offset=len(vertices);vertices.extend(arr(g,b,p['attributes']['POSITION']));ii=[x[0]+offset for x in arr(g,b,p['indices'])];faces.extend(zip(ii[::3],ii[1::3],ii[2::3]))
 canonical={};ids=[canonical.setdefault(tuple(round(c,6) for c in v),len(canonical)) for v in vertices];edges=collections.Counter();directed=collections.Counter();degenerate=0
 for f in faces:
  a,c,d=[ids[i] for i in f]
  if len({a,c,d})<3:degenerate+=1
  for x,y in [(a,c),(c,d),(d,a)]:edges[tuple(sorted((x,y)))]+=1;directed[x,y]+=1
 return {'triangles':len(faces),'boundaryEdges':sum(v==1 for v in edges.values()),'nonmanifoldEdges':sum(v>2 for v in edges.values()),'opposedWindingFailures':sum(1 for a,c in edges if edges[a,c]==2 and (directed[a,c]!=1 or directed[c,a]!=1)),'degenerateAt1e6CoordinateWeld':degenerate,'coordinateWeldDecimals':6}
g,b=read(source);cg,cb=read(candidate);patch=json.loads((out/'patch-audit.json').read_text());p=g['meshes'][0]['primitives'][0];cp=cg['meshes'][0]['primitives'][0]
assert cb[:len(b)]==b
assert p['attributes']==cp['attributes']
for idx in p['attributes'].values():assert g['accessors'][idx]==cg['accessors'][idx]
assert g['materials'][0]==cg['materials'][0] and g['images']==cg['images'][:len(g['images'])]
ii=[x[0] for x in arr(g,b,p['indices'])];faces=list(zip(ii[::3],ii[1::3],ii[2::3]));removed=set(patch['protectedAudit']['removedTriangleIds']);expected=[f for i,f in enumerate(faces) if i not in removed];ci=[x[0] for x in arr(cg,cb,cp['indices'])];actual=list(zip(ci[::3],ci[1::3],ci[2::3]));assert actual==expected
before=topology(g,b);after=topology(cg,cb);assert after['boundaryEdges']==before['boundaryEdges']==0
assert len(actual)==patch['protectedAudit']['protectedTriangles']
for key in ['nonmanifoldEdges','opposedWindingFailures','degenerateAt1e6CoordinateWeld']:assert after[key]<=before[key],(key,before[key],after[key])
result={'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),'candidateSha256':hashlib.sha256(candidate.read_bytes()).hexdigest(),'originalBinaryBytesIdentical':len(b),'nativeAttributeAccessorsIdentical':True,'protectedTriangleIndicesAndWindingIdentical':len(actual),'nativeMaterialAndImageReferencesIdentical':True,'before':before,'after':after,'topologyDelta':{k:after[k]-before[k] for k in before if k!='coordinateWeldDecimals'},'notes':'Native degenerate triangles remain in protected regions. No global welding, normals recomputation or source cleanup. All new geometry is local to the two distal forefeet.'}
(out/'independent-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
