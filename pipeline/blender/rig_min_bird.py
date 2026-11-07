"""Two-short-leg kingfisher rig; HIGH crow mesh is remodeled before binding.
Blender --background --python rig_min_bird.py -- source_norm.glb output.glb
No API calls. Custom anatomical masks prevent breast/wing weight crossover.
"""
import math
import os
import sys
import bpy
import numpy as np
from mathutils import Vector
sys.path.insert(0, os.path.dirname(__file__))
from prepare_min_bird import remodel, repaint
from rig_avian import load, new_action, finish_action, key_pose, key_loc, world_rot, FPS
from rig_jingwei import contact


def build(obj, original):
    arm = bpy.data.objects.new('min_bird_rig', bpy.data.armatures.new('min_bird_rig'))
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.data.edit_bones
    def bone(name, a, b, parent=None, deform=True):
        item = eb.new(name)
        item.head, item.tail = a, b
        item.use_deform = deform
        if parent:
            item.parent = eb[parent]
    pelvis = Vector((0, -.015, .29))
    chest = Vector((0, -.16, .48))
    neck = Vector((0, -.29, .63))
    head = Vector((0, -.35, .72))
    tip = Vector((0, -.92, .77))
    bone('root', (0,0,0), (0,0,.08), deform=False)
    bone('pelvis', pelvis, chest, 'root')
    bone('chest', chest, neck, 'pelvis')
    bone('neck', neck, head, 'chest')
    bone('head', head, tip, 'neck')
    bone('tail_feather', (0,.12,.27), (0,.32,.22), 'pelvis')
    feet = {}
    for side, sign in [('l',1), ('r',-1)]:
        pts = [v.co for v,p in zip(obj.data.vertices,original) if sign*p[0]>.06 and p[2]<.055 and p[1]<.14]
        foot = Vector((sum(p.x for p in pts)/len(pts), -.06, .023))
        feet[side] = foot
        hip = Vector((foot.x, -.01, .19))
        knee = Vector((foot.x, .015, .105))
        bone(f'leg_{side}_upper', hip, knee, 'pelvis')
        bone(f'leg_{side}_lower', knee, foot, f'leg_{side}_upper')
        bone(f'foot_{side}', foot, foot+Vector((0,-.10,-.02)), f'leg_{side}_lower')
        points = [remodel(Vector((sign*x,y,z))) for x,y,z in [(.17,-.13,.70),(.36,-.06,.73),(.56,-.08,.83),(.73,-.05,.86)]]
        for i in range(3):
            bone(f'wing_{side}_{i+1}',points[i],points[i+1], 'chest' if i==0 else f'wing_{side}_{i}')
    bone('beak_attach',tip,tip+Vector((0,-.02,0)),'head',False)
    bpy.ops.object.mode_set(mode='OBJECT')
    bones = {b.name:b for b in arm.data.bones if b.use_deform}
    groups = {n:obj.vertex_groups.new(name=n) for n in bones}
    for v,p in zip(obj.data.vertices,original):
        side = 'l' if p[0]>=0 else 'r'
        if p[2]<.105 and p[1]<.16:
            names = [f'foot_{side}']
        elif p[2]<.32 and p[1]<.16:
            names = [f'leg_{side}_upper',f'leg_{side}_lower',f'foot_{side}']
        elif abs(p[0])>.19 and p[2]>.45:
            names = [f'wing_{side}_{i}' for i in [1,2,3]]
            if abs(p[0])<.26:
                names += ['chest']
        elif p[1]>.18 and p[2]<.5:
            names = ['tail_feather','pelvis']
        elif p[2]>.93 and abs(p[0])<.18:
            names = ['head']
        else:
            names = ['pelvis','chest','neck','head']
        scored=[]
        for name in names:
            b=bones[name]
            a,end=b.head_local,b.tail_local
            ab=end-a
            t=max(0,min(1,(v.co-a).dot(ab)/max(ab.length_squared,1e-8)))
            d=max((a+t*ab-v.co).length,1e-4)
            scored.append((d,name))
        scored.sort()
        scored=scored[:3]
        total=sum(d**-5.5 for d,_ in scored)
        for d,name in scored:
            groups[name].add([v.index],d**-5.5/total,'REPLACE')
    mod=obj.modifiers.new('avian_skin','ARMATURE')
    mod.object=arm
    obj.parent=arm
    return arm, {'feet':feet,'height':max(v.co.z for v in obj.data.vertices)}


def animate(arm,lm,name,seconds):
    action=new_action(arm,name)
    n=round(seconds*FPS)
    for frame in range(n+1):
        phase=frame/n
        t=math.tau*phase
        backward=lift=0
        if name=='walk':
            # 0.10 m/s path, .5 second planted stance, then paired airborne return.
            if phase<=.5:
                backward=-.025+.10*phase
            else:
                u=(phase-.5)*2
                backward=.025-.05*(u*u*(3-2*u))
                lift=.065*math.sin(math.pi*u)
            delta=Vector((0,0,lift*.85))
            tilt=.025*math.sin(t)
            wing=.035*math.sin(t)
        elif name=='alert':
            # Quiet shielding display: feet remain planted, both wings open slightly.
            envelope=math.sin(math.pi*phase)**2
            delta=Vector((0,0,.003*math.sin(2*t)))
            tilt=-.09*envelope+.025*math.sin(t)
            wing=.40*envelope+.025*math.sin(3*t)*envelope
        else:
            delta=Vector((0,0,.002*math.sin(2*t)))
            tilt=.035*math.sin(t)
            wing=.012*math.sin(2*t)
        local=arm.data.bones['pelvis'].matrix_local.to_3x3().inverted()@delta
        key_loc(arm,frame,'pelvis',local)
        pose={
            'head':world_rot(arm.pose.bones['head'],(1,0,0),tilt),
            'neck':world_rot(arm.pose.bones['neck'],(0,0,1),.025*math.sin(t)),
            'tail_feather':world_rot(arm.pose.bones['tail_feather'],(1,0,0),.02*math.sin(t)),
        }
        for side,sign in [('l',1),('r',-1)]:
            pose[f'wing_{side}_1']=world_rot(arm.pose.bones[f'wing_{side}_1'],(0,1,0),-sign*wing)
            for i in [2,3]:
                pose[f'wing_{side}_{i}']=world_rot(arm.pose.bones[f'wing_{side}_{i}'],(0,0,1),sign*wing*.12)
        key_pose(arm,frame,pose)
        bpy.context.view_layer.update()
        contact(arm,lm,frame,delta,backward,lift)
    finish_action(arm,action)
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        key.interpolation='LINEAR'


def main():
    args=sys.argv[sys.argv.index('--')+1:]
    obj=load(args[0])
    original=np.array([v.co[:] for v in obj.data.vertices])
    repaint(obj,original)
    for v in obj.data.vertices:
        v.co=remodel(v.co.copy())
    obj.data.update()
    obj.name='min_bird_high_remodel'
    arm,lm=build(obj,original)
    bpy.context.scene.render.fps=FPS
    for name,seconds in [('idle',4),('walk',1),('alert',4.2)]:
        animate(arm,lm,name,seconds)
    bpy.ops.export_scene.gltf(filepath=args[1],export_format='GLB',export_animations=True,
        export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    print('EXPORTED',args[1],'bones',len(arm.data.bones),'feet',lm['feet'])

if __name__=='__main__':
    main()
