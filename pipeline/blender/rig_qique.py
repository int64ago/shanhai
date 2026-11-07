"""Qique's native chicken tissue, continuous mouse feet and grounded display.
The contact function remains compatible with the other existing bird riggers.
Qique uses a straight gait; runtime world anchors cover blended transitions.
"""
import math
import sys
from pathlib import Path
import bpy
from mathutils import Matrix, Vector
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import rig_jingwei as bird
from rig_avian import FPS,load,new_action,finish_action,key_loc,key_pose,world_rot


def smooth(a,b,x):
    t=max(0,min(1,(x-a)/(b-a)));return t*t*(3-2*t)


def contact(arm,lm,side,frame,delta,backward=0,lift=0,lateral=0,yaw=0):
    ankle=lm['feet'][side]
    upper=arm.pose.bones[f'leg_{side}_upper'];lower=arm.pose.bones[f'leg_{side}_lower'];foot=arm.pose.bones[f'foot_{side}']
    hip=upper.bone.head_local+delta;target=ankle+Vector((lateral,backward,lift))
    axis=target-hip;direction=axis.normalized();distance=min(axis.length,(upper.bone.length+lower.bone.length)*.9999)
    l1,l2=upper.bone.length,lower.bone.length;along=(l1*l1-l2*l2+distance*distance)/(2*distance)
    normal=Vector((0,-direction.z,direction.y)).normalized()
    rest_axis=(lower.bone.tail_local-upper.bone.head_local).normalized();rest_normal=Vector((0,-rest_axis.z,rest_axis.y)).normalized()
    bend=1 if (upper.bone.tail_local-upper.bone.head_local).dot(rest_normal)>=0 else -1
    knee=hip+direction*along+normal*math.sqrt(max(0,l1*l1-along*along))*bend
    bird.set_segment(upper,hip,knee);bird.set_segment(lower,knee,target)
    foot.matrix=Matrix.Translation(target)@Matrix.Rotation(yaw,4,'Z')@Matrix.Translation(-ankle)@foot.bone.matrix_local
    bpy.context.view_layer.update()
    for pb in [upper,lower,foot]:
        pb.keyframe_insert('rotation_quaternion',frame=frame);pb.keyframe_insert('location',frame=frame)


def make_rig(obj):
    # Exact material membership prevents breast/flight tissue from following toes.
    members={}
    for poly in obj.data.polygons:
        members.setdefault(obj.data.materials[poly.material_index].name,set()).update(poly.vertices)
    body=members['qique_body'];skin=members['qique_skin'];claws=members['qique_claw'];flight=members['qique_flight']
    lm={'pelvis':Vector((0,-.04,.407)),'chest':Vector((0,-.10,.567)),
        'neck_base':Vector((0,-.21,.707)),'head_base':Vector((0,-.29,.812)),
        'beak_tip':Vector((-.08,-.42,.828)),'tail_base':Vector((0,.16,.547)),
        'tail_tip':Vector((0,.44,.657)),'feet':{s:Vector((sign*.101,-.145,.072)) for s,sign in [('l',1),('r',-1)]}}
    arm=bpy.data.objects.new('rig',bpy.data.armatures.new('rig'));bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active=arm;bpy.ops.object.mode_set(mode='EDIT');eb=arm.data.edit_bones
    def bone(name,a,b,parent=None,deform=True):
        item=eb.new(name);item.head=a;item.tail=b;item.use_deform=deform
        if parent:item.parent=eb[parent]
    bone('root',(0,0,0),(0,0,.1),deform=False)
    for name,a,b,parent in [('pelvis','pelvis','chest','root'),('chest','chest','neck_base','pelvis'),('neck','neck_base','head_base','chest'),('head','head_base','beak_tip','neck'),('tail_feather','tail_base','tail_tip','pelvis')]:bone(name,lm[a],lm[b],parent)
    for side,foot in lm['feet'].items():
        # A real folded knee supplies stride slack under the feathered thigh;
        # an almost straight chain runs out of reach at startup/weight shift.
        hip=Vector((foot.x,-.065,.347));knee=Vector((foot.x,-.025,.202))
        bone(f'leg_{side}_upper',hip,knee,'pelvis');bone(f'leg_{side}_lower',knee,foot,f'leg_{side}_upper')
        bone(f'foot_{side}',foot,foot+Vector((0,-.17,-.062)),f'leg_{side}_lower')
    for side,sign in [('l',1),('r',-1)]:
        points=[Vector((sign*x,-.180,.567)) for x in [.120,.280,.455,.720]]
        for i in range(3):bone(f'wing_{side}_{i+1}',points[i],points[i+1],'chest' if i==0 else f'wing_{side}_{i}')
    bpy.ops.object.mode_set(mode='OBJECT');bones={b.name:b for b in arm.data.bones if b.use_deform}
    groups={name:obj.vertex_groups.new(name=name) for name in bones}
    def weighted(index,names):
        p=obj.data.vertices[index].co;scored=[]
        for name in names:
            b=bones[name];axis=b.tail_local-b.head_local;t=max(0,min(1,(p-b.head_local).dot(axis)/max(axis.length_squared,1e-8)))
            scored.append((max((b.head_local+axis*t-p).length,.001),name))
        scored.sort();scored=scored[:3];total=sum(d**-5 for d,_ in scored)
        for d,name in scored:groups[name].add([index],d**-5/total,'REPLACE')
    for i in skin:
        p=obj.data.vertices[i].co;side='l' if p.x>=0 else 'r'
        if p.z<.09:groups[f'foot_{side}'].add([i],1,'REPLACE')
        else:weighted(i,[f'leg_{side}_upper',f'leg_{side}_lower',f'foot_{side}'])
    # An inner claw tip crosses the centreline. Assign each complete connected
    # claw to its foot; splitting individual vertices by X stretches that tip
    # between both feet during a lift. Weld UV/cap duplicates for membership only.
    parents={i:i for i in claws}
    def find(i):
        while parents[i]!=i:parents[i]=parents[parents[i]];i=parents[i]
        return i
    def union(a,b):parents[find(b)]=find(a)
    positions={}
    for i in claws:
        key=tuple(round(v,6) for v in obj.data.vertices[i].co)
        if key in positions:union(i,positions[key])
        else:positions[key]=i
    for poly in obj.data.polygons:
        ids=[i for i in poly.vertices if i in claws]
        for i in ids[1:]:union(ids[0],i)
    components={}
    for i in claws:components.setdefault(find(i),[]).append(i)
    if len(components)!=10:raise ValueError(f'Expected ten complete claws, got {len(components)}')
    for ids in components.values():
        side='l' if sum(obj.data.vertices[i].co.x for i in ids)>0 else 'r'
        groups[f'foot_{side}'].add(ids,1,'REPLACE')
    print('QIQUE_COMPLETE_CLAWS',len(components))
    for i in body:
        p=obj.data.vertices[i].co;side='l' if p.x>=0 else 'r'
        if p.y>.15 and p.z>.42:weighted(i,['tail_feather','pelvis']);continue
        names=['pelvis','chest','neck','head'];weighted(i,names)
        leg=bones[f'leg_{side}_upper'];axis=leg.tail_local-leg.head_local;t=max(0,min(1,(p-leg.head_local).dot(axis)/axis.length_squared))
        distance=(p-leg.head_local-axis*t).length
        blend=(1-smooth(.25,.40,p.z))*(1-smooth(.045,.095,distance))
        if blend>0:
            for name in names:
                try:weight=groups[name].weight(i)
                except RuntimeError:continue
                groups[name].add([i],weight*(1-blend),'REPLACE')
            groups[leg.name].add([i],blend,'REPLACE')
    for i in flight:
        side='l' if obj.data.vertices[i].co.x>=0 else 'r';weighted(i,[f'wing_{side}_{j}' for j in [1,2,3]])
    mod=obj.modifiers.new('rig','ARMATURE');mod.object=arm;obj.parent=arm
    print('QIQUE_LANDMARKS',lm);print('QIQUE_SKIN',len(obj.data.vertices),len(arm.data.bones));return arm,lm


def animate(arm,lm,name,seconds):
    action=new_action(arm,name);n=round(seconds*FPS)
    for f in range(n+1):
        t=f/FPS;phase=f/n;wave=math.sin(phase*math.tau)
        delta=Vector((0,0,-.010+.002*math.cos(phase*math.tau*2)));spread=0;neck=.018*wave
        targets={side:(0,0) for side in ['l','r']}
        if name=='walk':
            for side,offset in [('l',0),('r',.5)]:
                p=(phase+offset)%1;duty=.65;distance=.10*seconds*duty
                if p<duty:back=-distance/2+distance*p/duty;lift=0
                else:
                    u=(p-duty)/(1-duty);back=distance/2-distance*u*u*(3-2*u);lift=.055*math.sin(u*math.pi)
                targets[side]=(back,lift)
            neck=.025*math.sin(phase*math.tau*2)
        elif name=='alert':
            spread=smooth(.25,1.05,t)*(1-smooth(3.05,3.9,t));neck=.08*spread
            lift=.095*smooth(.95,1.50,t)*(1-smooth(2.10,2.80,t))
            targets['l']=(-.04*lift/.095,lift);delta.x=-.055*lift/.095
        key_loc(arm,f,'pelvis',arm.data.bones['pelvis'].matrix_local.to_3x3().inverted()@delta)
        pose={'neck':world_rot(arm.pose.bones['neck'],(1,0,0),neck),'head':world_rot(arm.pose.bones['head'],(0,0,1),.015*wave),'tail_feather':world_rot(arm.pose.bones['tail_feather'],(0,0,1),.04*wave)}
        for side,sign in [('l',1),('r',-1)]:
            for i in [1,2,3]:
                fold=(.31-.24*spread) if i==1 else .018*math.sin(t*2-i)*spread
                sweep=(1.43 if i==1 else .08)*(1-spread);pb=arm.pose.bones[f'wing_{side}_{i}']
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
    # Only move the accepted sculpt to its authored lowest contact level. No
    # foot flattening or geometry simplification is performed during rigging.
    for v in obj.data.vertices:v.co.z-=.003
    arm,lm=make_rig(obj)
    for name,seconds in [('idle',4),('walk',1.6),('alert',4.2)]:animate(arm,lm,name,seconds)
    bpy.ops.export_scene.gltf(filepath=args[1],export_format='GLB',export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    print('EXPORTED',args[1],'18 bones; straight stance; left claw display, right support')

if __name__=='__main__':main()
