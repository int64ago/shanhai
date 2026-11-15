"""Bounded eye base-color pixels, calibrated from actual Stage raycast UV/rest probes.
Blender --background --factory-startup --python THIS -- INPUT.glb NEW_OUTPUT.glb
No geometry, skin, curves, normals, non-eye pixels, or shared shaders are changed.
"""
import sys,json,hashlib,copy,argparse,subprocess
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
import numpy as np
import rig_yinglong_native as glb
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'raw/lingyu-production-20261115-corrected-human-limbs-v12-high/base_high_pbr.glb'
SOURCE_SHA='214672b66577aec8fe33badb95e91c500c92fde72aa7298e4e8765237e5ed308'
# Native glTF coordinates, from decoded rest-skin raycasts (not quantized POSITION).
# Both eyes have their own actual centers; no assumed reflection of the face.
CALIBRATION=ROOT/'pipeline/provenance/lingyu-eye-uv-calibration-20261115.json'
EYES=json.loads(CALIBRATION.read_text())['eyes']
def sha(data):return hashlib.sha256(data).hexdigest()
def smooth(x,a,b):
 t=np.clip((x-a)/(b-a),0,1);return t*t*(3-2*t)
def field(points):
 strength=np.zeros(points.shape[:-1]);color=np.ones((*strength.shape,3))
 for e in EYES:
  dx=points[...,0]-e['center'][0];dy=points[...,1]-e['center'][1];q=dx/e['halfWidth'];arch=np.sqrt(np.maximum(0,1-q*q));top=e['upper']*arch;bottom=-e['lower']*arch
  guard=(np.abs(q)<1)&(points[...,2]>.775)&(points[...,2]<.87)
  opening=smooth(dy,bottom-.0008,bottom+.0008)*(1-smooth(dy,top-.0008,top+.0008))*guard
  iris=1-smooth(np.sqrt((dx/e['irisRadius'][0])**2+(dy/e['irisRadius'][1])**2),.85,1.05)
  pupil=1-smooth(np.sqrt((dx/.0038)**2+(dy/.0055)**2),.85,1.1)
  upper=(1-smooth(np.abs(dy-top),.0004,.0017))*guard*smooth(1-np.abs(q),0,.12)
  lower=(1-smooth(np.abs(dy-bottom),.0003,.0012))*guard*smooth(1-np.abs(q),0,.12)*.55
  for alpha,target in [(iris*opening,[.20,.215,.21]),(pupil*opening,[.065,.075,.07]),(upper*.8,[.29,.285,.27]),(lower,[.39,.37,.34])]:
   # Accumulate as premultiplied source-over, then convert to a single target.
   combined=alpha+strength*(1-alpha)
   color=np.where(combined[...,None]>0,(np.asarray(target)*alpha[...,None]+color*strength[...,None]*(1-alpha[...,None]))/np.maximum(combined[...,None],1e-10),color)
   strength=combined
 return strength,color

def paint(doc,binary,directory):
 directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
 sourcebytes=SOURCE.read_bytes();assert sha(sourcebytes)==SOURCE_SHA
 sd,sb=glb.glb_read(SOURCE);p=sd['meshes'][0]['primitives'][0];P=glb.accessor(sd,sb,p['attributes']['POSITION']);UV=glb.accessor(sd,sb,p['attributes']['TEXCOORD_0']);F=glb.accessor(sd,sb,p['indices']).reshape(-1,3)
 before=copy.deepcopy(doc);prefix=bytes(binary)
 texid=doc['materials'][0]['pbrMetallicRoughness']['baseColorTexture']['index'];texture=doc['textures'][texid];imageid=texture.get('source',texture.get('extensions',{}).get('EXT_texture_webp',{}).get('source'));image=doc['images'][imageid];view=doc['bufferViews'][image['bufferView']];encoded=prefix[view.get('byteOffset',0):view.get('byteOffset',0)+view['byteLength']]
 sourcepath=directory/('original-eye-base.webp' if image['mimeType']=='image/webp' else 'original-eye-base.png');sourcepath.write_bytes(encoded)
 if image['mimeType']=='image/webp':
  # macOS's local decoder; production preparation receives PNG and needs no conversion.
  decoded=directory/'original-eye-base-decoded.png';subprocess.run(['sips','-s','format','png',str(sourcepath),'--out',str(decoded)],check=True,stdout=subprocess.DEVNULL);sourcepath=decoded
 im=bpy.data.images.load(str(sourcepath),check_existing=False);im.colorspace_settings.name='Non-Color';width,height=im.size[:];original=np.asarray(im.pixels[:],dtype=np.float32).reshape(height,width,4);pixels=original.copy();mask=np.zeros((height,width),dtype=np.float32);target=np.zeros((height,width,3),dtype=np.float32);selected=[]
 for i,face in enumerate(F):
  pts=P[face];lo=pts.min(0);hi=pts.max(0)
  if hi[2]<.775 or lo[2]>.87:continue
  if not any(hi[0]>e['center'][0]-e['halfWidth'] and lo[0]<e['center'][0]+e['halfWidth'] and hi[1]>e['center'][1]-.011 and lo[1]<e['center'][1]+.013 for e in EYES):continue
  uv=UV[face]*[width,-height]+[0,height];xmin,ymin=np.maximum(np.floor(uv.min(0)-1).astype(int),[0,0]);xmax,ymax=np.minimum(np.ceil(uv.max(0)+1).astype(int),[width-1,height-1]);a,b,c=uv;v0=b-a;v1=c-a;det=v0[0]*v1[1]-v0[1]*v1[0]
  if abs(det)<1e-8:continue
  yy,xx=np.mgrid[ymin:ymax+1,xmin:xmax+1];v2=np.stack([xx+.5,yy+.5],axis=-1)-a;u=(v2[...,0]*v1[1]-v2[...,1]*v1[0])/det;v=(v0[0]*v2[...,1]-v0[1]*v2[...,0])/det;inside=(u>=-1e-6)&(v>=-1e-6)&(u+v<=1+1e-6);world=pts[0]+u[...,None]*(pts[1]-pts[0])+v[...,None]*(pts[2]-pts[0]);alpha,colors=field(world);alpha*=inside
  region=mask[ymin:ymax+1,xmin:xmax+1];take=alpha>region;region[take]=alpha[take];target[ymin:ymax+1,xmin:xmax+1][take]=colors[take]
  if np.any(alpha>0):selected.append(int(i))
 pixels[...,:3]=original[...,:3]*(1-mask[...,None])+target*mask[...,None]
 changed=np.max(np.abs(pixels-original),axis=-1)>1/255
 assert 100<changed.sum()<width*height*.005,(changed.sum(),width,height)
 assert np.array_equal(pixels[mask==0],original[mask==0])
 output=directory/'bounded-eye-base.png';outim=bpy.data.images.new('Lingyu_bounded_eyes',width=width,height=height,alpha=True);outim.colorspace_settings.name='Non-Color';outim.pixels.foreach_set(pixels.ravel());outim.file_format='PNG';outim.filepath_raw=str(output);outim.save()
 check=bpy.data.images.load(str(output),check_existing=False);check.colorspace_settings.name='Non-Color';decoded=np.asarray(check.pixels[:],dtype=np.float32).reshape(height,width,4)
 assert np.array_equal(np.rint(decoded[mask==0]*255),np.rint(original[mask==0]*255)),'PNG changed a pixel outside eye mask'
 while len(binary)%4:binary.append(0)
 png=output.read_bytes();imageview=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':len(binary),'byteLength':len(png)});binary.extend(png);doc['images'][imageid]={**image,'bufferView':imageview,'mimeType':'image/png'}
 if 'EXT_texture_webp' in texture.get('extensions',{}):
  del texture['extensions']['EXT_texture_webp'];texture['source']=imageid
  if not texture['extensions']:del texture['extensions']
 assert bytes(binary[:len(prefix)])==prefix
 for key in ['meshes','nodes','skins','animations','accessors']:
  assert doc.get(key)==before.get(key),key
 for i,item in enumerate(before['images']):
  if i!=imageid:assert doc['images'][i]==item
 audit={'beast':'lingyu','sourceHighSha256':SOURCE_SHA,'route':'Actual eye surface triangles rasterized through their native UV; only base-color pixels','pixelEqualityScope':'Uncompressed PNG repair step only; runtime WebP is lossy','calibrationFile':str(CALIBRATION.relative_to(ROOT)),'calibration':EYES,'sourceTriangleIds':selected,'baseImageId':imageid,'imageSize':[width,height],'changedPixelsOver1Byte':int(changed.sum()),'totalPixels':width*height,'outsideMaskPixelsExactlyUnchanged':True,'geometrySkinAndAnimationExactlyUnchanged':True,'originalBinaryPrefixExactlyUnchanged':True,'patchedImageSha256':sha(png),'ready':False}
 doc.setdefault('extras',{})['lingyuEyeMaterial']=audit;(directory/'eye-material-audit.json').write_text(json.dumps(audit,indent=2)+'\n');return audit

def main():
 parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args(sys.argv[sys.argv.index('--')+1:]);output=args.output.resolve();assert output.is_relative_to(ROOT/'raw/_build') and not output.exists();output.parent.mkdir(parents=True,exist_ok=True);doc,data=glb.glb_read(args.source.resolve());binary=bytearray(data);paint(doc,binary,output.parent/'eye-material');glb.write_glb(output,doc,binary);print('EXPORTED',output,sha(output.read_bytes()))
if __name__=='__main__':main()
