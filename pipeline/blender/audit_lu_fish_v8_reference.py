"""Independently decode actual GLB geometry/UV retention in frozen native domains."""
import argparse,hashlib,json,struct,sys
from pathlib import Path
sys.dont_write_bytecode=True
import numpy as np
from mathutils.kdtree import KDTree
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[2]
A=np.array([[1.,0,0],[0,0,-1],[0,1,0]])
def read(p):
    raw=Path(p).read_bytes();assert raw[:4]==b'glTF';n=struct.unpack_from('<I',raw,12)[0];return json.loads(raw[20:20+n]),raw[28+n:]
def array(d,b,i):
    a=d['accessors'][i];v=d['bufferViews'][a['bufferView']];dt={5126:'<f4',5125:'<u4',5123:'<u2',5121:'u1'}[a['componentType']];n={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']]
    return np.ndarray((a['count'],n),dtype=dt,buffer=b,offset=v.get('byteOffset',0)+a.get('byteOffset',0),strides=(v.get('byteStride',n*np.dtype(dt).itemsize),np.dtype(dt).itemsize)).copy()
def cyclic(t):
    a,b,c=map(int,t);return min((a,b,c),(b,c,a),(c,a,b))
def main():
    arg=argparse.ArgumentParser();arg.add_argument('--source',required=True);arg.add_argument('--candidate',required=True);arg.add_argument('--output',required=True);args=arg.parse_args(sys.argv[sys.argv.index('--')+1:])
    src=Path(args.source).resolve();dst=Path(args.candidate).resolve();out=Path(args.output).resolve();assert all(p.is_relative_to(ROOT/'raw') for p in [src,dst,out]);sd,sb=read(src);cd,cb=read(dst);sp=sd['meshes'][0]['primitives'][0]
    rawp=array(sd,sb,sp['attributes']['POSITION']).astype(float);sn=array(sd,sb,sp['attributes']['NORMAL']).astype(float)@A.T;su=array(sd,sb,sp['attributes']['TEXCOORD_0']).astype(float);st=array(sd,sb,sp['indices']).reshape(-1,3)
    p=rawp@A.T;lo=p.min(0);hi=p.max(0);scale=1/max(hi-lo);offset=np.array([-(lo[0]+hi[0])/2,-(lo[1]+hi[1])/2,-lo[2]])*scale;p=p*scale+offset
    _,canonical=np.unique(np.column_stack([rawp,su]),axis=0,return_inverse=True)
    kd=KDTree(len(p))
    for i,v in enumerate(p):kd.insert(Vector(v),i)
    kd.balance()
    x,y,z=p.T
    masks={'native_wings_and_low_roots':((abs(x)>.075)&(y>-.15)&(y<.18)&(z>.23)&(z<.65))|((abs(x)>.20)&(y<.22)&(z>.10)&(z<.65)), 'four_lower_legs_and_hooves':(abs(x)<.158)&(y<.38)&(z<.20), 'central_bovine_torso':(y>-.22)&(y<.205)&(z>.30)&(z<.63)}
    native_triangles=set();max_position_error=0.;max_uv_error=0.;normal_errors=[];normal_by_source={};all_positions=[];all_tri=[];base=0
    for prim in cd['meshes'][0]['primitives']:
        q=array(cd,cb,prim['attributes']['POSITION']).astype(float)@A.T;t=array(cd,cb,prim['indices']).reshape(-1,3).astype(np.int64);all_positions.append(q);all_tri.append(t+base);base+=len(q)
        if prim.get('material')!=0:continue
        u=array(cd,cb,prim['attributes']['TEXCOORD_0']).astype(float);n=array(cd,cb,prim['attributes']['NORMAL']).astype(float)@A.T;mapping=np.full(len(q),-1,np.int64)
        for i,v in enumerate(q):
            candidates=kd.find_range(Vector(v),1e-6)
            valid=[(j,dist) for _,j,dist in candidates if np.max(abs(su[j]-u[i]))<2e-6]
            if not valid:continue
            j,dist=min(valid,key=lambda item:np.linalg.norm(sn[item[0]]-n[i]));mapping[i]=canonical[j]
            max_position_error=max(max_position_error,float(dist));max_uv_error=max(max_uv_error,float(np.max(abs(su[j]-u[i]))));normal_errors.append(float(np.linalg.norm(sn[j]-n[i])));key=int(canonical[j]);normal_by_source[key]=max(normal_by_source.get(key,0.),normal_errors[-1])
        for face in t:
            ids=mapping[face]
            if np.all(ids>=0):native_triangles.add(cyclic(ids))
    result={'candidate':str(dst),'candidateSha256':hashlib.sha256(dst.read_bytes()).hexdigest(),'source':str(src),'sourceSha256':hashlib.sha256(src.read_bytes()).hexdigest(),'domains':{},'maximumMappedPositionErrorH':max_position_error,'maximumMappedUvError':max_uv_error,'maximumMappedNormalVectorError':max(normal_errors,default=None),'normalLimit':'Blender re-encodes custom split normals. This records actual error rather than claiming source-normal bytes exact.','limits':'Frozen-domain oriented triangle geometry/UV audit only. Does not certify new-skin self intersections, distal-tip anatomy, color matching or visual acceptance.'}
    for name,mask in masks.items():
        selected=st[np.all(mask[st],axis=1)];expected={cyclic(canonical[t]) for t in selected};missing=expected-native_triangles
        result['domains'][name]={'protectedSourceTriangles':len(selected),'uniqueProtectedTriangles':len(expected),'missingOrChangedOrientedPositionUvTriangles':len(missing),'maximumProtectedVertexNormalError':max((normal_by_source.get(int(i),0.) for i in np.unique(canonical[selected])),default=0.),'pass':not missing}
    positions=np.vstack(all_positions);triangles=np.vstack(all_tri);_,inv=np.unique(positions,axis=0,return_inverse=True);t=inv[triangles];nondeg=(t[:,0]!=t[:,1])&(t[:,1]!=t[:,2])&(t[:,2]!=t[:,0]);t=t[nondeg];edges=np.sort(np.vstack([t[:,[0,1]],t[:,[1,2]],t[:,[2,0]]]),axis=1);_,counts=np.unique(edges,axis=0,return_counts=True)
    result['actualPositionWeldedTopology']={'boundaryEdges':int((counts==1).sum()),'nonmanifoldEdges':int((counts>2).sum()),'collapsedNativeOrNewTrianglesExcluded':int((~nondeg).sum()),'triangles':len(triangles)}
    result['allProtectedDomainsPass']=all(v['pass'] for v in result['domains'].values());out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=1),flush=True)
if __name__=='__main__':main()
