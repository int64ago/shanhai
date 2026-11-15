"""Numerical Longzhi skin QA using independently prepared rest-surface regions.
Anatomical counts require actual image review; labels alone never certify anatomy.
"""
import argparse,json,sys,math
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import rig_longzhi as rig


def main():
    p=argparse.ArgumentParser();p.add_argument('candidate',type=Path);p.add_argument('output',type=Path);p.add_argument('--reference',required=True,type=Path);args=p.parse_args(sys.argv[sys.argv.index('--')+1:]);ref=json.loads(args.reference.read_text());args.output.mkdir(parents=True,exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True);bpy.context.scene.render.fps=rig.FPS;bpy.ops.import_scene.gltf(filepath=str(args.candidate));obj=next(o for o in bpy.context.scene.objects if o.type=='MESH');arm=next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
    actions={}
    for track in arm.animation_data.nla_tracks:
        track.mute=True
        for strip in track.strips:
            if track.name in rig.DURATIONS:actions[track.name]=strip.action
    assert set(actions)==set(rig.DURATIONS),list(actions)
    arm.animation_data.action=None
    for pb in arm.pose.bones:pb.rotation_mode='QUATERNION';pb.rotation_quaternion=(1,0,0,0)
    bpy.context.view_layer.update()
    def points():
        deps=bpy.context.evaluated_depsgraph_get();evaluated=obj.evaluated_get(deps);mesh=evaluated.to_mesh();values=np.empty(len(mesh.vertices)*3,np.float32);mesh.vertices.foreach_get('co',values);values=values.reshape(-1,3);matrix=np.array(evaluated.matrix_world);values=values@matrix[:3,:3].T+matrix[:3,3];evaluated.to_mesh_clear();return values
    rest=points();tree=KDTree(len(ref['restPoints']))
    for i,point in enumerate(ref['restPoints']):tree.insert(point,i)
    tree.balance();mapping=[];error=0
    for point in rest:
        _,i,d=tree.find(point);mapping.append(i);error=max(error,d)
    assert error<.0003,error
    labels=np.array(ref['regionLabels'])[mapping];regions=ref['regions'];heads={};tails={}
    for i,r in enumerate(regions,1):
        ids=np.flatnonzero(labels==i);assert len(ids)>100
        if r['role']=='head':
            root=np.array(r['root']);axis=np.array(r['collar'])-root;t=(rest[ids]-root)@axis/(axis@axis);heads[r['name']]=ids[t>.98]
        else:tails[r['name']]=ids
    assert len(heads)==len(tails)==9
    assert all(len(ids)>100 for ids in heads.values())
    body=np.flatnonzero(labels==0);low=body[rest[body,2]<.035];middle=(rest[low,1].min()+rest[low,1].max())/2;feet={}
    for fb in ('front','back'):
        for side in ('l','r'):
            ids=low[((rest[low,1]<middle)==(fb=='front'))&((rest[low,0]>0)==(side=='l'))];assert len(ids)>10;feet[fb+'_'+side]=ids
    edges=np.array([e.vertices[:] for e in obj.data.edges]);lengths=np.linalg.norm(rest[edges[:,0]]-rest[edges[:,1]],axis=1);valid=lengths>.001;edges=edges[valid];lengths=lengths[valid]
    report={'candidate':str(args.candidate),'reference':str(args.reference),'restMatchMaximumErrorM':error,'vertices':len(rest),'triangles':sum(len(f.vertices)-2 for f in obj.data.polygons),'bones':len(arm.data.bones),'regionVertexCounts':{r['name']:int(np.sum(labels==i)) for i,r in enumerate(regions,1)},'anatomyVisuallyAccepted':False,'clips':{},'failures':[]}
    expected_bones=5+12+27+45
    assert len(arm.data.bones)==expected_bones
    groups={g.index:g.name for g in obj.vertex_groups};maximum_weight_error=0
    for v in obj.data.vertices:
        weights=[g.weight for g in v.groups if groups[g.group] in arm.data.bones];assert weights and all(math.isfinite(w) and w>=0 for w in weights);maximum_weight_error=max(maximum_weight_error,abs(sum(weights)-1))
    assert maximum_weight_error<.0001;report['maximumWeightError']=maximum_weight_error
    phases={'back_l':0,'front_l':.25,'back_r':.5,'front_r':.75}
    for name,seconds in rig.DURATIONS.items():
        arm.animation_data.action=actions[name];max_head=0.;max_strain=0.;max_sole_z=0.;max_stance_y=0.;max_sole_shape=0.;max_world_stance=0.;min_ground=1.;start=None;end=None;worst=None;anchors={}
        for step in range(round(seconds*30)+1):
            t=step/30;frame=t*rig.FPS;bpy.context.scene.frame_set(int(frame),subframe=frame-int(frame));bpy.context.view_layer.update();posed=points();assert np.isfinite(posed).all()
            if step==0:start=posed.copy()
            end=posed.copy();min_ground=min(min_ground,float(posed[:,2].min()));strain=np.abs(np.linalg.norm(posed[edges[:,0]]-posed[edges[:,1]],axis=1)/lengths-1);
            if float(strain.max())>max_strain:
                j=int(np.argmax(strain));max_strain=float(strain[j]);worst={'timeSeconds':t,'restEndpoints':rest[edges[j]].tolist(),'posedEndpoints':posed[edges[j]].tolist(),'restLengthM':float(lengths[j]),'posedLengthM':float(np.linalg.norm(posed[edges[j,0]]-posed[edges[j,1]]))}
            for ids in heads.values():
                for anchor in ids[[0,len(ids)//2,-1]]:
                    drift=np.abs(np.linalg.norm(posed[ids]-posed[anchor],axis=1)-np.linalg.norm(rest[ids]-rest[anchor],axis=1));max_head=max(max_head,float(drift.max()))
            for foot,ids in feet.items():
                phase=(t/seconds+phases[foot])%1
                if name!='walk' or phase<rig.DUTY:
                    def rotate(values,angle):
                        c,s=math.cos(angle),math.sin(angle);rotation=np.array([[c,-s,0],[s,c,0],[0,0,1]]);center=np.array([rig.RADIUS,0,0]);return (values-center)@rotation.T+center
                    relative=seconds*(phase-rig.DUTY/2) if name=='walk' else 0
                    expected=rotate(rest[ids],-rig.SPEED/rig.RADIUS*relative) if name=='walk' else rest[ids]
                    delta=posed[ids]-expected
                    max_sole_z=max(max_sole_z,float(np.abs(delta[:,2]).max()));max_stance_y=max(max_stance_y,float(np.linalg.norm(delta,axis=1).max()));max_sole_shape=max(max_sole_shape,float(np.abs(delta-delta.mean(axis=0)).max()))
                    world=rotate(posed[ids],rig.SPEED/rig.RADIUS*t) if name=='walk' else posed[ids]
                    key=(foot,math.floor(t/seconds+phases[foot]))
                    if key not in anchors:anchors[key]=world.copy()
                    max_world_stance=max(max_world_stance,float(np.linalg.norm(world-anchors[key],axis=1).max()))
        result={'worstEdge':worst,'durationSeconds':seconds,'samples':round(seconds*30)+1,'maximumCompleteSkullDistanceDriftM':max_head,'maximumEdgeRelativeStrainAbove1mm':max_strain,'minimumSoleHeightM':min_ground,'maximumStanceSoleVerticalDriftM':max_sole_z,'maximumStancePositionErrorM':max_stance_y,'maximumWorldStancePositionDriftM':max_world_stance,'maximumStanceFootShapeDriftM':max_sole_shape,'loopPositionSeamM':float(np.linalg.norm(end-start,axis=1).max())};report['clips'][name]=result
        for condition,label in [(max_head<.001,'skull rigidity'),(max_sole_z<.0007,'sole vertical drift'),(max_strain<.80,'localized edge strain'),(max_stance_y<.003,'stance translation'),(max_world_stance<.0007,'world planted stance'),(max_sole_shape<.001,'flat paw'),(min_ground>-.003,'ground penetration'),(result['loopPositionSeamM']<.001,'loop seam')]:
            if not condition:report['failures'].append(name+': '+label)
    report['passed']=not report['failures'];(args.output/'numerical-qa.json').write_text(json.dumps(report,indent=2)+'\n');print('LONGZHI_QA',json.dumps(report),flush=True)
    assert report['passed'],report['failures']

if __name__=='__main__':main()
