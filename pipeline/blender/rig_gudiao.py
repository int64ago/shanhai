"""Bind HIGH eagle remodel and inferred crown horn, with planted two-foot hops.
Blender --background --python rig_gudiao.py -- normalized_high.glb output.glb
"""
import math
import os
import sys
import bpy
from mathutils import Vector
sys.path.insert(0, os.path.dirname(__file__))
from prepare_gudiao import prepare, remodel, horn
import rig_qingniao as avian
from rig_avian import new_action, finish_action, key_pose, key_loc, world_rot, FPS
from rig_jingwei import contact


def animate(arm, lm, name, seconds):
    action=new_action(arm,name);n=round(seconds*FPS)
    for frame in range(n+1):
        phase=frame/n;t=phase*math.tau;backward=lift=0
        if name=='walk':
            # Same .12m/s retreat as the runtime chord translation.
            if phase<=.5: backward=-.042+.168*phase
            else:
                u=(phase-.5)*2;backward=.042-.084*(u*u*(3-2*u));lift=.075*math.sin(math.pi*u)
            delta=Vector((0,0,lift*.85));tilt=.035*math.sin(t);wing=.045*math.sin(t)
        elif name=='alert':
            envelope=math.sin(math.pi*phase)**2
            delta=Vector((0,0,.005*math.sin(2*t)));tilt=-.16*envelope+.045*math.sin(5*t)*envelope;wing=.92*envelope
        else:
            delta=Vector((0,0,.003*math.sin(2*t)));tilt=.025*math.sin(t);wing=.012*math.sin(2*t)
        key_loc(arm,frame,'pelvis',arm.data.bones['pelvis'].matrix_local.to_3x3().inverted()@delta)
        pose={'head':world_rot(arm.pose.bones['head'],(1,0,0),tilt),
              'neck':world_rot(arm.pose.bones['neck'],(0,0,1),.025*math.sin(t)),
              'tail_feather':world_rot(arm.pose.bones['tail_feather'],(1,0,0),.045*math.sin(t))}
        for side,sign in [('l',1),('r',-1)]:
            pose[f'wing_{side}_1']=world_rot(arm.pose.bones[f'wing_{side}_1'],(0,1,0),-sign*wing)
            for i in [2,3]:pose[f'wing_{side}_{i}']=world_rot(arm.pose.bones[f'wing_{side}_{i}'],(0,0,1),sign*wing*.14)
        key_pose(arm,frame,pose);bpy.context.view_layer.update();contact(arm,lm,frame,delta,backward,lift)
    finish_action(arm,action)
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:key.interpolation='LINEAR'


if __name__=='__main__':
    args=sys.argv[sys.argv.index('--')+1:]
    obj,original=prepare(args[0])
    # Reuse the verified anatomical masks and two-leg contact solver; all landmark
    # coordinates are mapped through this eagle's remodel, not the bluebird's.
    avian.remodel=remodel
    arm,lm=avian.build(obj,original);arm.name='gudiao_rig'
    part,base=horn(obj)
    group=part.vertex_groups.new(name='head');group.add(list(range(len(part.data.vertices))),1,'REPLACE')
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);part.select_set(True);bpy.context.view_layer.objects.active=obj;bpy.ops.object.join()
    bpy.context.scene.render.fps=FPS
    for name,seconds in [('idle',4.8),('walk',1.4),('alert',4.8)]:animate(arm,lm,name,seconds)
    bpy.ops.export_scene.gltf(filepath=args[1],export_format='GLB',export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    print('GUDIAO single embedded horn',list(base),'bones',len(arm.data.bones))
