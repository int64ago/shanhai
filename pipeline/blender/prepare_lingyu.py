"""Recipe preparation: rebuild accepted High+High donor patch, then uniform scale.
Blender --background --python THIS -- INPUT.glb OUTPUT.glb --length 2.4
No API, remesh, normal recomputation, Medium runtime source, or body reflection.
"""
import sys,json,hashlib,argparse,runpy
from pathlib import Path
import numpy as np
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import rig_yinglong_native as glb
ROOT=Path(__file__).resolve().parents[2]
ACCEPTED_PATCH='b4a02d4ae07c06a35b8bdc818e8da789640ffaf4e46b33cfb87cc3f8b787184b'
SOURCE_SHA='214672b66577aec8fe33badb95e91c500c92fde72aa7298e4e8765237e5ed308'
DONOR_SHA='7b8f311778d006197a22113b397193a651d66fb3a2de9801d1da2ede32622cc8'
ELEVATION=.22

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def append(doc,binary,values,kind,component=5126):
 dtype={5126:'<f4',5123:'<u2',5125:'<u4'}[component];values=np.asarray(values,dtype=dtype)
 while len(binary)%4:binary.append(0)
 view=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':len(binary),'byteLength':values.nbytes});binary.extend(values.tobytes())
 idx=len(doc['accessors']);a={'bufferView':view,'componentType':component,'count':len(values),'type':kind}
 if kind in ['SCALAR','VEC3']:a.update(min=values.min(0).reshape(-1).tolist(),max=values.max(0).reshape(-1).tolist())
 doc['accessors'].append(a);return idx

def main():
 a=argparse.ArgumentParser();a.add_argument('source',type=Path);a.add_argument('output',type=Path);a.add_argument('--length',type=float,default=2.4);a.add_argument('--donor',type=Path,default=Path('raw/xingtian-production-20261115-closed-grip-whole-v7-high/base_high_pbr.glb'));args=a.parse_args(sys.argv[sys.argv.index('--')+1:])
 source=args.source.resolve();output=args.output.resolve();donor=(ROOT/args.donor).resolve() if not args.donor.is_absolute() else args.donor.resolve()
 assert digest(source)==SOURCE_SHA and digest(donor)==DONOR_SHA
 assert output.is_relative_to(ROOT/'raw/_build') and not output.exists()
 output.parent.mkdir(parents=True,exist_ok=True);rebuild=output.parent/'lingyu-forefeet-rebuild'
 oldargv=sys.argv[:]
 try:
  sys.argv=['repair_lingyu_donor_forefeet.py','--',str(rebuild)];runpy.run_path(str(Path(__file__).with_name('repair_lingyu_donor_forefeet.py')),run_name='__main__')
 finally:sys.argv=oldargv
 candidate=rebuild/'lingyu-donor-forefeet.glb';assert digest(candidate)==ACCEPTED_PATCH,'Rebuild differs from parent-reviewed static candidate'
 doc,data=glb.glb_read(candidate);binary=bytearray(data);positions=[glb.accessor(doc,data,p['attributes']['POSITION']) for p in doc['meshes'][0]['primitives']];allp=np.concatenate(positions);low,high=allp.min(0),allp.max(0);scale=args.length/(high[2]-low[2]);origin=np.array([(low[0]+high[0])/2,low[1],(low[2]+high[2])/2]);translation=np.array([0,ELEVATION,0])
 for p,points in zip(doc['meshes'][0]['primitives'],positions):p['attributes']['POSITION']=append(doc,binary,(points-origin)*scale+translation,'VEC3')
 from paint_lingyu_eyes import paint
 eye_audit=paint(doc,binary,output.parent/'eye-material')
 contract={'beast':'lingyu','sourceHighSha256':SOURCE_SHA,'donorHighSha256':DONOR_SHA,'acceptedStaticPatchSha256':ACCEPTED_PATCH,'uniformScale':float(scale),'rawOrigin':origin.tolist(),'elevationM':ELEVATION,'bodyLengthM':args.length,'geometryRoute':'Rebuilt bounded actual Xingtian High distal forefeet on actual Lingyu High; positive uniform normalization only thereafter','normalRecomputation':False,'eyeMaterialImageSha256':eye_audit['patchedImageSha256'],'riggingAccepted':True,'runtimeAccepted':False}
 doc.setdefault('extras',{})['lingyuPreparation']=contract;glb.write_glb(output,doc,binary);contract['preparedSha256']=digest(output);(output.parent/'lingyu-preparation.json').write_text(json.dumps(contract,indent=2)+'\n');print('EXPORTED',output)
if __name__=='__main__':main()
