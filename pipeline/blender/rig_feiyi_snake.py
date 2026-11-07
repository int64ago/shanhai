"""Twenty-four segment snake spine, six planted articulated legs and four feather wings.
Circular stance targets match FeiyiSnake.tsx exactly in XYZ and sole direction.
"""
import math
import sys
from pathlib import Path
import bpy
from mathutils import Matrix, Vector
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_quadruped as base
from rig_jingwei import set_segment
from prepare_feiyi_snake import LEG_ROWS, WING_ROWS

FPS = 30
SPINE = 24
WINGS = 5
RADIUS = 1.5
SPEED = .085
PERIOD = 2.4
DUTY = .70


def smooth(a, b, x):
    t = max(0, min(1, (x-a)/(b-a)))
    return t*t*(3-2*t)


def axial(y):
    return f'serpent_{max(0,min(SPINE-1,int((y+1.4)/2.8*SPINE))):02}'


def build(meshes):
    body = bpy.data.objects['feiyi_snake_body']
    verts = [v.co for v in body.data.vertices]
    centers = []
    for i in range(SPINE+1):
        y = -1.4 + 2.8*i/SPINE
        section = [q for q in verts if abs(q.y-y)<.065]
        centers.append(Vector(((min(q.x for q in section)+max(q.x for q in section))/2,y,
                               (min(q.z for q in section)+max(q.z for q in section))/2)))
    arm = bpy.data.objects.new('feiyi_snake_rig', bpy.data.armatures.new('feiyi_snake_rig'))
    bpy.context.collection.objects.link(arm); bpy.context.view_layer.objects.active=arm
    bpy.ops.object.mode_set(mode='EDIT'); eb=arm.data.edit_bones
    def bone(name, a, b, parent):
        item=eb.new(name); item.head=a; item.tail=b
        if parent: item.parent=eb[parent]
        return item
    bone('root',(0,0,0),(0,0,.1),None)
    for i in range(SPINE):
        bone(f'serpent_{i:02}',centers[i],centers[i+1],'root' if i==0 else f'serpent_{i-1:02}')
    landmarks={}
    for obj in meshes:
        if not obj.name.startswith('feiyi_leg_'): continue
        pts=[v.co for v in obj.data.vertices]; height=max(q.z for q in pts)
        # Several non-collinear plantar vertices survive texture seams/export.
        for v in obj.data.vertices:
            if v.co.z<height*.11: v.co.z=max(0,v.co.z-height*.045)
        side=1 if obj.name.endswith('_l') else -1
        row=int(obj.name.split('_')[2]); y=LEG_ROWS[row]
        hip=Vector((side*.060,y,.350))
        band=[q for q in pts if abs(q.z-.195)<.025]
        knee=sum(band,Vector())/len(band)
        band=[q for q in pts if abs(q.z-.070)<.02]
        foot=sum(band,Vector())/len(band); foot.z=.065
        leg=obj.name
        bone(leg+'_upper',hip,knee,axial(y))
        bone(leg+'_lower',knee,foot,leg+'_upper')
        bone(leg+'_foot',foot,foot+Vector((0,-.09,0)),leg+'_lower')
        landmarks[leg]=(hip,knee,foot)
    for row,y in enumerate(WING_ROWS):
        for side,label in [(1,'l'),(-1,'r')]:
            span=.84*(1 if row==0 else .8)
            root=Vector((side*.045,y,.395))
            for i in range(WINGS):
                a=root+Vector((side*span*i/WINGS,.14*span*i/WINGS,.12*span*i/WINGS))
                b=root+Vector((side*span*(i+1)/WINGS,.14*span*(i+1)/WINGS,.12*span*(i+1)/WINGS))
                name=f'feiyi_wing_{row}_{label}_{i}'
                bone(name,a,b,axial(y) if i==0 else f'feiyi_wing_{row}_{label}_{i-1}')
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm,centers,landmarks


def bind(mesh,arm):
    names=[]
    if mesh.name=='feiyi_snake_body': names=[f'serpent_{i:02}' for i in range(SPINE)]
    elif mesh.name.startswith('feiyi_leg_'): names=[mesh.name+s for s in ('_upper','_lower','_foot')]
    else: names=[mesh.name+f'_{i}' for i in range(WINGS)]
    groups={n:mesh.vertex_groups.new(name=n) for n in names}
    for v in mesh.data.vertices:
        q=v.co
        if mesh.name=='feiyi_snake_body':
            k=max(0,min(SPINE-1,(q.y+1.4)/2.8*SPINE-.5)); lo=int(k); w=k-lo
        elif mesh.name.startswith('feiyi_wing_'):
            row=int(mesh.name.split('_')[2]); span=.84*(1 if row==0 else .8)
            k=max(0,min(WINGS-1,(abs(q.x)-.045)/span*WINGS-.5)); lo=int(k); w=k-lo
        else:
            if q.z<.105:
                groups[names[2]].add([v.index],1,'REPLACE');continue
            scored=[]
            for n in names[:2]:
                bone=arm.data.bones[n]; a=bone.head_local; ab=bone.tail_local-a
                t=max(0,min(1,(q-a).dot(ab)/ab.length_squared))
                scored.append(max(.005,(q-a-ab*t).length)**-5)
            total=sum(scored)
            for n,score in zip(names,scored): groups[n].add([v.index],score/total,'REPLACE')
            continue
        groups[names[lo]].add([v.index],1-w,'REPLACE')
        if w and lo+1<len(names): groups[names[lo+1]].add([v.index],w,'REPLACE')
    modifier=mesh.modifiers.new('anatomical feiyi skin','ARMATURE');modifier.object=arm;mesh.parent=arm


def key(pb,frame):
    pb.keyframe_insert('location',frame=frame);pb.keyframe_insert('rotation_quaternion',frame=frame)


def contact(arm,leg,frame,relative,lift):
    upper=arm.pose.bones[leg+'_upper'];lower=arm.pose.bones[leg+'_lower'];foot=arm.pose.bones[leg+'_foot']
    parent=upper.parent
    hip=parent.matrix @ parent.bone.matrix_local.inverted() @ upper.bone.head_local
    ankle=foot.bone.head_local
    yaw=-SPEED/RADIUS*relative
    x,y=ankle.x-RADIUS,ankle.y
    target=Vector((RADIUS+math.cos(yaw)*x-math.sin(yaw)*y,math.sin(yaw)*x+math.cos(yaw)*y,ankle.z+lift))
    axis=target-hip;direction=axis.normalized();l1,l2=upper.bone.length,lower.bone.length
    distance=axis.length
    if distance>l1+l2: raise RuntimeError(f'{leg}: unreachable planted foot {distance} > {l1+l2}')
    along=(l1*l1-l2*l2+distance*distance)/(2*distance)
    rest=upper.bone.tail_local-upper.bone.head_local
    normal=rest-direction*rest.dot(direction)
    if normal.length<1e-5:normal=Vector((0,-1,0))
    normal.normalize()
    knee=hip+direction*along+normal*math.sqrt(max(0,l1*l1-along*along))
    set_segment(upper,hip,knee);set_segment(lower,knee,target)
    foot.matrix=Matrix.Translation(target)@Matrix.Rotation(yaw,4,'Z')@Matrix.Translation(-ankle)@foot.bone.matrix_local
    bpy.context.view_layer.update()
    for pb in (upper,lower,foot):key(pb,frame)


def animate(arm,centers,legs,name,seconds):
    action=base.new_action(arm,name);n=round(seconds*FPS)
    for frame in range(n+1):
        t=frame/FPS;phase=frame/n;display=smooth(.25,1.2,t)*(1-smooth(3.2,4.8,t)) if name=='special' else 0
        posed=[]
        for i,c in enumerate(centers):
            p=i/SPINE
            amplitude=.009 if name=='idle' else .020
            x=amplitude*math.sin(phase*math.tau-p*math.tau*1.1)*math.sin(math.pi*p)
            lift=.115*display*(1-smooth(-1.4,-.65,c.y))
            posed.append(c+Vector((x,0,lift)))
        for i in range(SPINE):
            pb=arm.pose.bones[f'serpent_{i:02}'];set_segment(pb,posed[i],posed[i+1]);key(pb,frame)
        for row in range(2):
            for side,label in [(1,'l'),(-1,'r')]:
                for i in range(WINGS):
                    pb=arm.pose.bones[f'feiyi_wing_{row}_{label}_{i}']
                    flap=.020*math.sin(phase*math.tau-row*.9-i*.35)+display*.09*math.sin(t*math.tau*.65-row*.8-i*.25)
                    pb.rotation_quaternion=base.world_rot(pb,(0,1,0),-side*(flap+display*.25)*(1 if i==0 else .20))
                    if i==0:pb.rotation_quaternion @= base.world_rot(pb,(0,0,1),side*(.14-.1*display))
                    key(pb,frame)
        bpy.context.view_layer.update()
        for leg in legs:
            row=int(leg.split('_')[2]);side=0 if leg.endswith('_l') else 1
            offset=((row+side)%2)*.5
            relative=lift=0
            if name=='walk':
                p=(phase+offset)%1
                if p<DUTY: relative=seconds*(p-DUTY/2)
                else:
                    u=(p-DUTY)/(1-DUTY);relative=seconds*DUTY*(.5-u*u*(3-2*u));lift=.033*math.sin(math.pi*u)
            contact(arm,leg,frame,relative,lift)
    base.finish_action(arm,action)
    for fc in base.action_fcurves(action):
        for point in fc.keyframe_points:point.interpolation='LINEAR'


def main():
    source,output=sys.argv[sys.argv.index('--')+1:]
    bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=source)
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    for o in meshes:
        bpy.context.view_layer.objects.active=o;bpy.ops.object.select_all(action='DESELECT');o.select_set(True)
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM');bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    arm,centers,legs=build(meshes)
    for mesh in meshes:bind(mesh,arm)
    bpy.context.scene.render.fps=FPS
    for name,seconds in [('idle',4.8),('walk',PERIOD),('special',4.8)]:animate(arm,centers,legs,name,seconds)
    bpy.context.scene.frame_set(0)
    bpy.ops.export_scene.gltf(filepath=output,export_format='GLB',export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False,export_optimize_animation_size=False)
    print('FEIYI_RIG',len(arm.data.bones),'bones',len(meshes),'meshes', {o.name:base.unweighted_count(o) for o in meshes})


if __name__=='__main__':main()
