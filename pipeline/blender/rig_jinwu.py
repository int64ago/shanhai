"""Jinwu's two-foot corvid stance, deliberate walk and grounded wing display.
Three original clips: idle 4s, walk 1.6s, alert 4.6s. Two feet are inference,
not a claim that the classical passage specifies a count. No solar/fire mesh.
120 Hz LINEAR samples and --resample false preserve actual paw contact.
"""
import math
import sys
from pathlib import Path
import bpy
from mathutils import Vector
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import rig_jingwei as bird
from rig_avian import load,new_action,finish_action,key_loc,key_pose,world_rot
from rig_qique import contact
FPS=120


def smooth(a,b,x):
    t=max(0,min(1,(x-a)/(b-a)));return t*t*(3-2*t)


def make_rig(obj):
    arm,lm=bird.make_rig(obj);bird.skin(obj,arm,lm)
    # Native tail feathers follow the rump; explicit soles follow each flat
    # counter-rotated foot, with no pelvis blending at the contact plane.
    for v in obj.data.vertices:
        part=None
        if v.co.z<lm['height']*.10 and v.co.y<.15:part='foot_l' if v.co.x>0 else 'foot_r'
        elif v.co.y>lm['tail_base'].y+.045 and abs(v.co.x)<.22 and v.co.z<lm['height']*.54:part='tail_feather'
        if part:
            for g in obj.vertex_groups:g.remove([v.index])
            obj.vertex_groups[part].add([v.index],1,'REPLACE')
    return arm,lm


def animate(arm,lm,name,seconds):
    action=new_action(arm,name);n=round(seconds*FPS)
    for f in range(n+1):
        t=f/FPS;phase=f/n;wave=math.sin(phase*math.tau);spread=0
        delta=Vector((0,0,-.012+.0015*math.sin(phase*math.tau*2)))
        targets={s:(0,0) for s in ['l','r']};nod=.022*wave
        if name=='walk':
            delta.z=-.015
            for side,offset in [('l',0),('r',.5)]:
                p=(phase+offset)%1;duty=.70;distance=.12*seconds*duty
                if p<duty:back=-distance/2+distance*p/duty;lift=0
                else:
                    u=(p-duty)/(1-duty);back=distance/2-distance*(u*u*(3-2*u));lift=.045*math.sin(u*math.pi)
                targets[side]=(back,lift)
            nod=.035*math.sin(phase*math.tau*2)
        elif name=='alert':
            spread=smooth(.25,1.15,t)*(1-smooth(3.25,4.45,t))
            nod=.07*spread+.025*math.sin(t*5)*spread
        key_loc(arm,f,'pelvis',arm.data.bones['pelvis'].matrix_local.to_3x3().inverted()@delta)
        pose={'neck':world_rot(arm.pose.bones['neck'],(1,0,0),nod),
              'head':world_rot(arm.pose.bones['head'],(0,0,1),.025*wave),
              'tail_feather':world_rot(arm.pose.bones['tail_feather'],(1,0,0),-.035*wave)}
        for side,sign in [('l',1),('r',-1)]:
            for i in [1,2,3]:
                pb=arm.pose.bones[f'wing_{side}_{i}']
                fold=(.92-.82*spread) if i==1 else .028*math.sin(t*2-i)*spread
                sweep=(.50 if i==1 else .13)*(1-spread)
                pose[pb.name]=world_rot(pb,(0,0,1),sign*sweep)@world_rot(pb,(0,1,0),sign*fold)
        key_pose(arm,f,pose);bpy.context.view_layer.update()
        for side,(back,lift) in targets.items():contact(arm,lm,side,f,delta,back,lift)
    finish_action(arm,action)
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    for key in fc.keyframe_points:key.interpolation='LINEAR'


def main():
    args=sys.argv[sys.argv.index('--')+1:];obj=load(args[0]);bpy.context.scene.render.fps=FPS
    arm,lm=make_rig(obj)
    for name,seconds in [('idle',4),('walk',1.6),('alert',4.6)]:animate(arm,lm,name,seconds)
    bpy.ops.export_scene.gltf(filepath=args[1],export_format='GLB',export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    print('EXPORTED',args[1],'bones',len(arm.data.bones),'two planted soles')


if __name__=='__main__':main()
