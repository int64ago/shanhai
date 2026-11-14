"""Offline source-calibrated Leishen complete-human-head/native-upright-serpent rig.

Run from the trusted worktree, never an asset download directory:
  blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
    --python pipeline/blender/rig_leishen_native.py -- SOURCE.glb NEW_OUTPUT \
    --calibration REVIEWED.json --accepted-source-sha256 SHA256
--inspect writes native measurements only; --calibrate renders geometry-only masks.
No reconstruction, recoloring, texture edits, remesh, or ground-pose correction.
The source is accepted FOR RIGGING ONLY; no runtime or production acceptance here.
"""
import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
TRUSTED = Path(__file__).resolve().parent
ROOT = TRUSTED.parents[1]
sys.path.insert(0,str(TRUSTED))
import bpy
import numpy as np
from mathutils import Matrix,Vector
import rig_yinglong_native as shared

FPS=60
LENGTH=3.2
ELEVATION=.22
SEGMENTS=24
DURATIONS={'idle':6.,'walk':4.,'special':6.}
COORDINATES='Blender X/right Y/back Z/up; native lengthY3.2m; minimumZ baked to0.22m'
sha=shared.sha
dump=shared.dump
array_sha=shared.array_sha
smooth=shared.smooth
base=shared.base


def load_source(source):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source),disable_bone_shape=True)
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    assert len(meshes)==1 and not any(o.type=='ARMATURE' for o in bpy.context.scene.objects)
    obj=meshes[0]
    assert not obj.modifiers and not obj.vertex_groups and not obj.data.shape_keys
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active=obj
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    assert obj.matrix_world.to_3x3().determinant()>0
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    for other in list(bpy.context.scene.objects):
        if other is not obj:
            bpy.data.objects.remove(other,do_unlink=True)
    before=shared.native_fingerprint(obj)
    native=np.array([tuple(v.co) for v in obj.data.vertices])
    normals=np.array([tuple(n.vector) for n in obj.data.corner_normals])
    assert np.isfinite(native).all() and np.isfinite(normals).all()
    low,high=native.min(axis=0),native.max(axis=0)
    scale=LENGTH/(high[1]-low[1])
    origin=np.array([(low[0]+high[0])/2,(low[1]+high[1])/2,low[2]])
    expected=(native-origin)*scale+[0,0,ELEVATION]
    transform=Matrix.Translation((0,0,ELEVATION))@Matrix.Scale(scale,4)@Matrix.Translation(-Vector(origin))
    obj.data.transform(transform)
    obj.data.update()
    obj.data.normals_split_custom_set(normals.tolist())
    after=shared.native_fingerprint(obj)
    assert {k:v for k,v in before.items() if k!='cornerNormalsSha256'}=={k:v for k,v in after.items() if k!='cornerNormalsSha256'}
    points=np.array([tuple(v.co) for v in obj.data.vertices])
    error=float(np.abs(points-expected).max())
    normal_error=float(np.abs(np.array([tuple(n.vector) for n in obj.data.corner_normals])-normals).max())
    assert error<4e-7 and normal_error<.0012,(error,normal_error)
    # Decoded Blender custom-normal codec only; actual GLB NORMAL passes through
    # source bytes directly. No reconstructed normals enter the delivered mesh.
    assert np.abs(np.array(obj.matrix_world)-np.eye(4)).max()<1e-6
    obj.name='leishen_native_complete_human_head_upright_serpent'
    return obj,points,{'sourceBoundsBlender':[low.tolist(),high.tolist()],
        'positiveUniformScale':scale,'decodedOrigin':origin.tolist(),'permanentElevationBakedM':ELEVATION,
        'meshObjectScale':list(obj.scale),'sourceFingerprint':before,'normalizedFingerprint':after,
        'maximumNormalizationPositionErrorM':error,'decodedCornerNormalCodecError':normal_error,
        'geometryReconstruction':False,'recoloring':False,'normalRecomputation':False,
        'restPositionsSha256':array_sha(points)}


def inspect(obj,points,out):
    graph=shared.adjacency(obj,points)
    comps=shared.components(graph,np.ones(len(points),dtype=bool))
    report={'bounds':shared.describe(points),'components':[dict(seed=c[0],**shared.describe(points,c)) for c in comps],
            'longitudinalSlices':[],'sourceAxesConfirmed':'human face +X, long body Y with head at -Y and single tail +Y; native +Z up; no rotation applied'}
    for y in np.arange(-1.60,1.61,.08):
        ids=np.flatnonzero((points[:,1]>=y)&(points[:,1]<y+.08))
        if len(ids):
            report['longitudinalSlices'].append(dict(yRange=[float(y),float(y+.08)],**shared.describe(points,ids)))
    np.savez(out/'native-probe.npz',positions=points,edges=np.array([tuple(e.vertices) for e in obj.data.edges]),
        triangles=np.array([tuple(p.vertices) for p in obj.data.polygons]),
        normals=np.array([tuple(n.vector) for n in obj.data.corner_normals]),
        uv=np.array([tuple(v.uv) for v in obj.data.uv_layers.active.data]))
    dump(out/'probe.json',report)
    print('LEISHEN_NATIVE_PROBE',json.dumps(report),flush=True)


def masks_from_calibration(obj,points,cal,review=True):
    graph=shared.adjacency(obj,points)
    result={}
    for name,spec in cal['cuts'].items():
        allowed=np.ones(len(points),dtype=bool)
        for plane in spec['planes']:
            allowed &= points@np.array(plane['normal']) <= plane['offset']
        comps=shared.components(graph,allowed)
        ids=sorted(i for c in comps for i in c)
        assert len(ids)>20,name
        seeds=[c[0] for c in comps]
        if review:
            assert spec['seeds']==seeds and spec['count']==len(ids)
            assert spec['indicesSha256']==array_sha(ids,'<u4')
        else:
            spec.update(seeds=seeds,count=len(ids),indicesSha256=array_sha(ids,'<u4'))
        result[name]=ids
    assert not set(result['head'])&set(result['neck'])
    result['body']=[i for i in range(len(points)) if i not in set(result['head'])]
    result['tail']=[i for i in result['body'] if points[i,1]>=cal['tailMaskStartY']]
    result['all_native']=list(range(len(points)))
    return result


def diagnostic(obj,points,masks,cal,out):
    out.mkdir()
    camera=shared.camera_setup(900)
    original=list(obj.data.materials)
    indices=[p.material_index for p in obj.data.polygons]
    regions=np.zeros(len(points),dtype=int)
    regions[masks['head']]=1
    regions[masks['neck']]=2
    colors=[(.05,.24,.52,1),(.10,.70,.24,1),(.85,.28,.06,1)]
    obj.data.materials.clear()
    try:
        for j,color in enumerate(colors):
            material=bpy.data.materials.new('native_geometry_region_'+str(j))
            material.use_nodes=True
            shader=material.node_tree.nodes.get('Principled BSDF')
            shader.inputs['Base Color'].default_value=color
            shader.inputs['Emission Color'].default_value=color
            shader.inputs['Emission Strength'].default_value=.25
            obj.data.materials.append(material)
        for poly in obj.data.polygons:
            poly.material_index=int(np.bincount(regions[list(poly.vertices)],minlength=3).argmax())
        center=(points.min(axis=0)+points.max(axis=0))/2
        for tag,direction in [('34',(1,-.7,.25)),('plus-x',(1,0,.1)),('minus-x',(-1,0,.1)),('top',(0,0,1)),('minus-y',(0,-1,.05)),('plus-y',(0,1,.05))]:
            shared.render_view(camera,out,'regions-'+tag,center,direction,3.7)
        ids=masks['head']+masks['neck']
        p=points[ids]
        target=(p.min(axis=0)+p.max(axis=0))/2
        for tag,direction in [('face-plus-x',(1,0,.08)),('skull-minus-x',(-1,0,.10)),('ear-minus-y',(0,-1,.1)),('ear-plus-y',(0,1,.1))]:
            shared.render_view(camera,out,'human-head-neck-'+tag,target,direction,1.45)
    finally:
        obj.data.materials.clear()
        for material in original:
            obj.data.materials.append(material)
        for poly,index in zip(obj.data.polygons,indices):
            poly.material_index=index


def runtime_contract():
    return {'scale':1.,'sourceFaceForward':'Blender +X / glTF +X; body long axis Blender Y / glTF -Z; native relative orientation retained','restLengthY':LENGTH,
        'permanentMinimumZ':ELEVATION,'permanentElevationMethod':'Baked translation in native mesh coordinates and matching skeleton rests; no normalization node scale',
        'outerLocomotionRequired':False,'animatedRootTranslation':'Small periodic vertical bob centered at zero; no X/Z runtime locomotion',
        'idleDuration':6.,'walkDuration':4.,'specialDuration':6.,'walkMeaning':'Stationary slow 3D axial traveling wave',
        'specialReturn':'Matches idle phase0 pose, velocity and acceleration at both endpoints',
        'interpolation':'60fps source keys; actual periodic C2 glTF CUBICSPLINE; Float32 residuals disclosed in QA',
        'boneScale':'Every bone scale is exactly one in all clips; no longitudinal stretching',
        'productionAccepted':False}


def make_rig(cal):
    arm=bpy.data.objects.new('leishen_rig',bpy.data.armatures.new('leishen_native_human_head_axis'))
    bpy.context.scene.collection.objects.link(arm)
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    bpy.context.view_layer.objects.active=arm
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(name,a,b,parent=None,deform=True):
        item=arm.data.edit_bones.new(name)
        item.head,item.tail=Vector(a),Vector(b)
        assert (item.tail-item.head).length>1e-4
        item.use_deform=deform
        if parent:
            item.parent=arm.data.edit_bones[parent]
        return item
    bone('root',(0,0,0),(0,0,.12),deform=False)
    pts=cal['landmarks']['centerline']
    assert len(pts)==SEGMENTS+1
    for i in range(SEGMENTS):
        bone(f'axial_{i:02}',pts[i],pts[i+1],'root' if i==0 else f'axial_{i-1:02}')
    bone('head',pts[0],cal['landmarks']['humanHeadCenter'],'axial_00')
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(arm.data.bones)==26
    return arm


def bind(obj,arm,points,masks,cal):
    head=set(masks['head'])
    centers=np.array(cal['landmarks']['centerline'])
    delta=np.diff(centers,axis=0)
    lengths=np.linalg.norm(delta,axis=1)
    arc=np.r_[0.,np.cumsum(lengths)]
    stations=(arc[:-1]+arc[1:])*.5
    # The source neck is upright and folds in Y; assigning by Y would mix the
    # skull/neck with low belly. Project on this animal's reviewed 3D centerline.
    projections=[]
    for p in points:
        f=np.clip(np.einsum('ij,ij->i',p-centers[:-1],delta)/lengths**2,0,1)
        q=centers[:-1]+f[:,None]*delta
        nearest=int(np.argmin(np.sum((q-p)**2,axis=1)))
        projections.append(arc[nearest]+f[nearest]*lengths[nearest])
    # Thick native elbow surfaces can be equally near two centerline segments.
    # Diffuse the scalar coordinate along native topology (including seam copies),
    # never positions, so neighboring scales cannot switch axial stations abruptly.
    regularization=cal['weightArcGraphRegularization']
    # Collapse coincident seam copies for scalar computation only. Ordinary
    # neighbor averaging treats UV seam copies with different degrees differently
    # and would itself introduce weight seams despite identical source positions.
    keys,inverse=np.unique(np.round(points,6),axis=0,return_inverse=True)
    # Retained native needle facets require a single affine skin transform:
    # otherwise tiny transverse height amplifies a harmless weight gradient into
    # facet folding. Contract only their WEIGHT-coordinate graph, never geometry.
    faces=np.array([tuple(p.vertices) for p in obj.data.polygons],dtype=int)
    ab=points[faces[:,1]]-points[faces[:,0]]
    ac=points[faces[:,2]]-points[faces[:,0]]
    longest=np.maximum.reduce([np.linalg.norm(ab,axis=1),np.linalg.norm(ac,axis=1),np.linalg.norm(ac-ab,axis=1)])
    quality=np.linalg.norm(np.cross(ab,ac),axis=1)/np.maximum(longest**2,1e-30)
    coupling=cal['thinFacetWeightCoupling']
    needles=faces[(quality<coupling['maximumArea2OverLongestEdgeSquared'])&(longest<coupling['maximumEdgeM'])]
    parent=np.arange(len(keys))
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]
            i=parent[i]
        return i
    for face in inverse[needles]:
        for j in face[1:]:parent[find(j)]=find(face[0])
    _,labels=np.unique([find(i) for i in range(len(keys))],return_inverse=True)
    inverse=labels[inverse]
    counts=np.bincount(inverse)
    keys=np.stack([np.bincount(inverse,weights=points[:,j])/counts for j in range(3)],axis=1)
    coupled_head=np.bincount(inverse,weights=np.isin(np.arange(len(points)),list(head)))>0
    blend_z=keys[:,2]
    edges=np.array([tuple(e.vertices) for e in obj.data.edges],dtype=int)
    unique_edges=np.unique(np.sort(inverse[edges],axis=1),axis=0)
    unique_edges=unique_edges[unique_edges[:,0]!=unique_edges[:,1]]
    neighbors=np.r_[unique_edges,unique_edges[:,::-1]]
    degree=np.bincount(neighbors[:,0],minlength=len(keys))
    coordinate=np.bincount(inverse,weights=np.array(projections))/np.bincount(inverse)
    pinned=keys[:,2]>=cal['headBlendZ'][0]
    strength=regularization['strength']
    for _ in range(regularization['iterations']):
        total=np.bincount(neighbors[:,0],weights=coordinate[neighbors[:,1]],minlength=len(keys))
        mean=total/np.maximum(degree,1)
        coordinate=np.where(pinned|(degree==0),coordinate,(1-strength)*coordinate+strength*mean)
    projections=coordinate[inverse]
    groups={b.name:obj.vertex_groups.new(name=b.name) for b in arm.data.bones}
    weights=[]
    a,b=cal['headBlendZ']
    for i,p in enumerate(points):
        if i in head:
            w={'head':1.}
        else:
            s=projections[i]
            station=float(np.interp(s,stations,np.arange(SEGMENTS)))
            nearest=int(math.floor(station+.5))
            t=station-nearest
            # Quadratic B-spline partition spreads bending over three adjacent
            # bones without the steep two-bone quintic derivative at a station.
            values=[.5*(.5-t)**2,.75-t*t,.5*(.5+t)**2]
            w={}
            for j,value in zip((nearest-1,nearest,nearest+1),values):
                name=f'axial_{min(SEGMENTS-1,max(0,j)):02}'
                w[name]=w.get(name,0.)+value
            h=1. if coupled_head[inverse[i]] else float(smooth((blend_z[inverse[i]]-a)/(b-a)))
            w={name:value*(1-h) for name,value in w.items()}
            w['head']=h
        w={name:value for name,value in w.items() if value>1e-8}
        total=sum(w.values())
        w={name:value/total for name,value in w.items()}
        assert 1<=len(w)<=4 and abs(sum(w.values())-1)<1e-7
        for name,value in w.items():
            groups[name].add([i],value,'REPLACE')
        weights.append(w)
    assert all(weights[i]=={'head':1.} for i in masks['head'])
    modifier=obj.modifiers.new('Source measured axis and complete rigid human skull','ARMATURE')
    modifier.object=arm
    obj.parent=arm
    obj['runtimeContract']=runtime_contract()
    obj['candidateOnly']=True
    return weights


def animate(arm,name,seconds):
    action=base.new_action(arm,name)
    count=round(seconds*FPS)
    previous={}
    for frame in range(count+1):
        p=frame/count
        phase=math.tau*p
        display=math.sin(math.pi*p)**4 if name=='special' else 0.
        walk=name=='walk'
        for pb in arm.pose.bones:
            pb.rotation_mode='QUATERNION'
            pb.location=(0,0,0)
            pb.rotation_quaternion=(1,0,0,0)
            pb.scale=(1,1,1)
        root=arm.pose.bones['root']
        bob=(.006 if walk else .004)*math.sin(phase)
        root.location=root.bone.matrix_local.to_3x3().inverted()@Vector((0,0,bob))
        # Two rounded abdominal pulses at p=1/3 and2/3, with zero C2 endpoint
        # contribution. Paired lower-neck/distal-tail bends move the abdomen
        # coherently instead of scaling its skin or accumulating tail rotation.
        beat=(math.sin(phase)**2*display/.421875) if name=='special' else 0.
        bends=np.zeros(SEGMENTS)
        # Lift the native heavy abdomen as a coherent broad segment. Spread the
        # initiating bend through lower neck and cancel orientation in the thin
        # distal tail, avoiding alternating curvature inside thick belly scales.
        bends[5:9]=.018*np.array([.25,.75,.75,.25])
        bends[16:24]=-.0072*np.array([.25,.5,.75,1.,1.,.75,.5,.25])
        for i in range(SEGMENTS):
            pb=arm.pose.bones[f'axial_{i:02}']
            u=(i+.5)/SEGMENTS
            amplitude=((.004 if walk else .002)+.002*display)*(.15+.85*u)
            lateral=amplitude*math.sin(phase-4.5*u)
            vertical=amplitude*.40*math.sin(phase-4.5*u+.9)+beat*float(bends[i])
            pb.rotation_quaternion=base.world_rot(pb,base.Z,lateral)@base.world_rot(pb,base.X,vertical)
        head=arm.pose.bones['head']
        head.rotation_quaternion=base.world_rot(head,base.Z,(.005+.006*display)*math.sin(phase+.4))@base.world_rot(head,base.Y,.003*math.sin(phase-.6))
        for pb in arm.pose.bones:
            if pb.name in previous and previous[pb.name].dot(pb.rotation_quaternion)<0:
                pb.rotation_quaternion.negate()
            previous[pb.name]=pb.rotation_quaternion.copy()
            for channel in ('location','rotation_quaternion','scale'):
                pb.keyframe_insert(channel,frame=frame)
    base.finish_action(arm,action)
    for curve in base.action_fcurves(action):
        for key in curve.keyframe_points:
            key.interpolation='LINEAR'
    return action


def native_payload(path,source,points,weights,uv,triangles):
    doc,data=shared.glb_read(path)
    native,raw=shared.glb_read(source)
    assert len(native['meshes'])==1 and len(native['meshes'][0]['primitives'])==1
    src=native['meshes'][0]['primitives'][0]
    assert set(src['attributes'])=={'POSITION','NORMAL','TEXCOORD_0'}
    attrs={name:shared.accessor(native,raw,index) for name,index in src['attributes'].items()}
    indices=shared.accessor(native,raw,src['indices']).ravel()
    assert np.array_equal(indices.reshape(-1,3),triangles),'Native/imported index correspondence changed'
    assert np.abs(attrs['TEXCOORD_0']-(uv*[1,-1]+[0,1])).max()<2e-7
    decoded=attrs['POSITION'][:,[0,2,1]]*np.array([1.,-1.,1.])
    low,high=decoded.min(axis=0),decoded.max(axis=0)
    origin=np.array([(low[0]+high[0])/2,(low[1]+high[1])/2,low[2]])
    expected=(decoded-origin)*(LENGTH/(high[1]-low[1]))+[0,0,ELEVATION]
    assert np.abs(expected-points).max()<4e-7
    node=next(n for n in doc['nodes'] if 'mesh' in n and 'skin' in n)
    skin=doc['skins'][node['skin']]
    names={doc['nodes'][index]['name']:i for i,index in enumerate(skin['joints'])}
    joints=np.zeros((len(points),4),dtype='<u2')
    w=np.zeros((len(points),4),dtype='<f4')
    for i,values in enumerate(weights):
        for j,(name,value) in enumerate(values.items()):
            joints[i,j],w[i,j]=names[name],value
    binary=bytearray(data)
    def append(values,kind,component):
        values=np.ascontiguousarray(values)
        binary.extend(b'\x00'*((-len(binary))%4))
        start=len(binary)
        binary.extend(values.tobytes())
        view=len(doc['bufferViews'])
        doc['bufferViews'].append({'buffer':0,'byteOffset':start,'byteLength':values.nbytes})
        index=len(doc['accessors'])
        spec={'bufferView':view,'componentType':component,'count':len(values),'type':kind}
        if kind=='VEC3' and component==5126:
            spec.update(min=values.min(axis=0).tolist(),max=values.max(axis=0).tolist())
        doc['accessors'].append(spec)
        return index
    attributes={'POSITION':append((points[:,[0,2,1]]*[1,1,-1]).astype('<f4'),'VEC3',5126),
        'NORMAL':append(attrs['NORMAL'].astype('<f4'),'VEC3',5126),
        'TEXCOORD_0':append(attrs['TEXCOORD_0'].astype('<f4'),'VEC2',5126),
        'JOINTS_0':append(joints,'VEC4',5123),'WEIGHTS_0':append(w,'VEC4',5126)}
    assert native['accessors'][src['indices']]['componentType']==5123
    index=append(indices.astype('<u2'),'SCALAR',5123)
    primitives=doc['meshes'][node['mesh']]['primitives']
    assert len(primitives)==1
    primitives[0]['attributes'],primitives[0]['indices']=attributes,index
    # Preserve the actual original PBR document and encoded image bytes as well.
    # Blender only supplies a skeleton/animation carrier, never replacement PBR.
    images=[]
    for image in native.get('images',[]):
        assert 'bufferView' in image and 'uri' not in image
        view=native['bufferViews'][image['bufferView']]
        start=view.get('byteOffset',0)
        payload=raw[start:start+view['byteLength']]
        binary.extend(b'\x00'*((-len(binary))%4))
        offset=len(binary); binary.extend(payload)
        bv=len(doc['bufferViews'])
        doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':len(payload)})
        images.append({**image,'bufferView':bv})
    doc['images']=images
    for field in ('materials','textures','samplers'):
        if field in native:
            doc[field]=json.loads(json.dumps(native[field]))
        else:
            doc.pop(field,None)
    primitives[0]['material']=src.get('material',0)
    for field in ('extensionsUsed','extensionsRequired'):
        if field in native:
            doc[field]=sorted(set(doc.get(field,[]))|set(native[field]))
    shared.write_glb(path,doc,binary)
    return {'nativeVertices':len(points),'nativeTriangles':len(triangles),
        'nativeNormalSha256':array_sha(attrs['NORMAL']),'nativeUVSha256':array_sha(attrs['TEXCOORD_0']),
        'nativeIndexSha256':array_sha(indices,'<u2'),'nativeNormalUVIndexBytesPreservedExactly':True,
        'geometryChange':'Positive uniform source normalization and permanent translation only',
        'recoloring':False,'blenderNormalCodecBypassedInActualGltf':True,
        'sourcePbrMaterialTextureSamplerDocumentsCopied':True,'encodedSourceImagesCopiedWithoutReencoding':True}


def remove_rigid_export_roundoff(path):
    """Restore the intended unit-scale/fixed-length bone contract after Blender.

    Bone matrix decomposition introduces ~1e-6 scale and translation jitter even
    when every authored bone scale is1 and all non-root locations are0. Remove
    only that measured numerical noise; rebuild inverse binds from actual emitted
    node rests so the skeleton's native rest stays exact within Float32 tolerance.
    Mesh POSITION/NORMAL/UV/index/PBR buffers are not touched.
    """
    doc,data=shared.glb_read(path)
    binary=bytearray(data)
    max_scale_noise,max_translation_noise=0.,0.
    for node in doc['nodes']:
        scale=np.array(node.get('scale',[1,1,1]))
        max_scale_noise=max(max_scale_noise,float(np.abs(scale-1).max()))
        assert np.abs(scale-1).max()<3e-6
        if 'scale' in node:
            node['scale']=[1.,1.,1.]
    def append(values,kind):
        values=np.asarray(values,dtype='<f4')
        binary.extend(b'\x00'*((-len(binary))%4))
        offset=len(binary)
        binary.extend(values.tobytes())
        view=len(doc['bufferViews'])
        doc['bufferViews'].append({'buffer':0,'byteOffset':offset,'byteLength':values.nbytes})
        index=len(doc['accessors'])
        doc['accessors'].append({'bufferView':view,'componentType':5126,'count':len(values),'type':kind})
        return index
    for animation in doc['animations']:
        for channel in animation['channels']:
            target=channel['target']
            sampler=animation['samplers'][channel['sampler']]
            if target['path']=='scale' or (target['path']=='translation' and doc['nodes'][target['node']].get('name')!='root'):
                raw=shared.accessor(doc,data,sampler['output'])
                values=raw.reshape(-1,3,3)
                expected=np.ones(3) if target['path']=='scale' else np.array(doc['nodes'][target['node']].get('translation',[0,0,0]))
                noise=float(np.abs(values[:,1]-expected).max())
                assert noise<3e-6,(target,noise)
                if target['path']=='scale':
                    max_scale_noise=max(max_scale_noise,noise)
                else:
                    max_translation_noise=max(max_translation_noise,noise)
                cleaned=np.zeros_like(values)
                cleaned[:,1]=expected
                sampler['output']=append(cleaned.reshape(-1,3),'VEC3')
    shared.write_glb(path,doc,binary)
    evaluator=shared.GlbSkin(path)
    matrices=np.linalg.inv(evaluator.globals()[evaluator.bones])
    inverse=matrices.transpose(0,2,1).reshape(-1,16)
    assert len(doc['skins'])==1
    doc['skins'][0]['inverseBindMatrices']=append(inverse,'MAT4')
    shared.write_glb(path,doc,binary)
    return {'maximumDiscardedScaleDecompositionNoise':max_scale_noise,
        'maximumDiscardedNonRootLocalTranslationNoiseM':max_translation_noise,
        'boneScaleExactlyOne':True,'nonRootLocalTranslationsConstant':True,
        'inverseBindsDerivedFromActualEmittedRestTRS':True,'nativeMeshAttributesUntouched':True}


def motion_qa(skin,masks):
    rest=skin.points()
    faces=skin.triangles
    edges=np.unique(np.sort(np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]),axis=1),axis=0)
    lengths=np.linalg.norm(rest[edges[:,0]]-rest[edges[:,1]],axis=1)
    head_ids=np.array(masks['head'])
    anchors=[head_ids[0],head_ids[len(head_ids)//2],head_ids[-1]]
    reference=[np.linalg.norm(rest[head_ids]-rest[index],axis=1) for index in anchors]
    sets={name:set(masks[name]) for name in ('neck','body','tail')}
    selected={name:np.flatnonzero(np.array([a in ids or b in ids for a,b in edges])&(lengths>1e-4)) for name,ids in sets.items()}
    # Include edges crossing each geometric mask boundary, especially the
    # protected-skull/soft-neck junction, instead of omitting the seam itself.
    a,b,c=[rest[faces[:,i]] for i in range(3)]
    area0=np.linalg.norm(np.cross(b-a,c-a),axis=1)
    robust=area0>2e-8
    report={}
    swept_low,swept_high=rest.min(axis=0),rest.max(axis=0)
    for clip,seconds in DURATIONS.items():
        low,high=np.full(3,np.inf),np.full(3,-np.inf)
        movement_low,movement_high=np.full_like(rest,np.inf),np.full_like(rest,-np.inf)
        rigidity,max_speed=0.,0.
        strain={name:0. for name in selected}
        p99={name:0. for name in selected}
        min_area,max_area=1.,1.
        previous=None
        count=round(seconds*120)+1
        for step in range(count):
            points=skin.points(clip,step/120)
            low,high=np.minimum(low,points.min(axis=0)),np.maximum(high,points.max(axis=0))
            movement_low,movement_high=np.minimum(movement_low,points),np.maximum(movement_high,points)
            if previous is not None:
                max_speed=max(max_speed,float(np.linalg.norm(points-previous,axis=1).max())*120)
            previous=points
            for index,original in zip(anchors,reference):
                rigidity=max(rigidity,float(np.abs(np.linalg.norm(points[head_ids]-points[index],axis=1)-original).max()))
            current=np.linalg.norm(points[edges[:,0]]-points[edges[:,1]],axis=1)
            for name,ids in selected.items():
                values=np.abs(current[ids]/lengths[ids]-1)
                strain[name]=max(strain[name],float(values.max()))
                p99[name]=max(p99[name],float(np.quantile(values,.99)))
            if step%4==0:
                a,b,c=[points[faces[:,i]] for i in range(3)]
                ratio=np.linalg.norm(np.cross(b-a,c-a),axis=1)[robust]/area0[robust]
                min_area,max_area=min(min_area,float(ratio.min())),max(max_area,float(ratio.max()))
        dt=.001
        p0,p1,p2,pm2,pm,pe=[skin.points(clip,t) for t in (0,dt,2*dt,seconds-2*dt,seconds-dt,seconds)]
        seam=float(np.linalg.norm(pe-p0,axis=1).max())
        velocity=float(np.linalg.norm((p1-p0)/dt-(pe-pm)/dt,axis=1).max())
        acceleration=float(np.linalg.norm((p2-2*p1+p0)/dt**2-(pe-2*pm+pm2)/dt**2,axis=1).max())
        sweep=np.linalg.norm(movement_high-movement_low,axis=1)
        entry={'samples':count,'samplingHz':120,'boundsBlender':[low.tolist(),high.tolist()],
            'minimumGroundClearanceM':float(low[2]),'maximumSampledVertexSpeedMps':max_speed,
            'completeHumanHeadShapeDistanceErrorM':rigidity,'maximumNativeEdgeLengthRelativeChange':strain,
            'p99NativeEdgeLengthRelativeChange':p99,'robustTriangleAreaRatioRange':[min_area,max_area],
            'allVertexLoopPositionErrorM':seam,'allVertexWrapVelocityDifferenceMps':velocity,
            'allVertexWrapAccelerationDifferenceMps2':acceleration,'oneSidedDifferenceDt':dt,
            'actualCubicBufferContinuity':skin.curve_qa[clip],
            'maximumBodyVertexSweepM':float(sweep[masks['body']].max()),
            'maximumHumanHeadVertexSweepM':float(sweep[head_ids].max()),
            'maximumRegionVertexSweepM':{name:float(sweep[masks[name]].max()) for name in ('head','neck','body','tail')},
            'maximumFirst48EvenlySampledRegionVertexSweepM':{name:float(sweep[np.array(masks[name])[np.linspace(0,len(masks[name])-1,min(48,len(masks[name]))).astype(int)]].max()) for name in ('head','neck','body','tail')}}
        report[clip]=entry
        assert low[2]>.08 and rigidity<1e-4 and seam<1e-5 and velocity<.005 and acceleration<.05,entry
        assert max(strain.values())<.08 and max(p99.values())<.06,entry
        assert .65<min_area<=max_area<1.35,entry
        swept_low,swept_high=np.minimum(swept_low,low),np.maximum(swept_high,high)
    def start_derivatives(clip):
        dt=.001
        a,b,c=[skin.points(clip,t) for t in (0,dt,2*dt)]
        return a,(b-a)/dt,(c-2*b+a)/dt**2
    idle,special=start_derivatives('idle'),start_derivatives('special')
    endpoint={name:float(np.linalg.norm(a-b,axis=1).max()) for name,a,b in zip(('positionM','velocityMps','accelerationMps2'),idle,special)}
    assert endpoint['positionM']<1e-5 and endpoint['velocityMps']<.001 and endpoint['accelerationMps2']<.01,endpoint
    report['specialIdleSafeEndpointMatch']=endpoint
    report['maximumSweptBoundsBlenderSampled']=[swept_low.tolist(),swept_high.tolist()]
    report['maximumSweptBoundsGltfSampled']=[[swept_low[0],swept_low[2],-swept_high[1]],[swept_high[0],swept_high[2],-swept_low[1]]]
    report['sweptBoundsGltfAdvisory1cmPadding']=[(np.array(report['maximumSweptBoundsGltfSampled'][0])-.01).tolist(),(np.array(report['maximumSweptBoundsGltfSampled'][1])+.01).tolist()]
    return report


def reimport_and_render(path,out,skin,masks):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps=FPS
    bpy.context.scene.render.fps_base=1.
    bpy.ops.import_scene.gltf(filepath=str(path),disable_bone_shape=True)
    obj=next(o for o in bpy.context.scene.objects if o.type=='MESH')
    arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
    assert len(arm.data.bones)==26
    actions={}
    for track in arm.animation_data.nla_tracks:
        track.mute=True
        for strip in track.strips:
            for name in DURATIONS:
                if track.name==name or strip.action.name==name:
                    actions[name]=strip.action
    assert set(actions)==set(DURATIONS)
    arm.animation_data.action=None
    camera=shared.camera_setup(900)
    out.mkdir()
    center=np.array([0,0,1.20])
    max_error=0.
    def evaluate(t,clip):
        nonlocal max_error
        frame=t*FPS
        bpy.context.scene.frame_set(int(frame),subframe=frame-int(frame))
        bpy.context.view_layer.update()
        evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        mesh=evaluated.to_mesh()
        points=np.array([tuple(evaluated.matrix_world@v.co) for v in mesh.vertices])
        evaluated.to_mesh_clear()
        assert points.shape==skin.positions.shape
        error=float(np.linalg.norm(points-skin.points(clip,t),axis=1).max())
        max_error=max(max_error,error)
        assert error<.0003,(clip,t,error)
        return points
    for clip,seconds in DURATIONS.items():
        arm.animation_data.action=actions[clip]
        for step in range(8):
            t=seconds*step/8
            points=evaluate(t,clip)
            tag=f'{clip}-{step:02}-t{t:.3f}'
            shared.render_view(camera,out,tag+'-34',center,(1,-.7,.28),3.65)
            if step in (0,2,4,6):
                shared.render_view(camera,out,tag+'-side',center,(1,0,.08),3.65)
                whole=points[masks['head']+masks['neck']]
                target=(whole.min(axis=0)+whole.max(axis=0))/2
                skull=points[masks['head']]
                head_target=(skull.min(axis=0)+skull.max(axis=0))/2
                shared.render_view(camera,out,tag+'-human-head-face-plus-x',head_target,(1,0,.08),1.25)
                shared.render_view(camera,out,tag+'-neck-skull-minus-x',target,(-1,0,.12),1.90)
                shared.render_view(camera,out,tag+'-neck-ear-minus-y',target,(0,-1,.12),1.90)
        for t in (.173,seconds*.317,seconds-.023):
            evaluate(t,clip)
    arm.animation_data.action=None
    return {'boneCount':26,'clipDurations':DURATIONS,'maximumAllVertexVsExactGltfEvaluatorErrorM':max_error,
        'actualReimportRendered':True,'humanHeadAndNeckViewsPerClip':12}


def produce(obj,points,preservation,cal,args,source,out):
    assert cal['anatomyMasksReviewed'] is True
    bpy.context.scene.render.fps=FPS
    bpy.context.scene.render.fps_base=1.
    masks=masks_from_calibration(obj,points,cal)
    normals,uv=shared.per_vertex_attributes(obj)
    triangles=np.array([tuple(p.vertices) for p in obj.data.polygons])
    arm=make_rig(cal)
    weights=bind(obj,arm,points,masks,cal)
    arm.data.pose_position='REST'
    bpy.context.view_layer.update()
    evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    rest=np.array([tuple(evaluated.matrix_world@v.co) for v in evaluated.data.vertices])
    assert np.linalg.norm(rest-points,axis=1).max()<1e-6,'Native rest inversion'
    arm.data.pose_position='POSE'
    report={'schemaVersion':1,'beast':'leishen','candidateOnly':True,'productionAccepted':False,
        'source':str(source),'sourceSha256':sha(source),'script':str(Path(__file__).resolve()),
        'scriptSha256':sha(Path(__file__).resolve()),'calibrationSha256':sha(args.calibration.resolve()),
        'helperSha256':{name:sha(TRUSTED/name) for name in ('rig_yinglong_native.py','rig_jiaochong_native.py','rig_quadruped.py','rig_zhuyan_native.py','turnaround.py')},
        'blenderVersion':bpy.app.version_string,'preservation':preservation,'runtimeContract':runtime_contract(),
        'bones':[{'name':b.name,'parent':b.parent.name if b.parent else None,'headBlender':list(b.head_local),'tailBlender':list(b.tail_local)} for b in arm.data.bones],
        'weights':{'unweighted':0,'maxInfluences':max(map(len,weights)),'completeHumanHeadRigid':True,'noNonUnitAnimatedBoneScales':True},
        'maskCounts':{name:len(ids) for name,ids in masks.items()}}
    dump(out/'calibration.json',cal)
    (out/'rest-reference.json').write_text(json.dumps({'schemaVersion':1,'beast':'leishen','sourceSha256':report['sourceSha256'],
        'calibrationSha256':report['calibrationSha256'],'coordinates':COORDINATES,
        'gltfConversion':'[x,z,-y]; positions are normalized native world rest INCLUDING permanent elevation',
        'indexDomain':'points/masks use native source Blender vertex order before weights; match decoded/dequantized world rest positions after skin inverse-bind, not compressed GLB vertex order',
        'maskMethod':'Native edges and coincident seam duplicates rounded6 decimals; reviewed half-plane cuts/seeds in calibration; computed before weights',
        'points':np.round(points,9).tolist(),'masks':masks,
        'maskSemantics':{'head':'Complete native human face +X, skull, both eyes/ears, lips, chin and hair; conservative horizontal lower-nape cut includes a short native neck collar',
            'neck':'Upright curved native blue-gray neck below the protected human head, selected geometrically by Z, not by Y or weights',
            'body':'Every native non-head vertex, including upright neck, low belly and single tapering tail','tail':'Native posterior body selected by calibration tailMaskStartY',
            'all_native':'Every source vertex, retaining tiny native fragments'}},separators=(',',':'))+'\n')
    dump(out/'weights-audit.json',report['weights'])
    diagnostic(obj,points,masks,cal,out/'masks')
    assert shared.native_fingerprint(obj)==preservation['normalizedFingerprint']
    actions={name:animate(arm,name,seconds) for name,seconds in DURATIONS.items()}
    arm.animation_data.action=None
    for pb in arm.pose.bones:
        pb.location=(0,0,0)
        pb.rotation_quaternion=(1,0,0,0)
        pb.scale=(1,1,1)
    bpy.context.view_layer.update()
    assert shared.native_fingerprint(obj)==preservation['normalizedFingerprint']
    assert array_sha([tuple(v.co) for v in obj.data.vertices])==preservation['restPositionsSha256']
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    arm.select_set(True)
    path=out/'rigged.glb'
    bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB',use_selection=True,export_animations=True,
        export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False,export_extras=True,
        export_normals=True,export_texcoords=True,export_materials='EXPORT',export_image_format='AUTO',
        export_apply=False,export_force_sampling=True,export_frame_step=1,export_optimize_animation_size=False)
    report['nativeAttributePassthrough']=native_payload(path,source,points,weights,uv,triangles)
    report['clips']=shared.cubic_export(path)
    report['rigidExportRoundoffCleanup']=remove_rigid_export_roundoff(path)
    skin=shared.GlbSkin(path)
    skin.path=str(path)
    for curves in skin.animations.values():
        for node,channel,times,data in curves:
            if channel=='scale':
                assert np.abs(data[:,1]-1).max()<1e-7 and np.abs(data[:,[0,2]]).max()<1e-7
    imported_masks,report['nativeRestQA']=shared.rest_audit(skin,source,points,normals,uv,triangles,masks)
    report['nativeRestQA']['degenerateDisclosure']='All stored native zero/nearly-zero facets are retained exactly; the evaluated rest count can cross the1e-14m2 threshold due to Float32 inverse-bind roundoff. No geometric or manifold repair.'
    assert report['nativeRestQA']['nativePBR']==report['nativeRestQA']['candidatePBR'],'Native PBR/image bytes changed'
    dump(out/'native-rest-qa.json',report['nativeRestQA'])
    report['motionQA']=motion_qa(skin,imported_masks)
    dump(out/'numerical-qa.json',report['motionQA'])
    report['reimport']=reimport_and_render(path,out/'reimport-poses',skin,imported_masks)
    magick=shutil.which('magick')
    if magick:
        for clip in DURATIONS:
            images=sorted((out/'reimport-poses').glob(clip+'-*-34.png'))
            assert len(images)==8
            subprocess.run([magick,'(',*[str(p) for p in images[:4]],'+append',')','(',*[str(p) for p in images[4:]],'+append',')',
                '-append','-resize','1800x900',str(out/(clip+'-contact.png'))],check=True,timeout=60)
    report['candidateSha256']=sha(path)
    report['candidateBytes']=path.stat().st_size
    report['restReferenceSha256']=sha(out/'rest-reference.json')
    report['qaPassed']=True
    report['reproduceArgv']=[bpy.app.binary_path,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1',
        '--python',str(Path(__file__).resolve()),'--',str(source),str(out.with_name(out.name+'-reproduce')),
        '--calibration',str(args.calibration.resolve()),'--accepted-source-sha256',report['sourceSha256']]
    report['limitations']=['Offline rigging candidate only; actual Stage/shader/crossfade/compression/release acceptance belongs to parent.',
        'Native complete human face +X, upright curved neck, Y-long blue-gray body, single pointed tail and all source degenerate facets are retained; no source shape or axis correction.',
        'Bounds are120Hz sampled extrema with1cm advisory padding, not an analytical extrema certificate.',
        'C2 periodic spline construction has disclosed Float32 output timing/tangent residuals; all actual buffer values and tangents close exactly.',
        'Native PNG/PBR candidate is uncompressed; parent must meet runtime asset budget without changing anatomy and rerun QA against rest-reference.json.']
    report['images']={str(p.relative_to(out)):sha(p) for p in out.rglob('*.png')}
    dump(out/'audit.json',report)
    print('LEISHEN_NATIVE_CANDIDATE',json.dumps({k:v for k,v in report.items() if k not in ('preservation','images','bones')}),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('output',type=Path)
    modes=p.add_mutually_exclusive_group()
    modes.add_argument('--inspect',action='store_true')
    modes.add_argument('--calibrate',action='store_true')
    p.add_argument('--calibration',type=Path)
    p.add_argument('--accepted-source-sha256')
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    source,out=args.source.resolve(strict=True),args.output.resolve()
    assert source.is_relative_to(ROOT/'raw') and source.suffix=='.glb'
    assert out.is_relative_to(ROOT/'raw/_build') and not out.exists(),'Use NEW raw/_build output'
    source_hash=sha(source)
    if not args.inspect:
        assert args.calibration and args.accepted_source_sha256==source_hash
        cal=json.loads(args.calibration.resolve().read_text())
        assert cal['schemaVersion']==1 and cal['beast']=='leishen' and cal['sourceSha256']==source_hash
        assert cal['acceptedForRiggingOnly'] is True and cal['coordinates']==COORDINATES
    out.mkdir(parents=True)
    obj,points,preservation=load_source(source)
    if args.inspect:
        inspect(obj,points,out)
        dump(out/'preservation.json',preservation)
    elif args.calibrate:
        masks=masks_from_calibration(obj,points,cal,review=False)
        cal['anatomyMasksReviewed']=False
        diagnostic(obj,points,masks,cal,out/'masks')
        dump(out/'calibrated.json',cal)
        dump(out/'mask-summary.json',{name:shared.describe(points,ids) for name,ids in masks.items()})
    else:
        produce(obj,points,preservation,cal,args,source,out)
    assert sha(source)==source_hash


if __name__=='__main__':
    main()
