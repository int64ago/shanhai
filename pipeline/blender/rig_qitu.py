"""Rig three HIGH-derived modules; runtime assembles exactly 3 heads and 6 tails.
Blender --background --python rig_qitu.py -- normalized_high.glb output_dir
"""
import os
import sys
import math
import bpy
from mathutils import Vector
sys.path.insert(0,os.path.dirname(__file__))
from prepare_qitu import source,extract,trim_body,export,NECK,TAIL
from rig_qingniao import build,animate
from rig_avian import new_action,finish_action,key_pose,world_rot,FPS


def anchors(arm):
    bpy.context.view_layer.objects.active=arm;bpy.ops.object.mode_set(mode='EDIT')
    for name,pos,parent in [('neck_attach',NECK,'chest'),('tail_attach',TAIL,'pelvis')]:
        b=arm.data.edit_bones.new(name);b.head=pos;b.tail=Vector(pos)+Vector((0,0,.06));b.parent=arm.data.edit_bones[parent];b.use_deform=False
    bpy.ops.object.mode_set(mode='OBJECT')


def module_rig(obj,kind):
    arm=bpy.data.objects.new(f'qitu_{kind}_rig',bpy.data.armatures.new(f'qitu_{kind}_rig'))
    bpy.context.scene.collection.objects.link(arm);bpy.context.view_layer.objects.active=arm;bpy.ops.object.mode_set(mode='EDIT')
    points=[(0,0,0),(0,-.01,.16),(0,-.04,.30),(0,-.35,.30)] if kind=='head' else [(0,i*.20,0) for i in range(5)]
    names=[]
    for i in range(len(points)-1):
        name=f'{kind}_chain_{i}';names.append(name);b=arm.data.edit_bones.new(name);b.head=points[i];b.tail=points[i+1]
        if i: b.parent=arm.data.edit_bones[names[i-1]]
    bpy.ops.object.mode_set(mode='OBJECT')
    groups={n:obj.vertex_groups.new(name=n) for n in names}
    for v in obj.data.vertices:
        scored=[]
        for name in names:
            bone=arm.data.bones[name];a,end=bone.head_local,bone.tail_local;ab=end-a
            t=max(0,min(1,(v.co-a).dot(ab)/max(ab.length_squared,1e-8)))
            scored.append((max((a+t*ab-v.co).length,1e-4),name))
        if kind=='head' and v.co.z>.255: scored=[next(x for x in scored if x[1]==names[-1])]
        scored=sorted(scored)[:2];total=sum(d**-5 for d,_ in scored)
        for d,n in scored: groups[n].add([v.index],d**-5/total,'REPLACE')
    mod=obj.modifiers.new('module_skin','ARMATURE');mod.object=arm;obj.parent=arm
    return arm,names


def module_action(arm,names,kind,name,seconds):
    action=new_action(arm,name);n=round(seconds*FPS)
    for f in range(n+1):
        phase=f/n;t=phase*math.tau;envelope=math.sin(math.pi*phase)**2 if name=='alert' else 1
        pose={}
        for i,bone in enumerate(names):
            if kind=='head':
                amount=(.075 if name=='alert' else .025)*math.sin(t*(4 if name=='alert' else 1)-i*.4)*envelope
                pose[bone]=world_rot(arm.pose.bones[bone],(1,0,0),amount)
                if i==0: pose[bone]=world_rot(arm.pose.bones[bone],(0,0,1),.025*math.sin(t))@pose[bone]
            else:
                amount=(.13 if name=='alert' else .045)*math.sin(t*(2 if name=='walk' else 1)-i*.65)*envelope
                pose[bone]=world_rot(arm.pose.bones[bone],(0,0,1),amount)@world_rot(arm.pose.bones[bone],(1,0,0),.035*math.sin(t-i*.4))
        key_pose(arm,f,pose)
    finish_action(arm,action)
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points: key.interpolation='LINEAR'


def discard(obj,arm):
    bpy.data.objects.remove(obj,do_unlink=True);bpy.data.objects.remove(arm,do_unlink=True)
    for action in list(bpy.data.actions): bpy.data.actions.remove(action)


if __name__=='__main__':
    args=sys.argv[sys.argv.index('--')+1:];os.makedirs(args[1],exist_ok=True)
    body,original=source(args[0]);head,tail=extract(body,original)
    arm,lm=build(body,original);arm.name='qitu_body_rig';trim_body(body,original)
    bpy.context.view_layer.objects.active=body
    bpy.ops.object.vertex_group_limit_total(group_select_mode='ALL',limit=4)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode='ALL',lock_active=False)
    anchors(arm)
    bpy.context.scene.render.fps=FPS
    for name,seconds in [('idle',4.8),('walk',1.4),('alert',4.8)]: animate(arm,lm,name,seconds)
    export(f'{args[1]}/body_rig.glb',[body,arm],True);discard(body,arm)
    for kind,obj in [('head',head),('tail',tail)]:
        arm,names=module_rig(obj,kind)
        for name,seconds in [('idle',4.8),('walk',1.4),('alert',4.8)]: module_action(arm,names,kind,name,seconds)
        export(f'{args[1]}/{kind}_rig.glb',[obj,arm],True);discard(obj,arm)
    print('EXPORTED HIGH qitu body/head/tail modules')
