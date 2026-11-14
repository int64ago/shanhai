"""Offline Zhulong eye UV diagnostics and strictly local contrast derivative.
Run with Blender's bundled python -I. Never execute scripts from raw downloads.
Inspection never modifies a candidate. Derivation requires reviewed calibration.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SOURCE_SHA = "02097f47531438ad80c6aef6ca1f6043b73dc461097ac7b872967ec880dd8b74"
RUNTIME_SHA = "636580bbb5b26c9d7ffccb5d1a1434509a62e07e75afa227081e5a77a0680a0d"
MAGICK = shutil.which("magick") or "/opt/homebrew/bin/magick"

def sha(data): return hashlib.sha256(data).hexdigest()
def dump(path, data): path.write_text(json.dumps(data, indent=2) + "\n")
def load_glb(path):
    data = path.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", data)
    assert magic == b"glTF" and version == 2 and length == len(data)
    offset, doc, binary = 12, None, None
    while offset < length:
        size, kind = struct.unpack_from("<II", data, offset)
        value = data[offset+8:offset+8+size]
        if kind == 0x4e4f534a: doc = json.loads(value)
        elif kind == 0x004e4942: binary = value
        offset += 8+size
    return doc, binary

def accessor(doc, binary, index):
    spec = doc["accessors"][index]
    assert "sparse" not in spec
    types = {5120:"i1",5121:"u1",5122:"<i2",5123:"<u2",5125:"<u4",5126:"<f4"}
    widths = {"SCALAR":1,"VEC2":2,"VEC3":3,"VEC4":4,"MAT4":16}
    dtype, width = np.dtype(types[spec["componentType"]]), widths[spec["type"]]
    view = doc["bufferViews"][spec["bufferView"]]
    result = np.ndarray((spec["count"],width),dtype=dtype,buffer=binary,
        offset=view.get("byteOffset",0)+spec.get("byteOffset",0),
        strides=(view.get("byteStride",width*dtype.itemsize),dtype.itemsize)).copy()
    if spec.get("normalized"): result = result.astype(float)/np.iinfo(dtype).max
    return result

def image(doc,binary,texture):
    tex = doc["textures"][texture]
    index = tex.get("source",tex.get("extensions",{}).get("EXT_texture_webp",{}).get("source"))
    spec = doc["images"][index]
    view = doc["bufferViews"][spec["bufferView"]]
    start = view.get("byteOffset",0)
    return index,binary[start:start+view["byteLength"]],spec["mimeType"]

def rgba(path):
    dimensions = subprocess.check_output([MAGICK,"identify","-format","%w %h",str(path)],text=True).split()
    width,height = map(int,dimensions)
    raw = subprocess.check_output([MAGICK,str(path),"-alpha","on","-depth","8","rgba:-"])
    return np.frombuffer(raw,dtype=np.uint8).reshape(height,width,4).copy()

def png(path,values):
    values = np.asarray(values,dtype=np.uint8)
    h,w = values.shape[:2]
    subprocess.run([MAGICK,"-size",f"{w}x{h}","-depth","8","rgba:-",str(path)],input=values.tobytes(),check=True)

def geometry(doc,binary):
    prim = doc["meshes"][0]["primitives"][0]
    p = accessor(doc,binary,prim["attributes"]["POSITION"]).astype(float)
    uv = accessor(doc,binary,prim["attributes"]["TEXCOORD_0"]).astype(float)
    tri = accessor(doc,binary,prim["indices"]).ravel().reshape(-1,3)
    # Source native glTF Y-up, forward+Z; positive uniform normalization only.
    scale = 3.2/np.ptp(p[:,2])
    p = (p-[(p[:,0].min()+p[:,0].max())/2,p[:,1].min(),(p[:,2].min()+p[:,2].max())/2])*scale+[0,.22,0]
    return p,uv,tri

def project(points,uv,tri,texture,output,direction=(.35,.1,1.),target=(.07,.64,1.3),scale=.9,size=1200):
    direction = np.array(direction,dtype=float); direction /= np.linalg.norm(direction)
    right = np.cross([0,1,0],direction); right /= np.linalg.norm(right)
    up = np.cross(direction,right)
    relative = points-np.array(target)
    camera = np.stack([relative@right,relative@up,relative@direction],axis=1)
    xy = np.stack([(camera[:,0]/scale+.5)*size,(.5-camera[:,1]/scale)*size],axis=1)
    depth = np.full((size,size),-np.inf)
    face_ids = np.full((size,size),-1,dtype=np.int32)
    texels = np.full((size,size,2),-1,dtype=np.int32)
    xyz = np.full((size,size,3),np.nan,dtype=np.float32)
    result = np.full((size,size,4),255,dtype=np.uint8)
    height,width = texture.shape[:2]
    for f,ids in enumerate(tri):
        if points[ids,2].max()<.85: continue
        a,b,c = xy[ids]
        lo = np.maximum(np.floor(np.minimum(np.minimum(a,b),c)).astype(int),0)
        hi = np.minimum(np.ceil(np.maximum(np.maximum(a,b),c)).astype(int),size-1)
        if np.any(lo>hi): continue
        x,y = np.meshgrid(np.arange(lo[0],hi[0]+1)+.5,np.arange(lo[1],hi[1]+1)+.5)
        denom = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(denom)<1e-10: continue
        w0 = ((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/denom
        w1 = ((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/denom
        w2 = 1-w0-w1
        weights = np.stack([w0,w1,w2],axis=-1)
        z = weights@camera[ids,2]
        region = np.s_[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
        accepted = (np.minimum(np.minimum(w0,w1),w2)>=-1e-7)&(z>depth[region])
        if not accepted.any(): continue
        sampled_uv = weights@uv[ids]
        tx = np.clip((sampled_uv[...,0]*width).astype(int),0,width-1)
        ty = np.clip((sampled_uv[...,1]*height).astype(int),0,height-1)
        result[region][accepted] = texture[ty[accepted],tx[accepted]]
        texels[region][accepted] = np.stack([tx,ty],axis=-1)[accepted]
        xyz[region][accepted] = (weights@points[ids])[accepted]
        face_ids[region][accepted] = f
        depth[region][accepted] = z[accepted]
    png(output/"native-albedo-front.png",result)
    np.savez_compressed(output/"projection.npz",image=result,texels=texels,xyz=xyz,face_ids=face_ids,points=points,uv=uv,triangles=tri)
    return result

def inspect(args,out,source,runtime):
    sd,sb = load_glb(source); rd,rb = load_glb(runtime)
    s_texture = sd["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    r_texture = rd["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    _,encoded,_ = image(sd,sb,s_texture)
    (out/"source-basecolor.png").write_bytes(encoded)
    _,encoded,_ = image(rd,rb,r_texture)
    (out/"runtime-basecolor.webp").write_bytes(encoded)
    original = rgba(out/"source-basecolor.png")
    current = rgba(out/"runtime-basecolor.webp")
    points,uv,tri = geometry(sd,sb)
    project(points,uv,tri,original,out)
    subprocess.run([MAGICK,str(out/"source-basecolor.png"),"-resize","1024x1024",str(out/"source-atlas-1024.png")],check=True)
    dump(out/"inspection.json",{"sourceSha256":sha(source.read_bytes()),"runtimeSha256":sha(runtime.read_bytes()),"sourceImageSize":list(original.shape),"runtimeImageSize":list(current.shape),"geometryChanged":False,"projection":"Unlit native albedo, genuine native UV; no invented eyes"})

def inside(x,y,polygon):
    result = np.zeros(np.broadcast_shapes(np.shape(x),np.shape(y)),dtype=bool)
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        cross = ((a[1]>y)!=(b[1]>y)) & (x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1]+1e-20)+a[0])
        result ^= cross
    return result

def hull(values):
    values = sorted(set(map(tuple,values)))
    def cross(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def half(items):
        result=[]
        for p in items:
            while len(result)>1 and cross(result[-2],result[-1],p)<=0: result.pop()
            result.append(p)
        return result
    return half(values)[:-1]+half(values[::-1])[:-1]

def smooth(a,b,x):
    t=np.clip((x-a)/(b-a),0,1)
    return t*t*(3-2*t)

def eye_masks(args,out):
    inspection=args.inspection.resolve(strict=True)
    calibration=json.loads(args.calibration.resolve(strict=True).read_text())
    assert calibration["sourceSha256"]==SOURCE_SHA and calibration["runtimeSha256"]==RUNTIME_SHA
    p=np.load(inspection/"projection.npz")
    source=rgba(inspection/"source-basecolor.png")
    runtime=rgba(inspection/"runtime-basecolor.webp")
    h,w=runtime.shape[:2]; sh,sw=source.shape[:2]
    tx,ty=np.meshgrid((np.arange(w)+.5)*sw/w,(np.arange(h)+.5)*sh/h)
    yy,xx=np.indices(p["image"].shape[:2])
    # Sample the genuine native PNG for the gray-detail gates; no painted circle.
    native=source[np.minimum(ty.astype(int),sh-1),np.minimum(tx.astype(int),sw-1),:3].astype(float)
    thresholds=calibration["thresholds"]
    chroma=np.ptp(native,axis=2)
    luma=native@np.array([.2126,.7152,.0722])
    neutral=1-smooth(thresholds["sourceChromaFullBelow"],thresholds["sourceChromaZeroAbove"],chroma)
    detail=1-smooth(thresholds["sourceLumaFullBelow"],thresholds["sourceLumaZeroAbove"],luma)
    gate=neutral*detail*(native[:,:,2]/np.maximum(native[:,:,0],1)>=thresholds["minimumBlueRedRatio"])
    strength=np.zeros((h,w),dtype=float)
    reports={}
    for name,polygon in calibration["screenPolygons"].items():
        region=inside(xx+.5,yy+.5,polygon)&(p["face_ids"]>=0)
        native_uv=hull(p["texels"][region])
        support=inside(tx,ty,native_uv)
        local=support*gate
        strength=np.maximum(strength,local)
        ids=np.argwhere(local>0)
        geometry=p["xyz"][region]
        reports[name]={"nativeUvPixelHull":[list(map(int,v)) for v in native_uv],"runtimeChangedSupportTexels":len(ids),
            "runtimeUvBoundsXY":[ids[:,::-1].min(axis=0).tolist(),ids[:,::-1].max(axis=0).tolist()],
            "geometryBoundsGltf":[geometry.min(axis=0).tolist(),geometry.max(axis=0).tolist()],
            "nativeSourceLumaRange":[float(luma[local>0].min()),float(luma[local>0].max())]}
        assert len(ids)>2 and len(ids)<1000,reports[name]
    changed=runtime.copy()
    factor=1-thresholds["maximumDarkeningFraction"]*strength
    changed[:,:,:3]=np.round(runtime[:,:,:3].astype(float)*factor[:,:,None]).astype(np.uint8)
    mask=np.any(changed!=runtime,axis=2)
    assert mask.sum()<1500 and not np.any(changed[:,:,3]!=runtime[:,:,3])
    png(out/"basecolor-before.png",runtime)
    png(out/"basecolor-eye-contrast.png",changed)
    png(out/"eye-uv-mask.png",np.dstack([mask*255,mask*255,mask*255,np.full_like(mask,255,dtype=np.uint8)]))
    np.savez_compressed(out/"eye-mask.npz",mask=mask,strength=strength)
    uv=p["texels"]
    rx=np.clip((uv[:,:,0]*w/sw).astype(int),0,w-1)
    ry=np.clip((uv[:,:,1]*h/sh).astype(int),0,h-1)
    visible=p["face_ids"]>=0
    before=p["image"].copy();after=before.copy();overlay=before.copy()
    before[visible]=runtime[ry[visible],rx[visible]]
    after[visible]=changed[ry[visible],rx[visible]]
    selected=visible&mask[ry,rx]
    overlay[selected]=[0,220,230,255]
    png(out/"geometry-eye-mask-front.png",overlay)
    png(out/"runtime-albedo-before.png",before)
    png(out/"runtime-albedo-after.png",after)
    for name,polygon in calibration["screenPolygons"].items():
        xy=np.array(polygon)
        x0,y0=xy.min(axis=0)-[20,16]; x1,y1=xy.max(axis=0)+[20,16]
        for tag,im in [("before",before),("after",after),("mask",overlay)]:
            png(out/(name+"-"+tag+".png"),im[y0:y1,x0:x1])
            subprocess.run([MAGICK,str(out/(name+"-"+tag+".png")),"-filter","point","-resize","700%",str(out/(name+"-"+tag+"-zoom.png"))],check=True)
        bounds=reports[name]["runtimeUvBoundsXY"]
        lo=np.array(bounds[0])-[8,8];hi=np.array(bounds[1])+[9,9]
        atlas=runtime[lo[1]:hi[1],lo[0]:hi[0]].copy()
        region_mask=mask[lo[1]:hi[1],lo[0]:hi[0]]
        atlas[region_mask]=[0,220,230,255]
        png(out/(name+"-uv-mask.png"),atlas)
        subprocess.run([MAGICK,str(out/(name+"-uv-mask.png")),"-filter","point","-resize","1000%",str(out/(name+"-uv-mask-zoom.png"))],check=True)
    report={"sourceSha256":SOURCE_SHA,"runtimeSha256":RUNTIME_SHA,"regions":reports,"changedTexels":int(mask.sum()),
        "totalTexels":h*w,"thresholds":thresholds,"alphaChanged":False,
        "nonEyePixelsBitExact":bool(np.array_equal(changed[~mask],runtime[~mask])),
        "nonEyePixelBeforeSha256":sha(runtime[~mask].tobytes()),"nonEyePixelAfterSha256":sha(changed[~mask].tobytes()),
        "runtimeBeforePixelSha256":sha(runtime.tobytes()),"runtimeAfterPixelSha256":sha(changed.tobytes()),
        "anatomyMasksReviewed":False,"candidateCreated":False,"nonEyePixelReference":calibration["nonEyePixelReference"]}
    dump(out/"mask-audit.json",report)
    calibration["maskAuditSha256"]=sha((out/"mask-audit.json").read_bytes())
    calibration["maskPixelSha256"]=sha(mask.tobytes())
    dump(out/"calibration.json",calibration)

def derive(args,out,runtime):
    diagnostics=args.inspection.resolve(strict=True)
    cal=json.loads(args.calibration.resolve(strict=True).read_text())
    assert cal["anatomyMasksReviewed"] is True
    assert cal["maskAuditSha256"]==sha((diagnostics/"mask-audit.json").read_bytes())
    mask=np.load(diagnostics/"eye-mask.npz")["mask"]
    assert cal["maskPixelSha256"]==sha(mask.tobytes())
    before=rgba(diagnostics/"basecolor-before.png")
    after=rgba(diagnostics/"basecolor-eye-contrast.png")
    assert np.array_equal(before[~mask],after[~mask]) and not np.any(before[:,:,3]!=after[:,:,3])
    sd,sb=load_glb(args.source.resolve(strict=True))
    points,uv,tri=geometry(sd,sb)
    height,width=mask.shape
    yy,xx=np.nonzero(mask)
    xy=np.stack([xx+.5,yy+.5],axis=1)
    uv_pixels=uv*[width,height]
    occupied=set(); sampled=[]; affected_faces=[]
    for face,ids in enumerate(tri):
        a,b,c=uv_pixels[ids]
        lo=np.minimum(np.minimum(a,b),c);hi=np.maximum(np.maximum(a,b),c)
        choices=np.flatnonzero(np.all((xy>=lo)&(xy<=hi),axis=1))
        if not len(choices): continue
        denom=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(denom)<1e-12: continue
        x,y=xy[choices].T
        w0=((b[1]-c[1])*(x-c[0])+(c[0]-b[0])*(y-c[1]))/denom
        w1=((c[1]-a[1])*(x-c[0])+(a[0]-c[0])*(y-c[1]))/denom
        weights=np.stack([w0,w1,1-w0-w1],axis=1)
        ok=np.min(weights,axis=1)>=-1e-8
        if ok.any():
            occupied.update(choices[ok].tolist());sampled.extend(weights[ok]@points[ids]);affected_faces.append(face)
    assert len(occupied)==int(mask.sum()),"Changed texel outside native eye geometry"
    sampled=np.array(sampled)
    # Exhaustive UV occupancy check over ALL source triangles, including hidden
    # surfaces: the two tiny supports must not paint any other anatomical region.
    left=(sampled[:,0]>.065)&(sampled[:,0]<.105)&(sampled[:,1]>.64)&(sampled[:,1]<.67)&(sampled[:,2]>1.51)&(sampled[:,2]<1.55)
    right=(sampled[:,0]>.23)&(sampled[:,0]<.28)&(sampled[:,1]>.64)&(sampled[:,1]<.675)&(sampled[:,2]>1.43)&(sampled[:,2]<1.47)
    assert np.all(left|right),sampled[~(left|right)]
    def ink_fraction(rgb):
        srgb=rgb.astype(float)/255
        linear=np.where(srgb<=.04045,srgb/12.92,((srgb+.055)/1.055)**2.4)
        return 1-smooth(.02,.18,linear@np.array([.2126,.7152,.0722]))
    contrast={"meanCurrentShaderInkBefore":float(ink_fraction(before[:,:,:3][mask]).mean()),"meanCurrentShaderInkAfter":float(ink_fraction(after[:,:,:3][mask]).mean()),"note":"Analytical current shader ink gate only; not an actual Stage render"}
    doc,binary=load_glb(runtime)
    texture_id=doc["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    image_id,original,mime=image(doc,binary,texture_id)
    assert mime=="image/webp"
    baseline=out/"original-runtime-basecolor.webp"
    baseline.write_bytes(original)
    assert np.array_equal(rgba(baseline),before)
    encoded=(diagnostics/"basecolor-eye-contrast.png").read_bytes()
    payload=bytearray(binary)
    payload.extend(b"\x00"*((-len(payload))%4));start=len(payload);payload.extend(encoded)
    view=len(doc["bufferViews"])
    doc["bufferViews"].append({"buffer":0,"byteOffset":start,"byteLength":len(encoded)})
    doc["images"][image_id]["bufferView"]=view
    doc["images"][image_id]["mimeType"]="image/png"
    texture=doc["textures"][texture_id]
    texture["source"]=image_id
    texture.get("extensions",{}).pop("EXT_texture_webp",None)
    if texture.get("extensions")=={}: texture.pop("extensions",None)
    doc["buffers"][0]["byteLength"]=len(payload)
    raw=json.dumps(doc,separators=(",",":")).encode();raw+=b" "*((-len(raw))%4)
    payload.extend(b"\x00"*((-len(payload))%4))
    length=12+8+len(raw)+8+len(payload)
    candidate=out/"body.glb"
    candidate.write_bytes(struct.pack("<4sII",b"glTF",2,length)+struct.pack("<II",len(raw),0x4e4f534a)+raw+struct.pack("<II",len(payload),0x004e4942)+payload)
    assert length<15*1024*1024
    old_doc,old_binary=load_glb(runtime);new_doc,new_binary=load_glb(candidate)
    assert new_binary[:len(old_binary)]==old_binary
    # All geometry/skin/animation/accessor bytes remain in their original buffers.
    for name in ["meshes","skins","animations","accessors","nodes","materials","samplers"]:
        assert old_doc[name]==new_doc[name],name
    images=[]
    for i,spec in enumerate(old_doc["images"]):
        v=old_doc["bufferViews"][spec["bufferView"]];a=old_binary[v.get("byteOffset",0):v.get("byteOffset",0)+v["byteLength"]]
        v=new_doc["bufferViews"][new_doc["images"][i]["bufferView"]];b=new_binary[v.get("byteOffset",0):v.get("byteOffset",0)+v["byteLength"]]
        images.append({"image":i,"changed":a!=b,"beforeSha256":sha(a),"afterSha256":sha(b)})
        assert (a!=b)==(i==image_id)
    dump(out/"eye-contrast-audit.json",{"candidate":str(candidate),"candidateSha256":sha(candidate.read_bytes()),"candidateBytes":length,
        "sourceSha256":SOURCE_SHA,"parentRuntimeSha256":RUNTIME_SHA,"scriptSha256":sha(Path(__file__).read_bytes()),
        "calibration":cal,"maskAudit":json.loads((diagnostics/"mask-audit.json").read_text()),"images":images,
        "geometrySkinAnimationAccessorBytesUnchanged":True,"materialsUnchanged":True,"otherPbrImagesBytesUnchanged":True,
        "nonEyePixelsBitExact":True,"baseColorEncoding":"Lossless PNG preserving every decoded runtime pixel outside reviewed iris mask; other textures remain original WebP",
        "exhaustiveNativeUvOccupancy":{"changedTexelsOnEyeGeometry":len(occupied),"sourceTrianglesAffected":len(affected_faces),"sourceTriangleIndices":affected_faces,"allOccupancyRestrictedToTwoReviewedEyeRegions":True,"boundsGltf":[sampled.min(axis=0).tolist(),sampled.max(axis=0).tolist()]},
        "analyticalContrast":contrast,"sourceObservation":cal["sourceObservation"],"productionAccepted":False,"browserQaRun":False})
    shutil.copyfile(args.calibration,out/"calibration.json")
    shutil.copyfile(diagnostics/"eye-mask.npz",out/"eye-mask.npz")
    print(json.dumps({"candidate":str(candidate),"bytes":length,"sha256":sha(candidate.read_bytes()),"changedTexels":int(mask.sum())}),flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode",choices=["inspect","masks","derive"])
    p.add_argument("source",type=Path)
    p.add_argument("runtime",type=Path)
    p.add_argument("output",type=Path)
    p.add_argument("--inspection",type=Path)
    p.add_argument("--calibration",type=Path)
    args=p.parse_args()
    source,runtime,out=args.source.resolve(strict=True),args.runtime.resolve(strict=True),args.output.resolve()
    assert sha(source.read_bytes())==SOURCE_SHA and sha(runtime.read_bytes())==RUNTIME_SHA
    assert out.is_relative_to(ROOT/"raw/_build") and not out.exists()
    out.mkdir(parents=True)
    if args.mode=="inspect": inspect(args,out,source,runtime)
    elif args.mode=="masks": eye_masks(args,out)
    else: derive(args,out,runtime)
    assert sha(source.read_bytes())==SOURCE_SHA and sha(runtime.read_bytes())==RUNTIME_SHA

if __name__=="__main__": main()
