"""Dedicated Boyi skeleton, IK sheep walk, and grounded nine-tail display.

All 4 ears, 9 eight-bone tails and dorsal eyes are baked into this owned rig.
No runtime cached-scene attachments or reflected/negative scales are needed.
"""
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import rig_quadruped as base
from rig_ershu import leg_ik, smooth, rigid
from prepare_boyi import EARS, FOOT_POINTS, ear_root, tail_center

FPS = 30
TAIL_BONES = 8
SPECIAL_SECONDS = 4.8


def extra_bones(arm):
    bpy.context.view_layer.objects.active=arm
    bpy.ops.object.mode_set(mode='EDIT')
    eb=arm.data.edit_bones
    for side,pair in EARS:
        bone=eb.new(f'boyi_ear_{side}_{pair}')
        bone.head=ear_root(side,pair)
        bone.tail=bone.head+Vector((side*.18,0,-.04))
        bone.parent=eb['head']
    for side in (-1,1):
        bone=eb.new(f'boyi_eye_{side}')
        bone.head=(side*.105,.005,.67)
        bone.tail=(side*.105,.005,.74)
        bone.parent=eb['spine2']
    for index in range(9):
        for segment in range(TAIL_BONES):
            bone=eb.new(f'boyi_tail_{index:02}_{segment:02}')
            bone.head=tail_center(index,segment/TAIL_BONES)
            bone.tail=tail_center(index,(segment+1)/TAIL_BONES)
            bone.parent=eb['hips'] if segment==0 else eb[f'boyi_tail_{index:02}_{segment-1:02}']
            bone.use_connect=segment>0
    bpy.ops.object.mode_set(mode='OBJECT')


def tail_skin(obj,arm,index):
    groups=[obj.vertex_groups.new(name=f'boyi_tail_{index:02}_{j:02}') for j in range(TAIL_BONES)]
    span=.35-.10*abs((index-4)/4)
    for vertex in obj.data.vertices:
        t=max(0,min(1,(vertex.co.y-.305)/span))
        k=max(0,min(TAIL_BONES-1,t*TAIL_BONES-.5))
        lo=int(k)
        weight=k-lo
        groups[lo].add([vertex.index],1-weight,'REPLACE')
        if weight and lo+1<TAIL_BONES:
            groups[lo+1].add([vertex.index],weight,'REPLACE')
    mod=obj.modifiers.new('single sheep tail chain','ARMATURE')
    mod.object=arm
    obj.parent=arm


def appendage_pose(arm,phase,strength,display=0):
    pose={}
    for index in range(9):
        fan=(index-4)/4
        for segment in range(TAIL_BONES):
            bone=arm.pose.bones[f'boyi_tail_{index:02}_{segment:02}']
            wave=strength*.07*math.sin(phase-segment*.6+index*.45)
            spread=display*fan*(.30 if segment==0 else .012)
            lift=display*(-.18 if segment==0 else -.012)
            pose[bone.name]=base.world_rot(bone,base.X,wave+lift) @ base.world_rot(bone,base.Z,spread)
    for side,pair in EARS:
        bone=arm.pose.bones[f'boyi_ear_{side}_{pair}']
        pose[bone.name]=base.world_rot(bone,base.Y,side*(.035*math.sin(phase+pair)+display*.22))
    return pose


def eye_scale(arm,frame,blink=1,display=0):
    for side in (-1,1):
        bone=arm.pose.bones[f'boyi_eye_{side}']
        bone.scale=(1+.08*display,max(.14,blink),1+.08*display)
        bone.keyframe_insert('scale',frame=frame)


def idle(arm):
    action=base.new_action(arm,'idle')
    for frame in range(121):
        t=frame/FPS
        phase=math.tau*t/4
        pose=appendage_pose(arm,phase,.30)
        pose['head']=base.world_rot(arm.pose.bones['head'],base.X,.016*math.sin(phase))
        pose['neck']=base.world_rot(arm.pose.bones['neck'],base.Z,.025*math.sin(phase))
        base.key_pose(arm,frame,pose)
        blink=1-.88*max(0,1-abs(t-2.5)/.11)
        eye_scale(arm,frame,blink)
    base.finish_action(arm,action)


def walk(arm):
    action=base.new_action(arm,'walk')
    frames=48
    phases={'back_l':0,'front_l':.25,'back_r':.5,'front_r':.75}
    for frame in range(frames+1):
        t=frame/frames
        pose=appendage_pose(arm,math.tau*t,.60)
        for leg,offset in phases.items():
            swing,lift=base.leg_cycle((t+offset)%1,duty=.68)
            pose.update(leg_ik(arm,leg,-.08*swing,.018+.040*lift))
        pose['head']=base.world_rot(arm.pose.bones['head'],base.X,.012*math.sin(math.tau*t))
        base.key_pose(arm,frame,pose)
        base.key_loc(arm,frame,'root',Vector((0,-.018,0)))
        eye_scale(arm,frame)
    base.finish_action(arm,action)


def special(arm):
    action=base.new_action(arm,'special')
    for frame in range(round(SPECIAL_SECONDS*FPS)+1):
        t=frame/FPS
        display=smooth(0,.9,t)*(1-smooth(3.2,4.8,t))
        pose=appendage_pose(arm,t*math.tau/2,.30+display,display)
        pose['head']=base.world_rot(arm.pose.bones['head'],base.X,-.13*display)
        pose['neck']=base.world_rot(arm.pose.bones['neck'],base.X,-.045*display)
        base.key_pose(arm,frame,pose)
        eye_scale(arm,frame,display=display)
    base.finish_action(arm,action)


def main():
    source,output=sys.argv[sys.argv.index('--')+1:]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    for obj in meshes:
        bpy.context.view_layer.objects.active=obj
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
        bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    body=bpy.data.objects['boyi_high_sheep_body']
    lm={'height':.9,'length':1.2,'legs':FOOT_POINTS,'front_y':-.265,'back_y':.24,
        'chest':Vector((0,-.265,.49)),'chest_top':.70,'hips':Vector((0,.24,.49)),
        'head':Vector((0,-.38,.78)),'snout':Vector((0,-.56,.62)),'rear':Vector((0,.305,.58))}
    arm=base.build_armature(lm)
    arm.name='boyi_rig'
    # Weight the watertight HIGH-derived body before adding extra organ bones.
    base.skin(body,arm)
    axial=[arm.data.bones[n] for n in ('hips','spine1','spine2','chest','neck')]
    for vertex in body.data.vertices:
        if vertex.co.z<.40:
            continue
        blend=smooth(.40,.51,vertex.co.z)
        weights={body.vertex_groups[g.group].name:g.weight*(1-blend) for g in vertex.groups}
        nearest=min(axial,key=lambda b:(b.head_local-vertex.co).length_squared)
        weights[nearest.name]=weights.get(nearest.name,0)+blend
        for group in body.vertex_groups:
            group.remove([vertex.index])
        for name,weight in weights.items():
            if weight>1e-6:
                body.vertex_groups[name].add([vertex.index],weight,'REPLACE')
    base.normalize_weights(body)
    extra_bones(arm)
    for obj in meshes:
        if obj is body:
            continue
        name=obj.name
        if name.startswith('boyi_tail_'):
            tail_skin(obj,arm,int(name.split('_')[2]))
        elif name.startswith('boyi_ear_'):
            _,_,side,pair,_=name.split('_')
            rigid(obj,arm,f'boyi_ear_{side}_{pair}')
        elif name.startswith('boyi_dorsal_'):
            rigid(obj,arm,f'boyi_eye_{name.split("_")[2]}')
        elif name.startswith('boyi_hoof_'):
            rigid(obj,arm,name.removeprefix('boyi_hoof_')+'_foot')
        else:
            rigid(obj,arm,'head')
    bpy.context.scene.render.fps=FPS
    idle(arm)
    walk(arm)
    special(arm)
    bpy.context.scene.frame_set(0)
    bpy.ops.export_scene.gltf(filepath=output,export_format='GLB',export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    print('BOYI_RIG bones',len(arm.data.bones),'unweighted body',base.unweighted_count(body),'actions',[(a.name,tuple(a.frame_range)) for a in bpy.data.actions])


if __name__=='__main__':
    main()
