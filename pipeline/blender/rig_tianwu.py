"""Tianwu: eight independent three-bone feet, curved necks and tails.
The sole targets, rather than a sinusoidal upper-leg rotation, define locomotion.
Support phase moves backwards at constant speed; foot matrices stay level.
"""
import argparse
import json
import math
import sys
import struct
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix, Vector

FPS=30
DURATION={'idle':6.,'walk':4.,'special':5.}
DUTY=.68
STRIDE=.06
SPEED=STRIDE/(DURATION['walk']*DUTY)
# Bounded circle shared with runtime. The scene's +Z .75 offset puts this
# original-X point at the runtime turning pivot; compensate it in each sole.
RADIUS=.40/.68
OMEGA=SPEED/RADIUS
PIVOT=np.array([.75,0.,0.])
ANCHORS=np.array([-.368,.3765,.732,1.4765])

def smooth(x):
    x=np.clip(x,0,1);return x*x*(3-2*x)

def curve(control,t):
    a,b,c,d=np.asarray(control)
    return (1-t)**3*a+3*(1-t)**2*t*b+3*(1-t)*t*t*c+t**3*d

def distance(points,a,b):
    d=b-a;t=np.clip((points-a)@d/max(np.dot(d,d),1e-12),0,1)
    return np.linalg.norm(points-a-t[:,None]*d,axis=1)

def make_rig(obj,anatomy):
    q=np.array([tuple(v.co) for v in obj.data.vertices])
    feet=[]
    # Geometry-only masks precede skin weights. Each mask owns a real low paw.
    for pair,x in enumerate(ANCHORS):
        for side in [-1,1]:
            mask=(np.argmin(abs(q[:,0,None]-ANCHORS),axis=1)==pair)&(q[:,1]*side>0)&(q[:,2]<.14)
            p=q[mask];assert len(p)>15,('Missing actual paw',pair,side)
            sole=p[p[:,2]<p[:,2].min()+.012]
            foot=np.r_[sole[:,:2].mean(0),.09]
            knee=np.array([x+(.16 if pair<2 else -.16),foot[1]*.78,.35])
            hip=np.array([x,side*.125,.63])
            feet.append({'name':f'leg_{pair}_{"l" if side<0 else "r"}',
                'hip':hip.tolist(),'knee':knee.tolist(),'foot':foot.tolist(),
                'phase':(pair*.25+(0 if side<0 else .5))%1,
                'soleMinimumZ':float(sole[:,2].min()),'actualSoleVertices':len(sole)})
    anatomy['feet']=feet
    arm=bpy.data.objects.new('tianwu_rig',bpy.data.armatures.new('eight_support_foot_rig'))
    bpy.context.collection.objects.link(arm);bpy.context.view_layer.objects.active=arm
    bpy.ops.object.select_all(action='DESELECT');arm.select_set(True);bpy.ops.object.mode_set(mode='EDIT')
    segments={}
    def bone(name,a,b,parent='body'):
        bo=arm.data.edit_bones.new(name);bo.head=a;bo.tail=b
        if parent:bo.parent=arm.data.edit_bones[parent]
        segments[name]=(np.asarray(a),np.asarray(b))
    bone('root',[0,0,0],[0,0,.15],None)
    bone('body',[.7,0,.64],[-.3,0,.70],'root')
    for rec in feet:
        name=rec['name'];h,k,f=rec['hip'],rec['knee'],rec['foot']
        bone(name+'_upper',h,k);bone(name+'_lower',k,f,name+'_upper')
        # Independent sole effector: its absolute orientation and translation
        # cannot inherit interpolation error from the upper/lower chain.
        bone(name+'_foot',f,(np.array(f)+[-.12,0,0]).tolist(),'root')
    for kind in ['heads','tails']:
        for i,rec in enumerate(anatomy[kind]):
            pts=[curve(rec['control'],t) for t in np.linspace(0,1,6)]
            prefix='neck' if kind=='heads' else 'tail'
            for j in range(5):bone(f'{prefix}_{i}_{j}',pts[j],pts[j+1],'body' if j==0 else f'{prefix}_{i}_{j-1}')
            if kind=='heads':bone(f'head_{i}',pts[-1],np.array(rec['headCenter'])+[0,0,.12],f'neck_{i}_4')
    bpy.ops.object.mode_set(mode='OBJECT')
    # Rank nearby source-defined segments. At most four influences per vertex.
    names=list(segments);ds=np.stack([distance(q,*segments[n]) for n in names],axis=1)
    weights=np.zeros_like(ds);idx={n:i for i,n in enumerate(names)}
    weights[:,idx['body']]=1
    for rec in feet:
        name=rec['name'];f=np.array(rec['foot']);pair=int(np.argmin(abs(ANCHORS-f[0])));side=np.sign(f[1]);x=ANCHORS[pair]
        mask=(np.argmin(abs(q[:,0,None]-ANCHORS),axis=1)==pair)&(q[:,1]*side>0)&(q[:,2]<.57)&((abs(q[:,0]-x)<.17)|(q[:,2]<.14))
        for v in np.flatnonzero(mask):
            z=q[v,2];weights[v]=0
            lateral=float(smooth((abs(q[v,1])-.065)/.075))
            root=0. if z<.36 else 1-(1-float(smooth((z-.36)/.21)))*lateral
            if z<.12:root=0.;w={'foot':1.}
            elif z<.26:
                t=float(smooth((z-.12)/.14));w={'foot':1-t,'lower':t}
            elif z<.44:
                t=float(smooth((z-.26)/.18));w={'lower':1-t,'upper':t}
            else:w={'upper':1.}
            weights[v,idx['body']]=root
            for label,value in w.items():weights[v,idx[name+'_'+label]]=value*(1-root)
    for kind,prefix in [('heads','neck'),('tails','tail')]:
        candidates=[n for n in names if n.startswith(prefix+'_') or (kind=='heads' and n.startswith('head_'))]
        ci=np.array([idx[n] for n in candidates]);nearest=np.min(ds[:,ci],axis=1)
        allowed=((q[:,0]<.27)&(q[:,2]>.70)&(nearest<.15)) if kind=='heads' else ((q[:,0]>1.48)&(nearest<.105))
        for v in np.flatnonzero(allowed):
            local=np.argsort(ds[v,ci])[:2];chosen=ci[local]
            raw=1/np.maximum(ds[v,chosen],.012)**4;raw/=raw.sum()
            body_blend=float(smooth((q[v,0]-1.48)/.20)) if kind=='tails' else float(smooth((q[v,2]-.70)/.18))
            weights[v]=0;weights[v,idx['body']]=1-body_blend
            weights[v,chosen]=raw*body_blend
        if kind=='heads':
            centers=np.array([rec['headCenter'] for rec in anatomy['heads']])
            nearest_head=np.argmin(np.linalg.norm(q[:,None]-centers,axis=2),axis=1)
            for i,rec in enumerate(anatomy['heads']):
                target=np.array(rec['control'][-1]);up=target-np.array(rec['control'][-2]);up/=np.linalg.norm(up)
                relative=q-target;axial=relative@up
                transverse=np.linalg.norm(relative-axial[:,None]*up,axis=1)
                # The plane is the actual donor neck section. A bounding sphere
                # misses projecting noses/chins and produces facial stretching.
                mask=(nearest_head==i)&(axial>.012)&(axial<.40)&(transverse<.22)
                weights[mask]=0;weights[mask,idx[f'head_{i}']]=1
    assert np.max(abs(weights.sum(1)-1))<1e-8
    assert np.max(np.sum(weights>0,axis=1))<=4
    for i,name in enumerate(names):
        group=obj.vertex_groups.new(name=name)
        for vertex in np.flatnonzero(weights[:,i]>0):group.add([int(vertex)],float(weights[vertex,i]),'REPLACE')
    mod=obj.modifiers.new('Continuous_eight_leg_skin','ARMATURE');mod.object=arm;obj.parent=arm
    return arm,feet

def set_segment(arm,name,a,b):
    rest=arm.data.bones[name];direction=rest.tail_local-rest.head_local
    rotation=direction.rotation_difference(Vector(b)-Vector(a)).to_matrix().to_4x4()
    matrix=Matrix.Translation(Vector(a))@rotation@rest.matrix_local.to_3x3().to_4x4()
    arm.pose.bones[name].matrix=matrix
    bpy.context.view_layer.update()

def leg_pose(arm,rec,offset,yaw=0.):
    h,k,f=[Vector(rec[key]) for key in ['hip','knee','foot']]
    target=f+Vector(offset);d=(target-h).length;u=(target-h).normalized()
    l1=(k-h).length;l2=(f-k).length
    assert abs(l1-l2)+1e-5<d<l1+l2-1e-5,('Leg target beyond anatomical reach',rec['name'],d,l1+l2)
    a=(l1*l1-l2*l2+d*d)/(2*d);height=math.sqrt(max(0,l1*l1-a*a))
    perpendicular=k-h-u*(k-h).dot(u);perpendicular.normalize()
    new_knee=h+u*a+perpendicular*height;name=rec['name']
    set_segment(arm,name+'_upper',h,new_knee);set_segment(arm,name+'_lower',new_knee,target)
    # Absolute rest orientation compensates both upper and lower limb rotation.
    arm.pose.bones[name+'_foot'].matrix=Matrix.Translation(target)@Matrix.Rotation(yaw,4,'Z')@Matrix.Translation(-f)@arm.data.bones[name+'_foot'].matrix_local

def stance_target(rec,elapsed):
    # Place the sole at its touchdown world position, then invert the current
    # circular route. Both longitudinal and lateral motion depend on paw position.
    delta=OMEGA*elapsed;c=math.cos(delta);s=math.sin(delta)
    rotation=np.array([[c,s,0],[-s,c,0],[0,0,1]])
    f=np.array(rec['foot']);lead=f-PIVOT+[-STRIDE/2,0,0]
    target=PIVOT+np.array([RADIUS*s,RADIUS*(c-1),0])+rotation@lead
    return target-f

def foot_offset(t,rec):
    p=(t/4+rec['phase'])%1;duration=4*DUTY
    if p<DUTY:
        elapsed=p*4
        return stance_target(rec,elapsed).tolist(),-OMEGA*elapsed,True
    q=(p-DUTY)/(1-DUTY);swing=4*(1-DUTY);eps=1e-4
    a=stance_target(rec,duration);b=stance_target(rec,0)
    va=(stance_target(rec,duration+eps)-stance_target(rec,duration-eps))/(2*eps)
    vb=(stance_target(rec,eps)-stance_target(rec,-eps))/(2*eps)
    h00=2*q**3-3*q*q+1;h10=q**3-2*q*q+q;h01=-2*q**3+3*q*q;h11=q**3-q*q
    offset=h00*a+h10*swing*va+h01*b+h11*swing*vb
    offset[2]=.045*math.sin(math.pi*q)**2
    yaw=h00*(-OMEGA*duration)+(h10+h11)*swing*(-OMEGA)
    return offset.tolist(),yaw,False

def animate(arm,feet,anatomy):
    scene=bpy.context.scene;scene.render.fps=FPS
    qa=[]
    for name,duration in DURATION.items():
        action=bpy.data.actions.new(name)
        if not arm.animation_data:arm.animation_data_create()
        arm.animation_data.action=action
        for frame in range(round(duration*FPS)+1):
            scene.frame_set(frame);t=frame/FPS
            for pb in arm.pose.bones:pb.matrix_basis=Matrix.Identity(4)
            envelope=math.sin(math.pi*t/duration)**4 if name=='special' else 0
            # Body breath remains small; grounded paws always use absolute targets.
            body=arm.pose.bones['body'];body.rotation_mode='XYZ'
            body.rotation_euler.x=.005*math.sin(2*math.pi*t/duration)
            bpy.context.view_layer.update()
            for rec in feet:
                offset,yaw,support=foot_offset(t,rec) if name=='walk' else ([0,0,0],0.,True)
                leg_pose(arm,rec,offset,yaw)
                if name=='walk':qa.append({'frame':frame,'time':t,'foot':rec['name'],'support':support,'offset':offset,'soleYaw':yaw})
            for i in range(8):
                for j in range(5):
                    neck=arm.pose.bones[f'neck_{i}_{j}'];neck.rotation_mode='XYZ'
                    neck.rotation_euler.x=.009*math.sin(2*math.pi*t/duration+i*.6-j*.2)+.025*envelope
                    tail=arm.pose.bones[f'tail_{i}_{j}'];tail.rotation_mode='XYZ'
                    tail.rotation_euler.x=(.035+.06*envelope)*math.sin(2*math.pi*t/duration+i*.52-j*.4)
                    tail.rotation_euler.z=.018*math.sin(2*math.pi*t/duration+i*.8-j*.3)
            for pb in arm.pose.bones:
                pb.rotation_mode='QUATERNION' if pb.name.startswith('leg_') else pb.rotation_mode
                pb.keyframe_insert('location',frame=frame)
                pb.keyframe_insert('rotation_quaternion' if pb.rotation_mode=='QUATERNION' else 'rotation_euler',frame=frame)
        # All clips are exported as named NLA strips. No stale active action.
        arm.animation_data.action=None
        track=arm.animation_data.nla_tracks.new();track.name=name;track.strips.new(name,0,action)
        track.mute=True
    return qa

def main():
    ap=argparse.ArgumentParser();ap.add_argument('source');ap.add_argument('output');ap.add_argument('--preview');ap.add_argument('--anatomy')
    a=ap.parse_args(sys.argv[sys.argv.index('--')+1:]);source=Path(a.source).resolve();out=Path(a.output).resolve();out.parent.mkdir(parents=True,exist_ok=True)
    data=source.read_bytes()
    if data[:4]==b'glTF':
        length=struct.unpack_from('<I',data,12)[0];document=json.loads(data[20:20+length])
        native=next((node.get('extras',{}).get('tianwuNativePlan') for node in document.get('nodes',[]) if node.get('extras',{}).get('tianwuNativePlan')),None)
        if native:
            assert json.loads(native)['version']==1 and document.get('skins'),'Invalid pre-rigged native mother'
            out.write_bytes(data)
            print('SKIN Native High core retained; three actions are driven by owned runtime skeletons');return
    anatomy_path=Path(a.anatomy) if a.anatomy else source.parent/'anatomy.json'
    anatomy=json.loads(anatomy_path.read_text());bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source),disable_bone_shape=True)
    obj=next(o for o in bpy.context.scene.objects if o.type=='MESH')
    bpy.context.view_layer.objects.active=obj;bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    arm,feet=make_rig(obj,anatomy);qa=animate(arm,feet,anatomy)
    arm.rotation_euler.z=math.pi/2
    bpy.context.scene.frame_set(0)
    for track in arm.animation_data.nla_tracks:track.mute=False
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);arm.select_set(True);bpy.context.view_layer.objects.active=arm
    bpy.ops.export_scene.gltf(filepath=str(out),export_format='GLB',use_selection=True,
        export_animations=True,export_animation_mode='NLA_TRACKS',export_frame_range=False,
        export_force_sampling=True,export_anim_slide_to_zero=True,export_skins=True,export_yup=True)
    anatomy.update({'duty':DUTY,'stride':STRIDE,'speed':SPEED,'durations':DURATION,
        'coordinateTransform':'Blender original X longitudinal rotated +90deg around Z: front glTF +Z',
        'derivedAnatomy':True,'productionAccepted':False,
        'route':{'kind':'circle','sourceRadius':RADIUS,'runtimeUniformScale':.60,'runtimeRadius':RADIUS*.60,'angularSpeed':OMEGA,'sourcePivot':PIVOT.tolist(),'support':'world-fixed sole position and orientation inverted into rotating body space'}})
    (out.parent/'anatomy.json').write_text(json.dumps(anatomy,indent=2))
    (out.parent/'support-targets.json').write_text(json.dumps(qa))
    print('TIANWU_RIG',json.dumps({'bones':len(arm.data.bones),'feet':len(feet),'speed':SPEED,'output':str(out)}))
if __name__=='__main__':main()
