"""Kuafu's native body, continuous replacement wrists and two held snakes.

Uniform normalization only after the preparation stage. Actual sole contact QA.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Vector
import rig_quadruped as base
from rig_yingzhao import contact

HEIGHT,FPS,RADIUS,SPEED,SECONDS,DUTY=1.9,30,1.,.09,2.6,.67


def smooth(a,b,x):
    t=max(0.,min(1.,(x-a)/(b-a)))
    return t*t*(3-2*t)


def make_rig(supports):
    arm=bpy.data.objects.new('kuafu_rig',bpy.data.armatures.new('kuafu_native'))
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active=arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(name,start,end,parent=None):
        b=arm.data.edit_bones.new(name)
        b.head,b.tail=Vector(start)*HEIGHT,Vector(end)*HEIGHT
        if parent:b.parent=arm.data.edit_bones[parent]
    bone('root',(0,0,0),(0,0,.1))
    bone('hips',(0,.06,.43),(0,.05,.61),'root')
    bone('chest',(0,.05,.61),(0,.04,.80),'hips')
    bone('neck',(0,.04,.80),(0,.04,.88),'chest')
    bone('head',(0,.04,.88),(0,.04,.99),'neck')
    for sign,side in [(1,'l'),(-1,'r')]:
        bone(f'leg_{side}_upper',(sign*.103,.075,.43),(sign*.108,.068,.225),'hips')
        bone(f'leg_{side}_lower',(sign*.108,.068,.225),(sign*.108,.077,.046),f'leg_{side}_upper')
        bone(f'leg_{side}_foot',(sign*.108,.077,.046),(sign*.11,-.006,.017),f'leg_{side}_lower')
        bone(f'arm_{side}_upper',(sign*.13,.04,.79),(sign*.158,.08,.623),'chest')
        bone(f'arm_{side}_lower',(sign*.158,.08,.623),(sign*.186,.025,.619),f'arm_{side}_upper')
        bone(f'arm_{side}_hand',(sign*.186,.025,.619),(sign*.246,-.085,.622),f'arm_{side}_lower')
        ear=(.065,.058,.906) if sign>0 else (-.069,.060,.913)
        bone(f'ear_{side}_attach',ear,(ear[0]+sign*.02,ear[1],ear[2]),'head')
        support=Vector(supports[side])
        bone(f'held_{side}_root',support,support+Vector((0,0,.025)),f'arm_{side}_hand')
        for branch,direction,length in [('upper',1,.33),('lower',-1,.27)]:
            parent=f'held_{side}_root'
            for i in range(1,7):
                start=support+Vector((0,0,direction*length*(i-1)/6))
                end=support+Vector((0,0,direction*length*i/6))
                name=f'held_{side}_{branch}_{i}'
                bone(name,start,end,parent);parent=name
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm


def distance(p,bone):
    delta=bone.tail_local-bone.head_local
    t=max(0,min(1,(p-bone.head_local).dot(delta)/delta.length_squared))
    return (p-bone.head_local-delta*t).length


def skin_body(obj,arm):
    names=[b.name for b in arm.data.bones if not b.name.startswith(('held_','ear_'))]
    groups={n:obj.vertex_groups.new(name=n) for n in names}
    soles={'l':[],'r':[]}
    def inverse(p,names):
        w={n:1/max(.012*HEIGHT,distance(p,arm.data.bones[n]))**4 for n in names}
        total=sum(w.values())
        return {n:v/total for n,v in w.items()}
    for v in obj.data.vertices:
        p=v.co;z=p.z/HEIGHT;x=abs(p.x)/HEIGHT
        side='l' if p.x>0 else 'r';sign=1 if p.x>0 else -1
        if z<.068:
            w={f'leg_{side}_foot':1.}
            if p.z<.0035:soles[side].append(v.index)
        elif z<.32:
            w=inverse(p,[f'leg_{side}_{s}' for s in ['upper','lower','foot']])
            rigid=1-smooth(.068,.13,z)
            w={n:v*(1-rigid)for n,v in w.items()};w[f'leg_{side}_foot']+=rigid
            hip=smooth(.275,.32,z)
            w={n:v*(1-hip)for n,v in w.items()};w['hips']=hip
        elif z>.865:
            w={'head':1.}
        elif x>.13 and .50<z<.80:
            axis=Vector((sign*.55,-.835,.02)).normalized()
            wrist=Vector((sign*.186,.025,.619))*HEIGHT
            along=(p-wrist).dot(axis)/HEIGHT
            if along>.008:
                w={f'arm_{side}_hand':1.}
            else:
                w=inverse(p,[f'arm_{side}_{s}'for s in ['upper','lower','hand']])
                torso=1-smooth(.125,.16,x)
                w={n:v*(1-torso)for n,v in w.items()};w['chest']=torso
        else:
            w=inverse(p,['hips','chest','neck']) if z>.54 else {'hips':1.}
        w=dict(sorted(((n,v)for n,v in w.items()if v>1e-7),key=lambda it:it[1],reverse=True)[:4])
        total=sum(w.values())
        for name,value in w.items():groups[name].add([v.index],value/total,'REPLACE')
    modifier=obj.modifiers.new('kuafu_skin','ARMATURE');modifier.object=arm;obj.parent=arm
    return soles


def skin_snake(obj,arm,side,support):
    groups={n:obj.vertex_groups.new(name=n)for n in [b.name for b in arm.data.bones if b.name.startswith(f'held_{side}_')]}
    for v in obj.data.vertices:
        dz=v.co.z/HEIGHT-support[2]
        # The entire four-finger contact band is rigid with the hand.
        distance=max(0,abs(dz)-.039)
        branch='upper' if dz>=0 else 'lower'
        step=(.33 if dz>=0 else .27)/6
        t=min(6,distance/step)
        low=int(t);high=min(6,low+1);f=t-low
        def name(i):return f'held_{side}_root' if i==0 else f'held_{side}_{branch}_{i}'
        groups[name(low)].add([v.index],1-f,'REPLACE')
        if f:groups[name(high)].add([v.index],f,'REPLACE')
    modifier=obj.modifiers.new('supported_serpent_skin','ARMATURE');modifier.object=arm;obj.parent=arm


def animate(arm,name,seconds):
    action=base.new_action(arm,name)
    count=round(seconds*FPS)
    for frame in range(count+1):
        t=frame/FPS;phase=frame/count
        show=smooth(.3,1.2,t)*(1-smooth(2.7,4,t)) if name=='special' else 0
        delta=Vector((0,0,-.012 if name=='walk' else 0))
        pose={}
        for sign,side in [(1,'l'),(-1,'r')]:
            for part,value in [('upper',-.12*show),('lower',-.10*show)]:
                b=arm.pose.bones[f'arm_{side}_{part}']
                pose[b.name]=base.world_rot(b,base.X,value+.005*math.sin(phase*math.tau))
            for branch in ['upper','lower']:
                for i in range(1,7):
                    b=arm.pose.bones[f'held_{side}_{branch}_{i}']
                    amount=(.006+.014*show)*i/6*math.sin(phase*math.tau-i*.6+sign)
                    pose[b.name]=base.world_rot(b,base.Y,amount)
        for part in ['chest','head']:
            b=arm.pose.bones[part]
            pose[part]=base.world_rot(b,base.X,.003*math.sin(phase*math.tau))
        base.key_loc(arm,frame,'root',arm.data.bones['root'].matrix_local.to_3x3().inverted()@delta)
        base.key_pose(arm,frame,pose)
        bpy.context.view_layer.update()
        for side,offset in [('l',0),('r',.5)]:
            lateral=backward=lift=yaw=0
            if name=='walk':
                p=(phase+offset)%1
                if p<DUTY:relative=seconds*(p-DUTY/2)
                else:
                    u=(p-DUTY)/(1-DUTY);relative=seconds*DUTY*(.5-u*u*(3-2*u));lift=.055*math.sin(math.pi*u)
                yaw=-SPEED/RADIUS*relative
                ankle=arm.data.bones[f'leg_{side}_foot'].head_local
                x,y=ankle.x-RADIUS,ankle.y
                lateral=RADIUS+math.cos(yaw)*x-math.sin(yaw)*y-ankle.x
                backward=math.sin(yaw)*x+math.cos(yaw)*y-ankle.y
            contact(arm,f'leg_{side}',frame,delta,lateral,backward,lift,yaw)
    base.finish_action(arm,action)
    for curve in base.action_fcurves(action):
        for key in curve.keyframe_points:key.interpolation='LINEAR'
    return action


def sole_qa(obj,arm,soles,actions):
    report={}
    for name,seconds in [('idle',4.),('walk',SECONDS),('special',4.)]:
        arm.animation_data.action=actions[name]
        plants={};minimum=1e9;maximum=-1e9;drift=0
        for step in range(round(seconds*FPS*2)+1):
            t=step/(FPS*2);frame=min(t,seconds)*FPS
            bpy.context.scene.frame_set(int(frame),subframe=frame-int(frame))
            evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=evaluated.to_mesh()
            points=np.array([list(v.co)for v in mesh.vertices]);evaluated.to_mesh_clear()
            assert np.isfinite(points).all()
            for side,offset in [('l',0),('r',.5)]:
                sole=points[soles[side]].copy()
                if name=='walk':
                    raw=t/seconds+offset
                    if not .025<raw%1<DUTY-.025:continue
                    theta=math.pi/2-SPEED/RADIUS*t;phi=math.pi-theta
                    rot=np.array([[math.cos(phi),-math.sin(phi),0],[math.sin(phi),math.cos(phi),0],[0,0,1]])
                    sole=sole@rot.T+np.array([RADIUS*math.cos(theta),-RADIUS*math.sin(theta),0]);key=(side,math.floor(raw))
                else:key=(side,0)
                minimum=min(minimum,float(sole[:,2].min()));maximum=max(maximum,float(sole[:,2].max()))
                if key not in plants:plants[key]=sole.copy()
                drift=max(drift,float(np.linalg.norm(sole-plants[key],axis=1).max()))
        report[name]=dict(minHeight=minimum,maxHeight=maximum,maxStanceDrift=drift,soleVertices={s:len(v)for s,v in soles.items()})
        assert minimum>-.002 and maximum<.006 and drift<.0015,report[name]
    arm.animation_data.action=None
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('output',type=Path);parser.add_argument('--preview',type=Path)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.source.resolve()))
    objects=[o for o in bpy.context.scene.objects if o.type=='MESH']
    body=next(o for o in objects if o.name=='kuafu_native_body')
    snakes={s:next(o for o in objects if o.name==f'kuafu_held_snake_{s}')for s in ['l','r']}
    supports={s:list(o['support'])for s,o in snakes.items()}
    for obj in objects:
        transform=obj.matrix_world.copy()
        normal_matrix=transform.to_3x3().inverted().transposed()
        normals=[(normal_matrix@n.vector).normalized()for n in obj.data.corner_normals]
        obj.parent=None;obj.matrix_world.identity()
        for v in obj.data.vertices:v.co=(transform@v.co)*HEIGHT
        obj.data.update();obj.data.normals_split_custom_set(normals)
    bpy.ops.object.select_all(action='DESELECT')
    arm=make_rig(supports);soles=skin_body(body,arm)
    for side,obj in snakes.items():skin_snake(obj,arm,side,supports[side])
    bpy.context.scene.render.fps=FPS
    actions={n:animate(arm,n,s)for n,s in [('idle',4.),('walk',SECONDS),('special',4.)]}
    qa=sole_qa(body,arm,soles,actions)
    bpy.context.scene.frame_set(0)
    for b in arm.pose.bones:b.rotation_quaternion=(1,0,0,0);b.location=(0,0,0)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects+[arm]:obj.select_set(True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(args.output.resolve()),export_format='GLB',use_selection=True,
                             export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_extras=True)
    report=dict(bones=len(arm.data.bones),clips=list(actions),soles=qa,supports=supports,height=HEIGHT,
                runtime=dict(radius=RADIUS,speed=SPEED,walkSeconds=SECONDS,duty=DUTY),
                outputSha256=hashlib.sha256(args.output.read_bytes()).hexdigest())
    args.output.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
    print('KUAFU_RIG '+json.dumps(report),flush=True)
    if args.preview:
        from turnaround import setup_render
        cam=setup_render(768);target=Vector((0,0,HEIGHT*.5));cam.location=target+Vector((2.5,-3.5,1.1))
        cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.ortho_scale=HEIGHT*1.2
        bpy.context.scene.render.filepath=str(args.preview.resolve());bpy.context.view_layer.update();bpy.ops.render.render(write_still=True)


if __name__=='__main__':main()
