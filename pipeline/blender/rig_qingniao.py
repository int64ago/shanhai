"""Independent two-wing/two-leg HIGH bird skeleton, cloned three times at runtime.
Blender --background --python rig_qingniao.py -- normalized_high.glb output.glb
"""
import math
import os
import sys
import bpy
from mathutils import Vector
sys.path.insert(0,os.path.dirname(__file__))
from prepare_qingniao import prepare, remodel
from rig_avian import new_action,finish_action,key_pose,key_loc,world_rot,FPS
from rig_jingwei import contact


def build(obj,original):
    arm=bpy.data.objects.new('qingniao_rig',bpy.data.armatures.new('qingniao_rig'))
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active=arm
    bpy.ops.object.mode_set(mode='EDIT')
    eb=arm.data.edit_bones
    def bone(name,a,b,parent=None,deform=True):
        item=eb.new(name)
        item.head,item.tail=a,b
        item.use_deform=deform
        if parent: item.parent=eb[parent]
    pts={n:remodel(Vector(p)) for n,p in {
        'pelvis':(0,.02,.48),'chest':(0,-.12,.70),'neck':(0,-.26,.84),
        'head':(0,-.35,.99),'beak':(0,-.65,.97),'tail':(0,.20,.42),'tail_tip':(0,.64,.08)}.items()}
    bone('root',(0,0,0),(0,0,.08),deform=False)
    for name,a,b,parent in [('pelvis','pelvis','chest','root'),('chest','chest','neck','pelvis'),
            ('neck','neck','head','chest'),('head','head','beak','neck'),('tail_feather','tail','tail_tip','pelvis')]:
        bone(name,pts[a],pts[b],parent)
    feet={}
    for side,sign in [('l',1),('r',-1)]:
        low=[v.co for v,p in zip(obj.data.vertices,original) if sign*p[0]>.06 and p[2]<.055 and p[1]<.14]
        foot=Vector((sum(p.x for p in low)/len(low),-.06,.034))
        feet[side]=foot
        hip=Vector((foot.x,.0,.31));knee=Vector((foot.x,.045,.17))
        bone(f'leg_{side}_upper',hip,knee,'pelvis')
        bone(f'leg_{side}_lower',knee,foot,f'leg_{side}_upper')
        bone(f'foot_{side}',foot,foot+Vector((0,-.10,-.03)),f'leg_{side}_lower')
        wing=[remodel(Vector((sign*x,y,z))) for x,y,z in [(.17,-.13,.70),(.36,-.06,.73),(.56,-.08,.83),(.73,-.05,.86)]]
        for i in range(3): bone(f'wing_{side}_{i+1}',wing[i],wing[i+1],'chest' if i==0 else f'wing_{side}_{i}')
    bone('beak_attach',pts['beak'],pts['beak']+Vector((0,-.02,0)),'head',False)
    bpy.ops.object.mode_set(mode='OBJECT')
    bones={b.name:b for b in arm.data.bones if b.use_deform}
    groups={n:obj.vertex_groups.new(name=n) for n in bones}
    for v,p in zip(obj.data.vertices,original):
        side='l' if p[0]>=0 else 'r'
        if p[2]<.105 and p[1]<.16: names=[f'foot_{side}']
        elif p[2]<.32 and p[1]<.16: names=[f'leg_{side}_upper',f'leg_{side}_lower',f'foot_{side}']
        elif abs(p[0])>.19 and p[2]>.45:
            names=[f'wing_{side}_{i}' for i in [1,2,3]]
            if abs(p[0])<.26: names+=['chest']
        elif p[1]>.18 and p[2]<.5: names=['tail_feather','pelvis']
        elif p[2]>.93 and abs(p[0])<.18: names=['head']
        else: names=['pelvis','chest','neck','head']
        scored=[]
        for name in names:
            b=bones[name];a,end=b.head_local,b.tail_local;ab=end-a
            t=max(0,min(1,(v.co-a).dot(ab)/max(ab.length_squared,1e-8)))
            scored.append((max((a+t*ab-v.co).length,1e-4),name))
        scored=sorted(scored)[:3];total=sum(d**-5.5 for d,_ in scored)
        for d,name in scored: groups[name].add([v.index],d**-5.5/total,'REPLACE')
    mod=obj.modifiers.new('avian_skin','ARMATURE');mod.object=arm;obj.parent=arm
    return arm,{'feet':feet,'height':max(v.co.z for v in obj.data.vertices)}


def animate(arm,lm,name,seconds):
    action=new_action(arm,name);n=round(seconds*FPS)
    for frame in range(n+1):
        phase=frame/n;t=phase*math.tau;backward=lift=0
        if name=='walk':
            if phase<=.5: backward=-.042+.168*phase
            else:
                u=(phase-.5)*2;backward=.042-.084*(u*u*(3-2*u));lift=.085*math.sin(math.pi*u)
            delta=Vector((0,0,lift*.85));tilt=.025*math.sin(t);wing=.035*math.sin(t)
        elif name=='alert':
            envelope=math.sin(math.pi*phase)**2
            delta=Vector((0,0,.004*math.sin(2*t)))
            tilt=.16*envelope*math.sin(t);wing=.72*envelope
        else:
            delta=Vector((0,0,.003*math.sin(2*t)));tilt=.045*math.sin(t);wing=.015*math.sin(2*t)
        key_loc(arm,frame,'pelvis',arm.data.bones['pelvis'].matrix_local.to_3x3().inverted()@delta)
        pose={'head':world_rot(arm.pose.bones['head'],(1,0,0),tilt),
              'neck':world_rot(arm.pose.bones['neck'],(0,0,1),.035*math.sin(t)),
              'tail_feather':world_rot(arm.pose.bones['tail_feather'],(1,0,0),.035*math.sin(t))}
        for side,sign in [('l',1),('r',-1)]:
            pose[f'wing_{side}_1']=world_rot(arm.pose.bones[f'wing_{side}_1'],(0,1,0),-sign*wing)
            for i in [2,3]: pose[f'wing_{side}_{i}']=world_rot(arm.pose.bones[f'wing_{side}_{i}'],(0,0,1),sign*wing*.12)
        key_pose(arm,frame,pose);bpy.context.view_layer.update()
        contact(arm,lm,frame,delta,backward,lift)
    finish_action(arm,action)
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for curve in bag.fcurves:
                    for key in curve.keyframe_points: key.interpolation='LINEAR'


if __name__=='__main__':
    args=sys.argv[sys.argv.index('--')+1:]
    obj,original=prepare(args[0]);arm,lm=build(obj,original)
    bpy.context.scene.render.fps=FPS
    for name,seconds in [('idle',4.8),('walk',1.4),('alert',4.8)]: animate(arm,lm,name,seconds)
    bpy.ops.export_scene.gltf(filepath=args[1],export_format='GLB',export_animations=True,
        export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    print('EXPORTED',args[1],'bones',len(arm.data.bones),'two independent legs and wings')
