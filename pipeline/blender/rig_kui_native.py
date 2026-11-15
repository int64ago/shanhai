"""Native v10 Kui: one planted IK leg, bounded hopping, eight-bone ox tail.
Unified builder CLI: INPUT OUTPUT --preview PREVIEW.png. Native surface retained.
"""
import argparse
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Vector
import rig_quadruped as base
from rig_jimeng_native import native_fingerprint
from rig_shuhu_native import activate, smooth, weights_for, contact, render_view

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT/'raw/_build/kui-v10-rig-qa'
FPS, LENGTH, RADIUS, SPEED, DUTY = 30, 1.6, .65, .16, .60
DURATIONS = {'idle':4.,'walk':1.8,'special':4.8}


def make_rig(obj):
    local = np.array([tuple(v.co) for v in obj.data.vertices])
    matrix = np.asarray(obj.matrix_world)
    points = local @ matrix[:3,:3].T + matrix[:3,3]
    scale = float(np.ptp(points,axis=0).max()); p = points/scale
    ankle_band = p[(p[:,2]>.105)&(p[:,2]<.125)]
    ankle = Vector(tuple((ankle_band.min(axis=0)+ankle_band.max(axis=0))/2))*scale
    tail = np.array([(0,.37,.78),(0,.435,.72),(0,.455,.65),(0,.46,.58),
                     (0,.47,.51),(0,.475,.44),(0,.48,.38),(0,.48,.33),(0,.49,.28)])
    for i in range(2,len(tail)):
        band = p[(np.abs(p[:,2]-tail[i,2])<.012)&(p[:,1]>.425)]
        if len(band)>5: tail[i,:2]=(np.quantile(band[:,:2],.05,axis=0)+np.quantile(band[:,:2],.95,axis=0))/2
    tail *= scale
    arm = bpy.data.objects.new('kui_native_rig',bpy.data.armatures.new('kui_native_rig'))
    bpy.context.scene.collection.objects.link(arm);activate(arm);bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.data.edit_bones
    def bone(name,a,b,parent=None,deform=True):
        item=eb.new(name);item.head,item.tail=Vector(a),Vector(b);item.use_deform=deform
        if parent:item.parent=eb[parent]
    def v(x,y,z):return Vector((x,y,z))*scale
    bone('root',v(0,0,0),v(0,0,.12),deform=False)
    bone('body',v(0,.18,.67),v(0,0,.65),'root')
    bone('chest',v(0,0,.65),v(0,-.25,.70),'body')
    bone('neck',v(0,-.25,.70),v(0,-.33,.76),'chest')
    bone('head',v(0,-.33,.76),v(0,-.49,.70),'neck')
    bone('central_upper',v(0,.012,.55),v(0,-.01,.32),'body')
    bone('central_lower',v(0,-.01,.32),ankle,'central_upper')
    bone('central_foot',ankle,v(0,-.045,.025),'central_lower')
    for i in range(8):bone(f'tail_{i:02d}',tail[i],tail[i+1],'body' if i==0 else f'tail_{i-1:02d}')
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm,p,scale,tail


def constrain_skin(obj,arm,p,scale):
    names=[b.name for b in arm.data.bones if b.use_deform];cols={n:i for i,n in enumerate(names)}
    w=np.zeros((len(p),len(names)),dtype=np.float32)
    def values(subset):return weights_for(p*scale,[arm.data.bones[n] for n in subset])
    axial=['body','chest','neck','head'];w[:,[cols[n] for n in axial]]=values(axial)
    # All facial details share one transform. A broad neck blend prevents a cuff.
    head=(p[:,1]<-.31)&(p[:,2]>.59)
    head_weight=(1-smooth(-.35,-.28,p[:,1]))*smooth(.57,.65,p[:,2])
    w*=1-head_weight[:,None];w[:,cols['head']]+=head_weight
    leg=(p[:,2]<.61)&(np.abs(p[:,0])<.145)&(p[:,1]<.20)&(p[:,1]>-.20)
    leg_names=['central_upper','central_lower','central_foot']
    limb=values(leg_names)
    blend=(1-smooth(.37,.62,p[:,2]))*(1-smooth(.085,.145,np.abs(p[:,0])))*(1-smooth(.11,.22,np.abs(p[:,1]-.01)))
    w*=1-blend[:,None]
    w[:,[cols[n] for n in leg_names]]+=limb*blend[:,None]
    # Native hoof, sole and rear dewclaw stay rigid. Blend through the fetlock.
    foot=(p[:,2]<.125);foot_blend=(1-smooth(.11,.20,p[:,2]))*leg
    w*=1-foot_blend[:,None];w[:,cols['central_foot']]+=foot_blend
    w[foot]=0;w[foot,cols['central_foot']]=1
    tail=(p[:,1]>.41)&(p[:,2]<.79)
    tail_names=[f'tail_{i:02d}' for i in range(8)]
    tail_weight=smooth(.405,.46,p[:,1])*(1-smooth(.70,.79,p[:,2]))*tail
    w*=1-tail_weight[:,None];w[:,[cols[n] for n in tail_names]]+=values(tail_names)*tail_weight[:,None]
    order=np.argsort(w,axis=1);np.put_along_axis(w,order[:,:-4],0,axis=1);w/=w.sum(axis=1,keepdims=True)
    obj.vertex_groups.clear()
    for col,name in enumerate(names):
        group=obj.vertex_groups.new(name=name)
        quant=np.rint(w[:,col]*4095).astype(np.int16);positive=np.flatnonzero(quant>0);ordered=positive[np.argsort(quant[positive])]
        unique,starts=np.unique(quant[ordered],return_index=True)
        for value,indices in zip(unique,np.split(ordered,starts[1:])):group.add(indices.tolist(),float(value)/4095,'REPLACE')
    base.normalize_weights(obj)
    diagnostic=np.tile((.62,.55,.40,1.),(len(p),1));diagnostic[leg]=(.86,.55,.14,1);diagnostic[head]=(.85,.15,.2,1);diagnostic[tail]=(.12,.65,.3,1);diagnostic[foot]=(.15,.4,.9,1)
    return diagnostic


def animate(arm,name,seconds):
    action=base.new_action(arm,name);count=round(seconds*FPS)
    for frame in range(count+1):
        phase=frame/count;t=frame/FPS
        envelope=float(smooth(.25,1.15,t)*(1-smooth(3.3,4.65,t))) if name=='special' else 0
        pose={
            'head':base.world_rot(arm.pose.bones['head'],base.X,.009*math.sin(math.tau*phase)-.065*envelope),
            'neck':base.world_rot(arm.pose.bones['neck'],base.X,-.018*envelope),
            'chest':base.world_rot(arm.pose.bones['chest'],base.X,.004*math.sin(math.tau*phase)-.012*envelope),
        }
        for i in range(8):
            bone=arm.pose.bones[f'tail_{i:02d}'];angle=(.012+.007*i)*(1+.5*envelope)*math.sin(math.tau*phase-i*.45)
            pose[bone.name]=base.world_rot(bone,base.Y,angle)
        dz=-.004*(1-math.cos(math.tau*phase))-.022*envelope
        lateral=backward=lift=yaw=0
        if name=='walk':
            p=phase%1
            if p<DUTY:
                relative=seconds*(p-DUTY/2);dz=-.030*math.sin(math.pi*p/DUTY)**2
            else:
                u=(p-DUTY)/(1-DUTY);recover=u*u*u*(10-15*u+6*u*u)
                relative=seconds*DUTY*(.5-recover)
                dz=.10*math.sin(math.pi*u)**2;lift=.14*math.sin(math.pi*u)**2
            yaw=-SPEED/RADIUS*relative;ankle=arm.data.bones['central_foot'].head_local
            x,y=ankle.x-RADIUS,ankle.y
            lateral=RADIUS+math.cos(yaw)*x-math.sin(yaw)*y-ankle.x
            backward=math.sin(yaw)*x+math.cos(yaw)*y-ankle.y
        delta=Vector((0,0,dz))
        base.key_loc(arm,frame,'root',arm.data.bones['root'].matrix_local.to_3x3().inverted()@delta)
        base.key_pose(arm,frame,pose);bpy.context.view_layer.update()
        # Absolute armature-space foot matrix cancels all upper-leg rotation.
        contact(arm,'central',frame,lateral,backward,lift,yaw)
    base.finish_action(arm,action)
    for fc in base.action_fcurves(action):
        for key in fc.keyframe_points:key.interpolation='LINEAR'
    return action


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source');parser.add_argument('output');parser.add_argument('--preview',required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:]);QA.mkdir(parents=True,exist_ok=True)
    obj=base.load(args.source);before=native_fingerprint(obj);arm,p,scale,tail=make_rig(obj)
    base.skin(obj,arm);diagnostic=constrain_skin(obj,arm,p,scale)
    after=native_fingerprint(obj)
    if before!=after:raise ValueError('Rig changed native geometry/UV/normals/PBR')
    # Emit explicit native masks, without touching the release mesh attributes.
    attr=obj.data.color_attributes.new(name='kui_anatomical_review',type='FLOAT_COLOR',domain='POINT');attr.data.foreach_set('color',diagnostic.astype(np.float32).ravel())
    mats=list(obj.data.materials);mat=bpy.data.materials.new('kui_mask_review');mat.use_nodes=True;nodes=mat.node_tree.nodes;nodes.clear();out=nodes.new('ShaderNodeOutputMaterial');emit=nodes.new('ShaderNodeEmission');color=nodes.new('ShaderNodeVertexColor');color.layer_name=attr.name;mat.node_tree.links.new(color.outputs['Color'],emit.inputs['Color']);mat.node_tree.links.new(emit.outputs[0],out.inputs[0]);obj.data.materials.clear();obj.data.materials.append(mat)
    render_view(obj,QA/'mask_side.png',(1,0,0));render_view(obj,QA/'mask_front.png',(0,-1,0))
    obj.data.materials.clear()
    for mat in mats:obj.data.materials.append(mat)
    obj.data.color_attributes.remove(attr)
    if native_fingerprint(obj)!=before:raise ValueError('Mask review altered source')
    bpy.context.scene.render.fps=FPS
    actions={name:animate(arm,name,seconds) for name,seconds in DURATIONS.items()}
    for name,action in actions.items():
        arm.animation_data.action=action
        for fraction in [.2,.5,.8]:
            bpy.context.scene.frame_set(round(DURATIONS[name]*FPS*fraction));render_view(obj,QA/f'{name}_{round(fraction*100)}.png')
    arm.animation_data.action=actions['idle'];bpy.context.scene.frame_set(0);render_view(obj,Path(args.preview))
    arm.animation_data.action=None;bpy.context.scene.frame_set(0);activate(obj);arm.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(Path(args.output).resolve()),export_format='GLB',use_selection=True,export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False,export_extras=True)
    manifest=dict(triangles=50000,boneCount=len(arm.data.bones),unweightedVertices=base.unweighted_count(obj),nativeGeometryPreserved=before==after,nativeFingerprint=after,tailCenterline=tail.tolist(),runtime=dict(length=scale,radius=RADIUS,speed=SPEED,stanceDuty=DUTY,durations=DURATIONS,fps=FPS))
    (QA/'rig-manifest.json').write_text(json.dumps(manifest,indent=2));print('SKIN native Kui',len(arm.data.bones),'bones, unweighted',base.unweighted_count(obj),flush=True)


if __name__=='__main__':main()
