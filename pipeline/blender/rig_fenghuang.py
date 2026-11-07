"""Fenghuang's compact fowl rig, alternating walk and grounded singing dance.
Three clips: idle (4s), walk (1.6s), alert (5.2s). Dance interprets 自歌自舞;
there is no inferred fire or flight. Native bird toes remain flat in stance.
"""
import math
import sys
from pathlib import Path
import bpy
from mathutils import Matrix, Vector
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_jingwei as bird
from rig_avian import FPS, load, new_action, finish_action, key_loc, key_pose, world_rot
from rig_qique import contact


def smooth(a,b,x):
    t=max(0,min(1,(x-a)/(b-a)));return t*t*(3-2*t)


def make_rig(obj):
    arm,lm=bird.make_rig(obj)
    lm.update(pelvis=Vector((0,-.015,.43)),chest=Vector((0,-.10,.61)),
              neck_base=Vector((0,-.20,.76)),head_base=Vector((0,-.33,.89)),
              beak_tip=Vector((0,-.47,.87)),tail_base=Vector((0,.15,.46)),tail_tip=Vector((0,.5,.83)))
    bpy.context.view_layer.objects.active=arm;bpy.ops.object.mode_set(mode='EDIT')
    eb=arm.data.edit_bones
    for name,a,b in [('pelvis',lm['pelvis'],lm['chest']),('chest',lm['chest'],lm['neck_base']),
                     ('neck',lm['neck_base'],lm['head_base']),('head',lm['head_base'],lm['beak_tip']),
                     ('tail_feather',lm['tail_base'],lm['tail_tip'])]:
        eb[name].head=a;eb[name].tail=b
    for side,foot in lm['feet'].items():
        hip=Vector((foot.x,foot.y+.025,.34));knee=Vector((foot.x,foot.y+.055,.18))
        eb[f'leg_{side}_upper'].head=hip;eb[f'leg_{side}_upper'].tail=knee
        eb[f'leg_{side}_lower'].head=knee;eb[f'leg_{side}_lower'].tail=foot
    bpy.ops.object.mode_set(mode='OBJECT')
    bird.skin(obj,arm,lm)
    # Authored crown and short fan follow their anatomical bases. Restored
    # tail feather weighting also covers the analytically raised native tail.
    crown=set();fan=set()
    for poly in obj.data.polygons:
        name=obj.data.materials[poly.material_index].name
        if name.startswith('low_crown'):crown.update(poly.vertices)
        if name.startswith('short_fan'):fan.update(poly.vertices)
    for v in obj.data.vertices:
        name=None
        if v.index in crown:name='head'
        elif v.index in fan or (v.co.y>.17 and abs(v.co.x)<.30 and v.co.z>.36):name='tail_feather'
        if name:
            for g in obj.vertex_groups:g.remove([v.index])
            obj.vertex_groups[name].add([v.index],1,'REPLACE')
    return arm,lm


def animate(arm,lm,name,seconds):
    action=new_action(arm,name);n=round(seconds*FPS)
    for f in range(n+1):
        t=f/FPS;phase=f/n;wave=math.sin(phase*math.tau)
        spread=0;neck=.025*wave;head=.015*wave
        delta=Vector((0,0,-.009+.002*math.cos(phase*math.tau*2)))
        targets={s:(0,0) for s in ['l','r']}
        if name=='walk':
            for side,offset in [('l',0),('r',.5)]:
                p=(phase+offset)%1;duty=.65;distance=.12*seconds*duty
                if p<duty:back=-distance/2+distance*p/duty;lift=0
                else:
                    u=(p-duty)/(1-duty);back=distance/2-distance*(u*u*(3-2*u));lift=.050*math.sin(u*math.pi)
                targets[side]=(back,lift)
            neck=.04*math.sin(phase*math.tau*2)
        elif name=='alert':
            envelope=smooth(.2,.9,t)*(1-smooth(4.4,5.1,t))
            spread=envelope*(.85+.15*math.cos((t-.9)*math.tau/1.6))
            # Two low deliberate steps with alternating support: singing dance.
            for side,begin in [('l',1.0),('r',2.65)]:
                u=(t-begin)/1.25
                if 0<u<1:targets[side]=(-.024*math.sin(u*math.pi),.065*math.sin(u*math.pi)**2)
            neck=.09*envelope+.035*wave;head=.055*envelope*math.sin(t*5)
        key_loc(arm,f,'pelvis',arm.data.bones['pelvis'].matrix_local.to_3x3().inverted()@delta)
        pose={'neck':world_rot(arm.pose.bones['neck'],(1,0,0),neck),
              'head':world_rot(arm.pose.bones['head'],(1,0,0),head),
              'tail_feather':world_rot(arm.pose.bones['tail_feather'],(0,0,1),.055*wave*(1+spread))}
        for side,sign in [('l',1),('r',-1)]:
            for i in [1,2,3]:
                fold=(.87-.77*spread) if i==1 else .035*math.sin(t*2-i)*spread
                sweep=(.58 if i==1 else .12)*(1-spread)
                pb=arm.pose.bones[f'wing_{side}_{i}']
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
    for name,seconds in [('idle',4),('walk',1.6),('alert',5.2)]:animate(arm,lm,name,seconds)
    bpy.ops.export_scene.gltf(filepath=args[1],export_format='GLB',export_animations=True,
                              export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    print('EXPORTED',args[1],'bones',len(arm.data.bones),'grounded alternating dance')


if __name__=='__main__':main()
