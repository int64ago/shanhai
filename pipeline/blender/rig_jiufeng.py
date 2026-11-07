"""Independent nine-neck HIGH hybrid bird rig, no native bird head geometry.
Blender --background --python rig_jiufeng.py -- bird_norm.glb output.glb
"""
import math
import os
import sys
import bpy
from mathutils import Vector
sys.dont_write_bytecode=True
sys.path.insert(0,os.path.dirname(__file__))
from prepare_jiufeng import prepare_body,remodel,trim,layout,curve,neck_material,neck_mesh,shoulder_ruff
from prepare_qitu import export
import rig_qingniao as avian
from rig_avian import new_action,finish_action,key_pose,key_loc,world_rot,FPS
from rig_jingwei import contact


def neck_rig(arm,mounts):
    bpy.context.view_layer.objects.active=arm;bpy.ops.object.mode_set(mode='EDIT')
    for i,(base,end,_) in enumerate(mounts):
        points=[curve(base,end,j/3)[0] for j in range(4)]
        for j in range(3):
            b=arm.data.edit_bones.new(f'neck_{i}_{j}');b.head=points[j];b.tail=points[j+1];b.parent=arm.data.edit_bones['chest' if j==0 else f'neck_{i}_{j-1}']
        b=arm.data.edit_bones.new(f'human_mount_{i}');b.head=end-Vector((0,0,.012));b.tail=b.head+Vector((0,0,.055));b.parent=arm.data.edit_bones[f'neck_{i}_2'];b.use_deform=False
    bpy.ops.object.mode_set(mode='OBJECT')
    mat=neck_material();ruff=shoulder_ruff(mat)
    group=ruff.vertex_groups.new(name='chest');group.add(list(range(len(ruff.data.vertices))),1,'REPLACE')
    ruff.parent=arm;mod=ruff.modifiers.new('shoulder_skin','ARMATURE');mod.object=arm
    parts=[ruff]
    for i,(base,end,_) in enumerate(mounts):
        part=neck_mesh(base,end,i,mat);groups=[part.vertex_groups.new(name=f'neck_{i}_{j}') for j in range(3)]
        for v in part.data.vertices:
            t=(v.index//20)/24;f=max(0,min(2,t*3-.5));low=int(f);high=min(2,low+1)
            if low==high:groups[low].add([v.index],1,'REPLACE')
            else:
                groups[low].add([v.index],1-(f-low),'REPLACE');groups[high].add([v.index],f-low,'REPLACE')
        mod=part.modifiers.new('feather_neck_skin','ARMATURE');mod.object=arm;part.parent=arm;parts.append(part)
    return parts


def animate(arm,lm,name,seconds):
    action=new_action(arm,name);n=round(seconds*FPS)
    for frame in range(n+1):
        phase=frame/n;t=phase*math.tau;backward=lift=0
        if name=='walk':
            if phase<=.5:backward=-.042+.168*phase
            else:
                u=(phase-.5)*2;backward=.042-.084*(u*u*(3-2*u));lift=.08*math.sin(math.pi*u)
            delta=Vector((0,0,lift*.85));wing=.035*math.sin(t)
        elif name=='alert':delta=Vector((0,0,.004*math.sin(2*t)));wing=.62*math.sin(math.pi*phase)**2
        else:delta=Vector((0,0,.003*math.sin(2*t)));wing=.015*math.sin(2*t)
        key_loc(arm,frame,'pelvis',arm.data.bones['pelvis'].matrix_local.to_3x3().inverted()@delta)
        pose={'tail_feather':world_rot(arm.pose.bones['tail_feather'],(1,0,0),.03*math.sin(t))}
        for side,sign in [('l',1),('r',-1)]:
            pose[f'wing_{side}_1']=world_rot(arm.pose.bones[f'wing_{side}_1'],(0,1,0),-sign*wing)
            for j in [2,3]:pose[f'wing_{side}_{j}']=world_rot(arm.pose.bones[f'wing_{side}_{j}'],(0,0,1),sign*wing*.12)
        for i in range(9):
            offset=i*2.39996;strength=(.045*math.sin(math.pi*phase)**2 if name=='alert' else .016)
            for j in range(3):
                amount=strength*math.sin(t+offset-j*.3)
                pose[f'neck_{i}_{j}']=world_rot(arm.pose.bones[f'neck_{i}_{j}'],(1,0,0),amount)
            pose[f'human_mount_{i}']=world_rot(arm.pose.bones[f'human_mount_{i}'],(0,0,1),.025*math.sin(t+offset))
        key_pose(arm,frame,pose);bpy.context.view_layer.update();contact(arm,lm,frame,delta,backward,lift)
    finish_action(arm,action)
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    for key in fc.keyframe_points:key.interpolation='LINEAR'


if __name__=='__main__':
    args=sys.argv[sys.argv.index('--')+1:];body,original=prepare_body(args[0]);avian.remodel=remodel
    arm,lm=avian.build(body,original);arm.name='jiufeng_bird_rig';trim(body);mounts=layout(body)
    parts=neck_rig(arm,mounts)
    bpy.ops.object.select_all(action='DESELECT');body.select_set(True)
    for p in parts:p.select_set(True)
    bpy.context.view_layer.objects.active=body;bpy.ops.object.join()
    bpy.ops.object.vertex_group_limit_total(group_select_mode='ALL',limit=4);bpy.ops.object.vertex_group_normalize_all(group_select_mode='ALL',lock_active=False)
    bpy.context.scene.render.fps=FPS
    for name,seconds in [('idle',4.8),('walk',1.4),('alert',4.8)]:animate(arm,lm,name,seconds)
    export(args[1],[body,arm],True);print('JIUFENG',len(arm.data.bones),'bones; exactly nine human mounts')
