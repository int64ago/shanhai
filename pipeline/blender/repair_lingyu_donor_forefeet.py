"""Bounded Xingtian High forefoot transplant, preserving native GLB attribute bytes.
Run with Blender --background --factory-startup --python THIS -- [--probe] OUTDIR.
Only the distal toe-side of each Lingyu metatarsal is replaced. No rig or API.
"""
import sys,json,struct,hashlib,copy,math
from pathlib import Path
import numpy as np
import bpy
ROOT=Path(__file__).resolve().parents[2]
SRC=ROOT/'raw/lingyu-production-20261115-corrected-human-limbs-v12-high/base_high_pbr.glb'
DONOR=ROOT/'raw/xingtian-production-20261115-closed-grip-whole-v7-high/base_high_pbr.glb'
EXPECTED=['214672b66577aec8fe33badb95e91c500c92fde72aa7298e4e8765237e5ed308','7b8f311778d006197a22113b397193a651d66fb3a2de9801d1da2ede32622cc8']
args=sys.argv[sys.argv.index('--')+1:];out=Path(args[-1]).resolve();probe='--probe' in args
assert out.is_relative_to(ROOT/'raw/_build');out.mkdir(parents=True,exist_ok=False)
def sha(b):return hashlib.sha256(b).hexdigest()
def load(path):
 b=path.read_bytes();n=struct.unpack_from('<I',b,12)[0];g=json.loads(b[20:20+n]);return g,bytearray(b[28+n:]),sha(b)
g,blob,sourcehash=load(SRC);dg,db,donorhash=load(DONOR);assert [sourcehash,donorhash]==EXPECTED
originalblob=bytes(blob);original=copy.deepcopy(g)
def array(g,b,idx):
 a=g['accessors'][idx];v=g['bufferViews'][a['bufferView']];dtype={5126:'<f4',5125:'<u4',5123:'<u2'}[a['componentType']];width={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']];return np.frombuffer(b,dtype=dtype,count=a['count']*width,offset=v.get('byteOffset',0)+a.get('byteOffset',0)).reshape(-1,width).copy()
p=g['meshes'][0]['primitives'][0];dp=dg['meshes'][0]['primitives'][0]
P=array(g,blob,p['attributes']['POSITION']);N=array(g,blob,p['attributes']['NORMAL']);UV=array(g,blob,p['attributes']['TEXCOORD_0']);F=array(g,blob,p['indices']).reshape(-1,3)
D=array(dg,db,dp['attributes']['POSITION']);DN=array(dg,db,dp['attributes']['NORMAL']);DUV=array(dg,db,dp['attributes']['TEXCOORD_0']);DF=array(dg,db,dp['indices']).reshape(-1,3)
Dworld=D.copy()
# The accepted donor foot splays outward ~31 degrees; align only its local frame.
yaw=math.radians(31);R=np.array([[math.cos(yaw),0,-math.sin(yaw)],[0,1,0],[math.sin(yaw),0,math.cos(yaw)]])
D=D@R.T;DN=DN@R.T
def boundary(points,faces):
 # Weld UV seams for topology only; retain native exported IDs in output.
 canon={};ids=[]
 for i,v in enumerate(points):
  key=tuple(np.round(v,6));ids.append(canon.setdefault(key,i))
 ids=np.array(ids);edges={}
 for f in faces:
  for a,b in zip(f,np.roll(f,-1)):
   ca,cb=int(ids[a]),int(ids[b]);key=tuple(sorted((ca,cb)))
   if ca!=cb:edges.setdefault(key,[]).append((ca,cb,int(a),int(b)))
 outer=[v[0] for v in edges.values() if len(v)==1];adj={}
 for a,b,ia,ib in outer:
  assert a not in adj,('branched cut',a);adj[a]=(b,ia,ib)
 loops=[]
 while adj:
  start=next(iter(adj));cur=start;loop=[]
  while True:
   nxt,ia,ib=adj.pop(cur);loop.append(ia);cur=nxt
   if cur==start:break
  loops.append(np.array(loop))
 return loops
cent=P[F].mean(axis=1);dc=D[DF].mean(axis=1)
# glTF frame: +Y height, +Z forward. Cut is well ahead of arch/heel/ankle.
cut=-.012
masks=[(P[F,2].max(axis=1)>cut)&(cent[:,1]<-.435)&(cent[:,0]*s>.065)&(cent[:,0]*s<.24) for s in [-1,1]]
# Split only triangles crossing the exact local plane. Their rear portions keep
# interpolated native UV/PBR; every full triangle behind it remains byte exact.
pp=P.tolist();nn=N.tolist();uu=UV.tolist();cache={};fronts=[];rear=[]
def intersection(a,b):
 key=tuple(sorted((int(a),int(b))))
 if key not in cache:
  t=(cut-pp[a][2])/(pp[b][2]-pp[a][2]);v=np.asarray(pp[a])*(1-t)+np.asarray(pp[b])*t;v[2]=cut;n=np.asarray(nn[a])*(1-t)+np.asarray(nn[b])*t;n/=np.linalg.norm(n);uv=np.asarray(uu[a])*(1-t)+np.asarray(uu[b])*t;cache[key]=len(pp);pp.append(v.tolist());nn.append(n.tolist());uu.append(uv.tolist())
 return cache[key]
def clip(face,front):
 result=[]
 for a,b in zip(np.roll(face,1),face):
  inside_a=(pp[a][2]>=cut) if front else (pp[a][2]<=cut);inside_b=(pp[b][2]>=cut) if front else (pp[b][2]<=cut)
  if inside_a!=inside_b:result.append(intersection(a,b))
  if inside_b:result.append(int(b))
 return [(result[0],result[i],result[i+1]) for i in range(1,len(result)-1)]
for mask in masks:
 front=[]
 for face in F[mask]:
  front.extend(clip(face,True));rear.extend(clip(face,False))
 fronts.append(np.asarray(front))
P=np.asarray(pp,dtype=np.float32);N=np.asarray(nn,dtype=np.float32);UV=np.asarray(uu,dtype=np.float32)
worlddc=Dworld[DF].mean(axis=1)
dmask=(D[DF,2].max(axis=1)>.22)&(dc[:,1]<-.82)&(worlddc[:,0]>.18)&(worlddc[:,0]<.5)
cut=.22;pp=D.tolist();nn=DN.tolist();uu=DUV.tolist();cache={};dfaces=[]
for face in DF[dmask]:dfaces.extend(clip(face,True))
D=np.asarray(pp);DN=np.asarray(nn);DUV=np.asarray(uu);dfaces=np.asarray(dfaces)
dloops=boundary(D,dfaces);assert len(dloops)==1,[(len(x),D[x].min(0).tolist(),D[x].max(0).tolist()) for x in dloops];dl=dloops[0]
report={'status':'PROBE' if probe else 'CANDIDATE_PENDING_ACTUAL_IMAGE_REVIEW','sourceSha256':sourcehash,'donorSha256':donorhash,'frame':'glTF +Y up +Z forward','donorCut':{'footFrameYawDegrees':31,'footFrameZGreaterThan':.22,'heightLessThan':-.82,'nativeXRange':[.18,.5]},'sourceCut':{'zGreaterThan':-.012,'heightLessThan':-.435,'absoluteXRange':[.065,.24]},'removedFaces':[],'donorFaces':len(dfaces),'donorLoopVertices':len(dl),'riggingStarted':False,'apiCalls':0,'localMirrorOnly':True,'feet':[]}
loops=[]
for s,mask in zip([-1,1],masks):
 ls=boundary(P,fronts[len(loops)]);assert len(ls)==1,[len(x) for x in ls];loop=ls[0];loops.append(loop)
 report['removedFaces'].append(int(mask.sum()));report['feet'].append({'side':s,'sourceLoopVertices':len(loop),'sourceLoopMin':P[loop].min(0).tolist(),'sourceLoopMax':P[loop].max(0).tolist()})
report['donorLoopMin']=D[dl].min(0).tolist();report['donorLoopMax']=D[dl].max(0).tolist()
if probe:
 json.dump(report,open(out/'probe.json','w'),indent=2);print(json.dumps(report,indent=2));sys.exit()
def append_view(data,target=None):
 while len(blob)%4:blob.append(0)
 idx=len(g['bufferViews']);v={'buffer':0,'byteOffset':len(blob),'byteLength':len(data)}
 if target:v['target']=target
 g['bufferViews'].append(v);blob.extend(data);return idx
def accessor(a,kind,component=5126):
 a=np.asarray(a,dtype='<f4' if component==5126 else '<u4');view=append_view(a.tobytes(),34963 if kind=='SCALAR' else 34962);idx=len(g['accessors']);v={'bufferView':view,'componentType':component,'count':len(a),'type':kind}
 if kind=='VEC3':v.update(min=a.min(0).tolist(),max=a.max(0).tolist())
 g['accessors'].append(v);return idx
def append_primitive(pos,nor,uv,faces,material,color=None):
 attrs={'POSITION':accessor(pos,'VEC3'),'NORMAL':accessor(nor,'VEC3'),'TEXCOORD_0':accessor(uv,'VEC2')}
 if color is not None:attrs['COLOR_0']=accessor(color,'VEC4')
 g['meshes'][0]['primitives'].append({'attributes':attrs,'indices':accessor(np.asarray(faces).reshape(-1,1),'SCALAR',5125),'material':material,'mode':4})
def image(gx,bx,index,label):
 im=gx['images'][index];v=gx['bufferViews'][im['bufferView']];path=out/(label+'.png');path.write_bytes(bytes(bx[v.get('byteOffset',0):v.get('byteOffset',0)+v['byteLength']]));im=bpy.data.images.load(str(path),check_existing=False);pix=np.array(im.pixels[:],dtype=float).reshape(im.size[1],im.size[0],4);return pix
sourcepix=image(original,originalblob,1,'source-diffuse-audit');donorpix=image(dg,db,1,'donor-diffuse-audit')
sourcemr=image(original,originalblob,2,'source-mr-audit');donormr=image(dg,db,2,'donor-mr-audit')
def sample(pix,uv,linearize=True):
 # Blender pixel arrays start at lower left, glTF UV starts at upper left.
 h,w=pix.shape[:2];x=np.clip((uv[:,0]*w).astype(int),0,w-1);y=np.clip(((1-uv[:,1])*h).astype(int),0,h-1);rgb=pix[y,x,:3];return np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4) if linearize else rgb
# Copy native donor normal/base/MR textures and material without touching source images.
texture_offset=len(g.get('textures',[]));image_offset=len(g.get('images',[]));sampler_offset=len(g.get('samplers',[]))
g.setdefault('samplers',[]).extend(copy.deepcopy(dg.get('samplers',[])))
for im in dg['images']:
 v=dg['bufferViews'][im['bufferView']];ni=copy.deepcopy(im);ni['bufferView']=append_view(bytes(db[v.get('byteOffset',0):v.get('byteOffset',0)+v['byteLength']]));g['images'].append(ni)
for tex in dg['textures']:
 nt=copy.deepcopy(tex);nt['source']+=image_offset
 if 'sampler' in nt:nt['sampler']+=sampler_offset
 g['textures'].append(nt)
dmat=copy.deepcopy(dg['materials'][0]);dmat['name']='Xingtian_actual_High_local_forefoot_PBR'
for parent,key in [(dmat,'normalTexture'),(dmat['pbrMetallicRoughness'],'baseColorTexture'),(dmat['pbrMetallicRoughness'],'metallicRoughnessTexture')]:parent[key]['index']+=texture_offset
dmi=len(g['materials']);g['materials'].append(dmat)
bmi=len(g['materials']);g['materials'].append({'name':'Local_stitched_skin_color_transition','doubleSided':True,'pbrMetallicRoughness':{'baseColorFactor':[1,1,1,1],'metallicFactor':0,'roughnessFactor':.65}})
keep=~(masks[0]|masks[1]);p['indices']=accessor(F[keep].reshape(-1,1),'SCALAR',5125)
rear=np.asarray(rear);rear_used=np.unique(rear);rear_map=np.full(len(P),-1);rear_map[rear_used]=np.arange(len(rear_used));append_primitive(P[rear_used],N[rear_used],UV[rear_used],rear_map[rear],0)
def normalize(a):return a/np.maximum(np.linalg.norm(a,axis=-1,keepdims=True),1e-10)
def ordered(points,loop,desired=None):
 center=(points[loop,:2].min(0)+points[loop,:2].max(0))*.5;q=points[loop,:2]-center;area=np.sum(q[:,0]*np.roll(q[:,1],-1)-q[:,1]*np.roll(q[:,0],-1));direction=1 if area>0 else -1
 if desired is not None and direction!=desired:loop=loop[::-1];direction=desired
 q=(points[loop,:2]-center)/np.maximum(np.ptp(points[loop,:2],axis=0),1e-8);start=int(np.argmin(np.abs(np.arctan2(q[:,1],q[:,0]))));lp=np.roll(loop,-start);q=np.roll(q,-start,axis=0);length=np.linalg.norm(np.roll(q,-1,axis=0)-q,axis=1);t=np.r_[0,np.cumsum(length[:-1])]/length.sum();return lp,t,direction
for j,(s,sl) in enumerate(zip([-1,1],loops)):
 used=np.unique(dfaces);remap=np.full(len(D),-1);remap[used]=np.arange(len(used));pos=D[used].astype(float);nor=DN[used].astype(float);uv=DUV[used].copy();faces=remap[dfaces].copy();dloop=remap[dl]
 sourcecenter=(P[sl].min(0)+P[sl].max(0))*.5;donorcenter=(pos[dloop].min(0)+pos[dloop].max(0))*.5
 span=P[sl].max(0)-P[sl].min(0);dspan=pos[dloop].max(0)-pos[dloop].min(0)
 scales=np.array([span[0]/dspan[0]*.98,span[1]/dspan[1]*.92,.46]);scales[0]*=s
 target=sourcecenter.copy();target[2]=.008
 pos=(pos-donorcenter)*scales+target;nor=normalize(nor/scales)
 if s<0:faces=faces[:,[0,2,1]] # Offline reflection: corrected winding, positive node scale.
 # Feather a local donor albedo tint toward the existing Lingyu skin at root.
 src_color=sample(sourcepix,UV[sl]).mean(0);don_color=sample(donorpix,uv[dloop]).mean(0);ratio=np.clip(src_color/np.maximum(don_color,.001),.04,1)
 fade=np.clip((pos[:,2]-.008)/.065,0,1);factor=ratio[None,:]*(1-fade[:,None]*.15)
 colors=np.c_[factor,np.ones(len(pos))]
 sl,st,sd=ordered(P,sl);dloop,dt,dd=ordered(pos,dloop,sd)
 # Angle-based zipper uses native boundary vertices and creates no caps or overlap.
 sp=P[sl];sn=N[sl];sc=sample(sourcepix,UV[sl]);dp2=pos[dloop];dn2=nor[dloop];dc2=sample(donorpix,uv[dloop])*colors[dloop,:3]
 bp=[];bn=[];bc=[];bu=[];bf=[]
 def cyclic(values,t,newt):return np.stack([np.interp(newt,np.r_[t[-1]-1,t,t[0]+1],np.r_[values[-1,k],values[:,k],values[0,k]]) for k in range(values.shape[1])],axis=1)
 def addring(points,normals,cols,ts,v):
  ids=[]
  for a,n,c,t in zip(points,normals,cols,ts):ids.append(len(bp));bp.append(a);bn.append(n);bc.append((*c,1));bu.append((float(t),v))
  return np.array(ids),ts
 ringlist=[addring(sp,sn,sc,st,0)]
 ts=np.arange(128)/128
 for alpha in [.25,.5,.75]:
  a=cyclic(sp,st,ts);b=cyclic(dp2,dt,ts);na=normalize(cyclic(sn,st,ts));nb=normalize(cyclic(dn2,dt,ts));nn=normalize(na*(1-alpha)+nb*alpha);cc=cyclic(sc,st,ts)*(1-alpha)+cyclic(dc2,dt,ts)*alpha
  def tangent(n):
   t=np.tile([0.,0.,1.],(len(n),1))-n*n[:,2,None];t/=np.maximum(t[:,2,None],.1);t[:,:2]=np.clip(t[:,:2],-.8,.8);return t
  length=(b[:,2]-a[:,2])[:,None];ma=tangent(na)*length;mb=tangent(nb)*length;t=alpha
  positions=(2*t**3-3*t*t+1)*a+(t**3-2*t*t+t)*ma+(-2*t**3+3*t*t)*b+(t**3-t*t)*mb
  ringlist.append(addring(positions,nn,cc,ts,alpha))
 ringlist.append(addring(dp2,dn2,dc2,dt,1))
 for (aa,at),(bb,bt) in zip(ringlist,ringlist[1:]):
  ia=ib=0
  while ia<len(aa) or ib<len(bb):
   av=at[(ia+1)%len(aa)]+((ia+1)//len(aa));bv=bt[(ib+1)%len(bb)]+((ib+1)//len(bb))
   if ia<len(aa) and (ib==len(bb) or av<bv):bf.append((aa[ia%len(aa)],aa[(ia+1)%len(aa)],bb[ib%len(bb)]));ia+=1
   else:bf.append((aa[ia%len(aa)],bb[(ib+1)%len(bb)],bb[ib%len(bb)]));ib+=1
 # Duplicate only bridge UV seam corners so wrap triangles do not cross the atlas.
 for fi,face in enumerate(bf):
  if np.ptp([bu[i][0] for i in face])>.5:
   corners=[]
   for i in face:
    if bu[i][0]<.5:
     corners.append(len(bp));bp.append(bp[i]);bn.append(bn[i]);bc.append(bc[i]);bu.append((bu[i][0]+1,bu[i][1]))
    else:corners.append(i)
   bf[fi]=tuple(corners)
 rounded=np.round(pos,6);valid=np.array([len({tuple(rounded[i]) for i in f})==3 for f in faces]);faces=faces[valid]
 # Bake only the bridge's metallic/roughness gradient into its own local UV strip.
 smr=cyclic(sample(sourcemr,UV[sl],False),st,np.linspace(0,1,256));dmr=cyclic(sample(donormr,uv[dloop],False),dt,np.linspace(0,1,256));pixels=np.ones((32,256,4),dtype=np.float32)
 for row in range(32):
  t=1-row/31;pixels[row,:,:3]=smr*(1-t)+dmr*t
 im=bpy.data.images.new('Local_bridge_MR',width=256,height=32,alpha=True);im.colorspace_settings.name='Non-Color';im.pixels.foreach_set(pixels.ravel());im.file_format='PNG';im.filepath_raw=str(out/f'bridge_{s:+d}_mr.png');im.save()
 vi=append_view(Path(im.filepath_raw).read_bytes());image_idx=len(g['images']);g['images'].append({'bufferView':vi,'mimeType':'image/png'});texture_idx=len(g['textures']);g['textures'].append({'source':image_idx});bm=copy.deepcopy(g['materials'][bmi]);bm['name']+=f'_{s:+d}';bm['pbrMetallicRoughness'].update(metallicRoughnessTexture={'index':texture_idx},roughnessFactor=1,metallicFactor=1);bridge_mat=len(g['materials']);g['materials'].append(bm)
 append_primitive(pos,nor,uv,faces,dmi,colors);append_primitive(bp,bn,bu,bf,bridge_mat,bc)
 report['feet'][j].update(removedDonorCollapsedTriangles=int((~valid).sum()),donorScale=scales.tolist(),donorTranslationTarget=target.tolist(),newToeBounds={'min':pos.min(0).tolist(),'max':pos.max(0).tolist()},donorNativeTriangles=len(faces),bridgeTriangles=len(bf),sourceLoopIndices=sl.tolist(),donorAlbedoRatio=ratio.tolist())
# Preserve original bytes and attribute accessors, including original UVs/normals.
assert bytes(blob[:len(originalblob)])==originalblob
for key,idx in original['meshes'][0]['primitives'][0]['attributes'].items():assert g['accessors'][idx]==original['accessors'][idx]
assert g['materials'][0]==original['materials'][0] and g['images'][:3]==original['images']
report['protectedAudit']={'originalBinaryPrefixByteIdentical':True,'originalAttributeAccessorsIdentical':True,'originalPositionNormalUvBytesIdentical':True,'protectedTrianglesOriginalIndicesAndWindingIdentical':True,'protectedTriangles':int(keep.sum()),'removedTriangleIds':np.flatnonzero(~keep).tolist(),'originalMaterialsImagesIdentical':True,'originalBinarySha256':sha(originalblob),'protectedIndexSha256':sha(F[keep].tobytes()),'bridgeTopology':'Arc-length zipper across planar native section loops, three Hermite tangent rings; clipped rear triangle fragments retain native UVs and normals.','pbrTransition':'Native donor UV/normal/metallic-roughness maps retained; local linear diffuse vertex factors blend to sampled Lingyu root colors; bridge carries sampled linear colors and a local metallic/roughness gradient UV strip. No global texture edits.'}
g['buffers'][0]['byteLength']=len(blob)
while len(blob)%4:blob.append(0)
jb=json.dumps(g,separators=(',',':')).encode();jb+=b' '*((-len(jb))%4);b=struct.pack('<4sII',b'glTF',2,28+len(jb)+len(blob))+struct.pack('<II',len(jb),0x4e4f534a)+jb+struct.pack('<II',len(blob),0x004e4942)+blob
candidate=out/'lingyu-donor-forefeet.glb';candidate.write_bytes(b);report['candidateSha256']=sha(b);report['candidateTriangles']=int(keep.sum()+len(rear)+sum(f['donorNativeTriangles']+f['bridgeTriangles'] for f in report['feet']));json.dump(report,open(out/'patch-audit.json','w'),indent=2)
assert sha(SRC.read_bytes())==sourcehash and sha(DONOR.read_bytes())==donorhash
print('EXPORTED',candidate,report['candidateTriangles'])
