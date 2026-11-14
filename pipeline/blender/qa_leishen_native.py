"""Dedicated offline Leishen localized strain and compressed-candidate audit.
Trusted code; run with Blender factory-startup/disable-autoexec, new raw/_build outputs.
"""
import argparse
import json
import math
import sys
from pathlib import Path
sys.dont_write_bytecode=True
TRUSTED=Path(__file__).resolve().parent
sys.path.insert(0,str(TRUSTED))
import bpy
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree
import rig_leishen_native as rig
shared=rig.shared
ROOT=TRUSTED.parents[1]
SOURCE_SHA='454cee9efe4a0f60324ccb3d6cfb69c2bf217e34c44d2df6f2835c21ae429c9e'


def geometry_mapping(skin,reference,tolerance):
    native=np.array(reference['points'],dtype=float)
    rest=skin.points()
    tree=KDTree(len(native))
    for i,p in enumerate(native):tree.insert(p,i)
    tree.balance()
    mapping=[];maximum=0.
    for p in rest:
        _,i,error=tree.find(p)
        assert error<tolerance,('rest match',error)
        mapping.append(i);maximum=max(maximum,error)
    reverse=KDTree(len(rest))
    for i,p in enumerate(rest):reverse.insert(p,i)
    reverse.balance()
    reverse_error=max(reverse.find(p)[2] for p in native)
    assert reverse_error<tolerance,('missing native geometry',reverse_error)
    mapping=np.array(mapping)
    masks={name:np.flatnonzero(np.isin(mapping,ids)).tolist() for name,ids in reference['masks'].items()}
    assert all(masks.values())
    return mapping,masks,{'method':'Bidirectional nearest independent native rest WORLD positions, no weight or vertex-order selection','maximumForwardErrorM':maximum,'maximumReverseErrorM':reverse_error,'toleranceM':tolerance}


def actions_from_import(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps=rig.FPS
    bpy.ops.import_scene.gltf(filepath=str(path),disable_bone_shape=True)
    obj=next(o for o in bpy.context.scene.objects if o.type=='MESH')
    arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
    actions={}
    for track in arm.animation_data.nla_tracks:
        track.mute=True
        for strip in track.strips:
            for name in rig.DURATIONS:
                if track.name==name or strip.action.name==name:actions[name]=strip.action
    assert set(actions)==set(rig.DURATIONS)
    arm.animation_data.action=None
    return obj,arm,actions


def mark_edge(points,edge):
    material=bpy.data.materials.new('QA edge overlay only')
    material.diffuse_color=(.9,.01,.015,1)
    material.use_nodes=True
    shader=material.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value=(.9,.01,.015,1)
    shader.inputs['Emission Color'].default_value=(.9,.01,.015,1)
    shader.inputs['Emission Strength'].default_value=.5
    a,b=[Vector(points[i]) for i in edge]
    delta=b-a
    bpy.ops.mesh.primitive_cylinder_add(vertices=12,radius=.00065,depth=delta.length,location=(a+b)/2)
    line=bpy.context.object
    line.rotation_quaternion=delta.to_track_quat('Z','Y')
    line.rotation_mode='QUATERNION'
    line.rotation_quaternion=delta.to_track_quat('Z','Y')
    line.data.materials.append(material)
    items=[line]
    for p in (a,b):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12,ring_count=8,radius=.0012,location=p)
        item=bpy.context.object;item.data.materials.append(material);items.append(item)
    return items


def strain(path,reference,out):
    skin=shared.GlbSkin(path)
    mapping,masks,match=geometry_mapping(skin,reference,2e-6)
    rest=skin.points()
    faces=skin.triangles
    edges=np.unique(np.sort(np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]),axis=1),axis=0)
    lengths=np.linalg.norm(rest[edges[:,0]]-rest[edges[:,1]],axis=1)
    body=set(masks['body'])
    ids=np.flatnonzero(np.array([a in body or b in body for a,b in edges])&(lengths>1e-4))
    worst={'relativeChange':-1.}
    for clip,seconds in rig.DURATIONS.items():
        for step in range(round(seconds*120)+1):
            points=skin.points(clip,step/120)
            current=np.linalg.norm(points[edges[ids,0]]-points[edges[ids,1]],axis=1)
            values=np.abs(current/lengths[ids]-1)
            j=int(np.argmax(values))
            if values[j]>worst['relativeChange']:
                edge=edges[ids[j]]
                worst={'clip':clip,'timeSeconds':step/120,'sample':step,'relativeChange':float(values[j]),
                    'signedRelativeChange':float(current[j]/lengths[ids[j]]-1),'candidateEdgeIndices':edge.tolist(),
                    'nativeRestMatchedIndices':mapping[edge].tolist(),'restLengthM':float(lengths[ids[j]]),'posedLengthM':float(current[j]),
                    'absoluteLengthChangeM':float(abs(current[j]-lengths[ids[j]])),
                    'restEndpointsBlender':rest[edge].tolist(),'posedEndpointsBlender':points[edge].tolist()}
    edge=np.array(worst['candidateEdgeIndices'])
    worst['jointWeights']=[{skin.doc['nodes'][skin.bones[j]]['name']:float(w) for j,w in zip(skin.joints[i],skin.weights[i]) if w>0} for i in edge]
    p=rest[edge].mean(axis=0)
    local=np.flatnonzero(np.linalg.norm(rest-p,axis=1)<.10)
    worst['localRadiusM']=.10;worst['localVertexCount']=len(local)
    worst['reportScope']='Absolute largest body-mask native edge strain across all three clips at120Hz; includes crossing region boundaries; ignores only edges<=0.1mm as original QA'
    shared.dump(out/'strain-location.json',worst)
    obj,arm,actions=actions_from_import(path)
    camera=shared.camera_setup(1000)
    for state in ('rest','peak'):
        arm.animation_data.action=None if state=='rest' else actions[worst['clip']]
        if state=='rest':
            for pb in arm.pose.bones:
                pb.location=(0,0,0);pb.rotation_quaternion=(1,0,0,0);pb.scale=(1,1,1)
        t=0. if state=='rest' else worst['timeSeconds']
        frame=t*rig.FPS
        bpy.context.scene.frame_set(int(frame),subframe=frame-int(frame));bpy.context.view_layer.update()
        points=rest if state=='rest' else skin.points(worst['clip'],t)
        target=points[edge].mean(axis=0)
        # Both sides of the belly and a ventral view locate the physical edge.
        for tag,direction in [('plus-x',(1,0,.25)),('minus-x',(-1,0,.2)),('underside',(.2,0,-1))]:
            shared.render_view(camera,out,state+'-local-'+tag,target,direction,.22)
        shared.render_view(camera,out,state+'-context',target,(1,-.4,.25),.75)
        markers=mark_edge(points,edge)
        for tag,direction in [('plus-x',(1,0,.25)),('minus-x',(-1,0,.2)),('underside',(.2,0,-1))]:
            shared.render_view(camera,out,state+'-marked-'+tag,target,direction,.10)
        for item in markers:bpy.data.objects.remove(item,do_unlink=True)
    shared.dump(out/'audit.json',{'candidateSha256':shared.sha(path),'scriptSha256':shared.sha(Path(__file__)),'restMapping':match,'worst':worst,'candidateOnly':True})
    print('LEISHEN_STRAIN',json.dumps(worst),flush=True)


def normal_world(skin):
    transforms=skin.globals()[skin.bones]@skin.inverse_bind
    linear=np.einsum('nvij,nv->nij',transforms[skin.joints][...,:3,:3],skin.weights)
    normal=np.einsum('nij,nj->ni',np.linalg.inv(linear).transpose(0,2,1),skin.normals)
    length=np.linalg.norm(normal,axis=1)
    assert length.min()>1e-6
    return normal/length[:,None]


def belly_sequence(path,skin,masks,out):
    rest=skin.points()
    abdomen=np.flatnonzero((rest[:,1]>-.95)&(rest[:,1]<.35)&(rest[:,2]<.85))
    assert len(abdomen)>100
    maximum=0.;peak=None;series=[]
    for step in range(721):
        t=step/120
        special=skin.points('special',t)
        idle=skin.points('idle',t)
        delta=special[abdomen]-idle[abdomen]
        value=float(np.abs(delta[:,2]).max())
        if value>maximum:maximum=value;peak=t
        if step%30==0:series.append({'t':t,'maximumVerticalDifferenceFromSynchronizedIdleM':value,'maximumAllAxisDifferenceM':float(np.linalg.norm(delta,axis=1).max())})
    obj,arm,actions=actions_from_import(path)
    arm.animation_data.action=actions['special']
    camera=shared.camera_setup(1000)
    out.mkdir()
    target=(rest[abdomen].min(axis=0)+rest[abdomen].max(axis=0))/2
    for t in (0.,.75,1.5,2.,2.5,3.,3.5,4.,4.5,5.25,6.):
        frame=t*rig.FPS;bpy.context.scene.frame_set(int(frame),subframe=frame-int(frame));bpy.context.view_layer.update()
        shared.render_view(camera,out,f'special-belly-t{t:04.2f}',target,(1,0,.05),1.7)
    result={'anatomySelection':'Independent native-world low abdomen: -.95<Y<.35, Z<.85; no weights used','vertices':len(abdomen),'maximumAbdominalVerticalDifferenceFromSynchronizedIdleM':maximum,'peakTimeSeconds':peak,'series':series,'pulseTargetsSeconds':[2.,4.],'boneScaleOrGeometryChanges':False}
    shared.dump(out/'belly-motion.json',result)
    return result


def compressed(path,reference,out,original):
    skin=shared.GlbSkin(path)
    raw=shared.GlbSkin(original)
    assert len(skin.bones)==len(raw.bones)==26
    assert len(skin.positions)==len(raw.positions)==50983
    assert len(skin.triangles)==len(raw.triangles)==50000
    mapping,masks,match=geometry_mapping(skin,reference,.00025)
    raw_mapping,_,_=geometry_mapping(raw,reference,2e-6)
    source_rest=np.array(reference['points'])
    # Independent world-position mapping establishes masks first. Attributes only
    # disambiguate coincident source seam copies in the subsequent UV/normal audit.
    tree=KDTree(len(source_rest))
    for i,p in enumerate(source_rest):tree.insert(p,i)
    tree.balance()
    raw_by_native={}
    for i,native in enumerate(raw_mapping):raw_by_native.setdefault(int(native),[]).append(i)
    n0,n1=normal_world(raw),normal_world(skin)
    matched=[];uv_error=0.;normal_angle=0.;rest_error=0.
    raw_rest=raw.points();candidate_rest=skin.points()
    for i,p in enumerate(candidate_rest):
        near=tree.find_range(p,.00025)
        possibilities=[j for _,native,_ in near for j in raw_by_native.get(native,[])]
        assert possibilities
        j=min(possibilities,key=lambda j:float(np.linalg.norm(skin.uv[i]-raw.uv[j]))*10+float(np.linalg.norm(n1[i]-n0[j]))*.1+float(np.linalg.norm(p-raw_rest[j])))
        matched.append(j)
        uv_error=max(uv_error,float(np.abs(skin.uv[i]-raw.uv[j]).max()))
        angle=math.degrees(math.acos(float(np.clip(np.dot(n1[i],n0[j]),-1,1))))
        normal_angle=max(normal_angle,angle)
        rest_error=max(rest_error,float(np.linalg.norm(p-raw_rest[j])))
    assert uv_error<.0003 and normal_angle<2. and rest_error<.00025,(uv_error,normal_angle,rest_error)
    names=lambda s:[s.doc['nodes'][i]['name'] for i in s.bones]
    assert names(skin)==names(raw)
    bone_error=float(np.abs(skin.globals()[skin.bones]-raw.globals()[raw.bones]).max())
    assert bone_error<2e-6,bone_error
    for s in (skin,raw):
        for i in s.bones:assert np.abs(np.array(s.doc['nodes'][i].get('scale',[1,1,1]))-1).max()<2e-6
        for curves in s.animations.values():
            for node,channel,times,data in curves:
                if channel=='scale' and node in s.bones:assert np.abs(data[:,1]-1).max()<2e-6
    hierarchy=lambda s:[(s.doc['nodes'][i]['name'],s.doc['nodes'][s.parent[i]].get('name')) for i in s.bones]
    assert hierarchy(skin)==hierarchy(raw)
    report={'candidateOnly':True,'scriptSha256':shared.sha(Path(__file__)),'decodedCandidateSha256':shared.sha(path),'sourceRigSha256':shared.sha(original),'referenceSha256':reference['_fileSha256'],'restMapping':match,'attributeCorrespondence':{'uvMaximumComponentError':uv_error,'worldNormalMaximumAngleDegrees':normal_angle,'maximumMatchedRestPositionErrorM':rest_error},'skeleton':{'bones':26,'hierarchyPreserved':True,'maximumBoneRestMatrixError':bone_error,'unitBoneScales':True},'motionQA':rig.motion_qa(skin,masks)}
    matched=np.array(matched)
    errors={}
    for clip,seconds in rig.DURATIONS.items():
        error=0.
        for step in range(round(seconds*120)+1):
            t=step/120
            error=max(error,float(np.linalg.norm(skin.points(clip,t)-raw.points(clip,t)[matched],axis=1).max()))
        assert error<.0015,(clip,error)
        errors[clip]=error
    report['maximumAnimatedVertexDifferenceVsUncompressedM']=errors
    shared.dump(out/'numerical-qa.json',report)
    report['reimport']=rig.reimport_and_render(path,out/'reimport-poses',skin,masks)
    report['bellyMotion']=belly_sequence(path,skin,masks,out/'belly-sequence')
    report['qaPassed']=True
    shared.dump(out/'audit.json',report)
    print('LEISHEN_COMPRESSED_QA',json.dumps(report),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['strain','compressed','belly'])
    p.add_argument('candidate',type=Path)
    p.add_argument('reference',type=Path)
    p.add_argument('output',type=Path)
    p.add_argument('--original',type=Path)
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    out=args.output.resolve();path=args.candidate.resolve(strict=True)
    assert out.is_relative_to(ROOT/'raw/_build') and not out.exists()
    reference=json.loads(args.reference.read_text())
    reference['_fileSha256']=shared.sha(args.reference)
    assert reference['sourceSha256']==SOURCE_SHA and reference['beast']=='leishen'
    out.mkdir(parents=True)
    if args.mode=='strain':strain(path,reference,out)
    elif args.mode=='compressed':
        assert args.original
        compressed(path,reference,out,args.original.resolve(strict=True))
    else:
        skin=shared.GlbSkin(path)
        _,masks,_=geometry_mapping(skin,reference,2e-6)
        belly_sequence(path,skin,masks,out/'belly-sequence')

if __name__=='__main__':main()
