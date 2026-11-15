"""Source-calibrated Lingyu aquatic rig; direct GLB skin/curve append preserves PBR.
Blender --background --python THIS -- PREPARED.glb OUTPUT.glb [--preview PATH]
No native position/UV/normal edits, no automatic/Medium landmark reuse.
"""
import sys,json,math,argparse
from functools import lru_cache
from pathlib import Path
import numpy as np
sys.dont_write_bytecode=True;sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare_lingyu import append,digest,glb,ACCEPTED_PATCH,SOURCE_SHA,DONOR_SHA
DURATIONS={'idle':6.,'walk':4.,'special':6.}
def smooth(x,a,b):
 t=np.clip((x-a)/(b-a),0,1);return t*t*(3-2*t)
def quat(x=0,y=0,z=0):
 # Tiny world-axis Euler rotations, xyzw quaternion, all rest bone axes identity.
 def mul(a,b):return np.r_[a[3]*b[:3]+b[3]*a[:3]+np.cross(a[:3],b[:3]),a[3]*b[3]-np.dot(a[:3],b[:3])]
 q=np.array([0.,0.,0.,1.])
 for axis,angle in enumerate([x,y,z]):
  v=np.zeros(4);v[axis]=math.sin(angle/2);v[3]=math.cos(angle/2);q=mul(q,v)
 return q

def main():
 parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('output',type=Path);parser.add_argument('--preview',type=Path);args=parser.parse_args(sys.argv[sys.argv.index('--')+1:]);source=args.source.resolve();output=args.output.resolve();output.parent.mkdir(parents=True,exist_ok=True)
 doc,data=glb.glb_read(source);binary=bytearray(data);prep=doc['extras']['lingyuPreparation'];assert prep['acceptedStaticPatchSha256']==ACCEPTED_PATCH and prep['sourceHighSha256']==SOURCE_SHA and prep['donorHighSha256']==DONOR_SHA
 prims=doc['meshes'][0]['primitives'];positions=[glb.accessor(doc,data,p['attributes']['POSITION']).astype(float) for p in prims];P=np.concatenate(positions);raw=(P-[0,prep['elevationM'],0])/prep['uniformScale']+prep['rawOrigin'];scale=prep['uniformScale'];origin=np.array(prep['rawOrigin'])
 def world(v):return (np.asarray(v)-origin)*scale+[0,prep['elevationM'],0]
 nodes=doc['nodes'];bones=[];rests=[];parents=[];names=[];landmarks={}
 def bone(name,rawpoint,parent=None):
  w=world(rawpoint);idx=len(nodes);translation=w-(rests[parent] if parent is not None else 0);nodes.append({'name':name,'translation':translation.tolist(),'rotation':[0,0,0,1],'scale':[1,1,1]});j=len(bones);bones.append(idx);rests.append(w);parents.append(parent);names.append(name)
  if parent is not None:nodes[bones[parent]].setdefault('children',[]).append(idx)
  landmarks[name]={'rawGltf':np.asarray(rawpoint).tolist(),'normalizedGltf':w.tolist()};return j
 core=(np.abs(raw[:,0])<.03)&(np.abs(raw[:,2])<.3)&(raw[:,1]>-.14)&(raw[:,1]<.3);root_y=float(np.median(raw[core,1]));root=bone('root',[0,root_y,0]);head=bone('whole_human_face',np.median(raw[raw[:,2]>.65],axis=0),root)
 axial=[]
 for i,z in enumerate(np.linspace(.30,-.91,16)):
  selected=(np.abs(raw[:,2]-z)<.04)&(raw[:,1]>-.14)&(raw[:,1]<.34)&(np.abs(raw[:,0])<.17);y=float(np.median(raw[selected,1])) if selected.any() else .04
  axial.append(bone(f'axial_{i:02}',[0,y,z],root if i==0 else axial[-1]))
 arm_bones={};leg_bones={};station_counts={}
 def station(side,y,region,label):
  chosen=(raw[:,0]*side>.06)&(np.abs(raw[:,1]-y)<.018)&region
  assert chosen.sum()>8,(side,y,label,int(chosen.sum()));station_counts[f'{label}_{side}']=int(chosen.sum());v=np.median(raw[chosen],axis=0);v[1]=y;return v
 for side in [-1,1]:
  arm_region=(raw[:,0]*side>.21)&(raw[:,2]>.34)
  shoulder=station(side,.11,arm_region&(raw[:,2]>.40),'shoulder');elbow=station(side,-.07,arm_region,'elbow');wrist=station(side,-.19,arm_region,'wrist')
  upper=bone(f'upper_arm_{side:+d}',shoulder,root);fore=bone(f'forearm_{side:+d}',elbow,upper);hand=bone(f'whole_hand_{side:+d}',wrist,fore);arm_bones[side]=(upper,fore,hand)
  leg_region=(raw[:,2]<-.035)&(raw[:,2]>-.28)
  hip=station(side,-.20,leg_region,'hip');knee=station(side,-.30,leg_region,'knee');ankle=station(side,-.435,leg_region&(raw[:,2]<-.12),'ankle')
  hip_parent=axial[int(np.argmin([abs(landmarks[names[j]]['rawGltf'][2]-hip[2]) for j in axial]))]
  thigh=bone(f'thigh_{side:+d}',hip,hip_parent);shin=bone(f'shin_{side:+d}',knee,thigh);foot=bone(f'whole_foot_{side:+d}',ankle,shin);leg_bones[side]=(thigh,shin,foot)
 assert len(bones)==30
 doc['scenes'][doc.get('scene',0)]['nodes'].append(bones[root]);doc['nodes'][0]['skin']=0
 inv=np.tile(np.eye(4),(len(bones),1,1));inv[:,:3,3]=-np.asarray(rests);doc['skins']=[{'name':'lingyu_calibrated_aquatic','joints':bones,'skeleton':bones[root],'inverseBindMatrices':append(doc,binary,inv.transpose(0,2,1).reshape(-1,16),'MAT4')}]
 def weights(r):
  count=len(r);w=np.zeros((count,len(bones)));stations=np.linspace(.30,-.91,16);coordinate=(.30-r[:,2])/(.30+.91)*15;coordinate=np.clip(coordinate,0,15);lo=np.floor(coordinate).astype(int);hi=np.minimum(lo+1,15);f=coordinate-lo
  for j in range(count):w[j,axial[lo[j]]]+=1-f[j];w[j,axial[hi[j]]]+=f[j]
  # axial_00 stays rigid with root, preserving the complete forebody/face join.
  # Two axial stations plus at most two limb stations fit exactly four influences.
  for side in [-1,1]:
   arm=smooth(r[:,0]*side,.18,.245)*smooth(r[:,2],.25,.34)*smooth(.60-r[:,2],0,.09)*smooth(.16-r[:,1],0,.09)
   arm=np.where((r[:,1]<-.215)&(r[:,0]*side>.24)&(r[:,2]>.3)&(r[:,2]<.58),1.,arm)
   elbow=smooth(-r[:,1],.035,.105);hand=smooth(-r[:,1],.17,.215);a,b,c=arm_bones[side];aw=np.zeros_like(w);aw[:,a]=1-elbow;aw[:,b]=elbow*(1-hand);aw[:,c]=elbow*hand;w=w*(1-arm[:,None])+aw*arm[:,None]
   leg=smooth(-r[:,1],.02,.245)*smooth(.045-r[:,2],0,.12)*smooth(r[:,2]+.40,0,.10)*smooth(r[:,0]*side,.035,.085)
   leg=np.where((r[:,1]<-.458)&(r[:,2]<.12)&(r[:,2]>-.28)&(r[:,0]*side>.045),1.,leg)
   knee=smooth(-r[:,1],.255,.325);foot=smooth(-r[:,1],.41,.458);a,b,c=leg_bones[side];lw=np.zeros_like(w);lw[:,a]=1-knee;lw[:,b]=knee*(1-foot);lw[:,c]=knee*foot;w=w*(1-leg[:,None])+lw*leg[:,None]
  face=r[:,2]>.61;w[face]=0;w[face,head]=1
  joints=np.argsort(w,axis=1)[:,-4:];values=np.take_along_axis(w,joints,axis=1);discarded=float(np.max(w.sum(1)-values.sum(1)));assert discarded<1e-8,discarded;values/=values.sum(1)[:,None];return joints,values
 all_joints=[];all_weights=[];cursor=0
 for index,(p,points) in enumerate(zip(prims,positions)):
  n=len(points);j,w=weights(raw[cursor:cursor+n]);cursor+=n;all_joints.append(j);all_weights.append(w);p['attributes']['JOINTS_0']=append(doc,binary,j,'VEC4',5123);p['attributes']['WEIGHTS_0']=append(doc,binary,w,'VEC4');p['extras']={'lingyuRegion':['protected_native','native_cut_fragments','donor_negative_x','bridge_negative_x','donor_positive_x','bridge_positive_x'][index]}
 all_joints=np.concatenate(all_joints);all_weights=np.concatenate(all_weights)
 @lru_cache(maxsize=8192)
 def pose(clip,t):
  duration=DURATIONS[clip];phase=2*math.pi*t/duration;env=math.sin(math.pi*t/6)**4 if clip=='special' else 0.;moving=clip=='walk';q={};translations={root:rests[root]+[0,.012*math.sin(phase)+.02*env,0]};q[root]=quat(y=.012*math.sin(phase)+.10*env*math.sin(phase))
  for i,j in enumerate(axial):
   f=i/15;amplitude=(.003+.005*f) if not moving else (.009+.011*f);angle=amplitude*math.sin(phase-i*.40)+env*(.008+.008*f)*math.sin(phase-i*.48);q[j]=quat(x=.002*f*math.sin(phase-i*.45),y=angle) if i>0 else quat()
  for side in [-1,1]:
   a,b,c=arm_bones[side];upper=(.025 if not moving else .045)*math.sin(phase+side*.7);fore=(.035 if not moving else .065)*math.sin(phase+side*.7+.5);q[a]=quat(x=upper,z=-side*.04*env);q[b]=quat(x=fore-.04*env);q[c]=quat(x=-.4*fore)
   a,b,c=leg_bones[side];thigh=(.015 if not moving else .035)*math.sin(phase+side*.8)+.05*env;shin=-.7*thigh;q[a]=quat(x=thigh,z=-side*.035*env);q[b]=quat(x=shin);q[c]=quat(x=-thigh-shin,z=side*.035*env)
  return q,translations
 doc['animations']=[]
 for clip,duration in DURATIONS.items():
  times=np.linspace(0,duration,int(duration*60)+1);time_acc=append(doc,binary,times[:,None],'SCALAR');animation={'name':clip,'samplers':[],'channels':[]}
  for joint,path in [(root,'translation')]+[(i,'rotation') for i in [root,*axial,*sum([list(v) for v in arm_bones.values()],[]),*sum([list(v) for v in leg_bones.values()],[])]]:
   def value(t):
    qs,ts=pose(clip,t);return ts[joint] if path=='translation' else qs[joint]
   values=np.asarray([value(t) for t in times]);h=1e-4;derivatives=np.asarray([(value(t+h)-value(t-h))/(2*h) for t in times]);values[-1]=values[0];derivatives[-1]=derivatives[0];triples=np.stack([derivatives,values,derivatives],axis=1);sampler=len(animation['samplers']);animation['samplers'].append({'input':time_acc,'output':append(doc,binary,triples.reshape(-1,3 if path=='translation' else 4),'VEC3' if path=='translation' else 'VEC4'),'interpolation':'CUBICSPLINE'});animation['channels'].append({'sampler':sampler,'target':{'node':bones[joint],'path':path}})
  doc['animations'].append(animation)
 contract={'beast':'lingyu','clips':DURATIONS,'supportMode':'Aquatic stationary swim: permanent 0.22m minimum rest elevation; no grounded stance, XZ root travel, footstep or circular runtime translation','completeFaceHandsAndForefeet':'single rigid bone per entire face/hand/foot, fingers and toe topology unchanged','sourceCalibratedLandmarks':landmarks,'stationCounts':station_counts,'boneCount':len(bones),'boneScale':1,'normalRecomputation':False,'runtimeAccepted':False,'sourcePreparedSha256':digest(source),'acceptedStaticPatchSha256':ACCEPTED_PATCH}
 doc['extras']['lingyuRig']=contract;glb.write_glb(output,doc,binary)
 masks={'face':np.flatnonzero(raw[:,2]>.65).tolist(),'body':np.flatnonzero((np.abs(raw[:,2])<.30)&(raw[:,1]>-.10)).tolist(),'tail':np.flatnonzero(raw[:,2]<-.55).tolist()}
 for side in [-1,1]:
  masks[f'hand_{side:+d}']=np.flatnonzero((raw[:,0]*side>.245)&(raw[:,1]<-.225)&(raw[:,2]>.32)).tolist();masks[f'foot_{side:+d}']=np.flatnonzero((raw[:,0]*side>.075)&(raw[:,1]<-.465)&(raw[:,2]<.12)&(raw[:,2]>-.26)).tolist()
 reference={'beast':'lingyu','sourceHighSha256':SOURCE_SHA,'donorHighSha256':DONOR_SHA,'acceptedStaticPatchSha256':ACCEPTED_PATCH,'points':P.tolist(),'masks':masks,'landmarks':landmarks,'coordinateFrame':'glTF +Y up +Z forward; uniform positive normalization; all masks from independent rest geometry boxes, not assigned skin weights'}
 (output.parent/'lingyu-rest-reference.json').write_text(json.dumps(reference,separators=(',',':'))+'\n');(output.parent/'lingyu-rig-contract.json').write_text(json.dumps(contract,indent=2)+'\n')
 # Independent evaluator reads the actual exported accessors and cubic buffers.
 skin=glb.GlbSkin(output);rest=skin.points();tri=skin.triangles;edges=np.unique(np.sort(np.concatenate([tri[:,[0,1]],tri[:,[1,2]],tri[:,[2,0]]]),axis=1),axis=0);length=np.linalg.norm(rest[edges[:,0]]-rest[edges[:,1]],axis=1);keep=length>.006;edges,length=edges[keep],length[keep];rigid=[k for k in masks if k=='face' or k.startswith(('hand_','foot_'))];qa={'sourceRigSha256':digest(output),'curveSeams':skin.curve_qa,'clips':{}}
 for clip,duration in DURATIONS.items():
  minimum=float('inf');maximum_strain=0;rigid_drift=0;movement=0
  for t in np.linspace(0,duration,49):
   posed=skin.points(clip,float(t));minimum=min(minimum,float(posed[:,2].min()));maximum_strain=max(maximum_strain,float(np.abs(np.linalg.norm(posed[edges[:,0]]-posed[edges[:,1]],axis=1)/length-1).max()));movement=max(movement,float(np.linalg.norm(posed-rest,axis=1).max()))
   for name in rigid:
    ids=np.asarray(masks[name]);anchors=ids[np.linspace(0,len(ids)-1,3,dtype=int)]
    for a in anchors:rigid_drift=max(rigid_drift,float(np.abs(np.linalg.norm(posed[ids]-posed[a],axis=1)-np.linalg.norm(rest[ids]-rest[a],axis=1)).max()))
  qa['clips'][clip]={'minimumWorldHeightM':minimum,'maximumEdgeStrainOver6mm':maximum_strain,'completeFaceHandsFeetDistanceDriftM':rigid_drift,'maximumDisplacementM':movement};(output.parent/'lingyu-rig-qa.json').write_text(json.dumps(qa,indent=2)+'\n');assert minimum>.12 and maximum_strain<.12 and rigid_drift<1e-5 and movement>.01,qa['clips'][clip]
 (output.parent/'lingyu-rig-qa.json').write_text(json.dumps(qa,indent=2)+'\n');print('EXPORTED',output,json.dumps(qa))
if __name__=='__main__':main()
