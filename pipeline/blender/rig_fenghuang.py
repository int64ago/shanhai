"""Rig the new HIGH chicken body and paired HIGH wing master.
Independent thigh/shank/rigid toe chains maintain actual sole XYZ and heading;
three-segment wings fold backwards over the flanks and open for a grounded dance.
"""
import math
import sys
from pathlib import Path
import bpy
from mathutils import Vector
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from rig_avian import FPS,load,new_action,finish_action,key_loc,key_pose,world_rot
from rig_qique import contact


def smooth(a,b,x):
    t=max(0,min(1,(x-a)/(b-a)));return t*t*(3-2*t)


def make_rig(obj):
    members={}
    for poly in obj.data.polygons:
        name=obj.data.materials[poly.material_index].name
        members.setdefault(name,set()).update(poly.vertices)
    body=members['fowl_plumage']
    lm={'pelvis':Vector((0,-.04,.410)), 'chest':Vector((0,-.10,.570)),
        'neck_base':Vector((0,-.21,.710)), 'head_base':Vector((0,-.29,.815)),
        'beak_tip':Vector((0,-.385,.812)), 'tail_base':Vector((0,.16,.55)),
        'tail_tip':Vector((0,.44,.66)), 'feet':{}}
    for side,sign in [('l',1),('r',-1)]:
        shank=[obj.data.vertices[i].co for i in body if sign*obj.data.vertices[i].co.x>.04 and .065<obj.data.vertices[i].co.z<.10]
        mid=sum(shank,Vector())/len(shank)
        lm['feet'][side]=Vector((mid.x,mid.y,.075))
    arm=bpy.data.objects.new('rig',bpy.data.armatures.new('rig'))
    bpy.context.collection.objects.link(arm);bpy.context.view_layer.objects.active=arm
    bpy.ops.object.mode_set(mode='EDIT');eb=arm.data.edit_bones
    def bone(name,a,b,parent=None,deform=True):
        item=eb.new(name);item.head=a;item.tail=b;item.use_deform=deform
        if parent:item.parent=eb[parent]
    bone('root',(0,0,0),(0,0,.1),deform=False)
    for name,a,b,parent in [('pelvis','pelvis','chest','root'),('chest','chest','neck_base','pelvis'),
                            ('neck','neck_base','head_base','chest'),('head','head_base','beak_tip','neck'),
                            ('tail_feather','tail_base','tail_tip','pelvis')]:bone(name,lm[a],lm[b],parent)
    for side,foot in lm['feet'].items():
        hip=Vector((foot.x*.88,-.065,.35));knee=Vector((foot.x*.90,-.105,.205))
        bone(f'leg_{side}_upper',hip,knee,'pelvis')
        bone(f'leg_{side}_lower',knee,foot,f'leg_{side}_upper')
        bone(f'foot_{side}',foot,foot+Vector((0,-.13,-.065)),f'leg_{side}_lower')
    for side,sign in [('l',1),('r',-1)]:
        points=[Vector((sign*x,-.180,.570)) for x in [.120,.280,.455,.720]]
        for i in range(3):bone(f'wing_{side}_{i+1}',points[i],points[i+1],'chest' if i==0 else f'wing_{side}_{i}')
    bpy.ops.object.mode_set(mode='OBJECT')
    bones={b.name:b for b in arm.data.bones if b.use_deform}
    groups={name:obj.vertex_groups.new(name=name) for name in bones}
    def weighted(index,names):
        p=obj.data.vertices[index].co;scored=[]
        for name in names:
            b=bones[name];axis=b.tail_local-b.head_local
            t=max(0,min(1,(p-b.head_local).dot(axis)/max(axis.length_squared,1e-8)))
            distance=max((b.head_local+axis*t-p).length,.001);scored.append((distance,name))
        scored.sort();scored=scored[:3];total=sum(d**-5 for d,_ in scored)
        for d,name in scored:groups[name].add([index],d**-5/total,'REPLACE')
    for i in body:
        p=obj.data.vertices[i].co;side='l' if p.x>=0 else 'r'
        if p.z<.10:
            groups[f'foot_{side}'].add([i],1,'REPLACE')
        elif p.z<.24 and -.22<p.y<.04 and abs(p.x)>.065:
            weighted(i,[f'leg_{side}_upper',f'leg_{side}_lower',f'foot_{side}'])
        elif p.y>.15 and p.z>.42:
            weighted(i,['tail_feather','pelvis'])
        else:
            names=['pelvis','chest','neck','head']
            weighted(i,names)
            # Feathered thighs blend radially into the pelvis. A hard height
            # split pulls broad belly feathers into long strips on leg lift.
            leg=bones[f'leg_{side}_upper'];axis=leg.tail_local-leg.head_local
            t=max(0,min(1,(p-leg.head_local).dot(axis)/axis.length_squared))
            distance=(p-leg.head_local-axis*t).length
            blend=(1-smooth(.25,.40,p.z))*(1-smooth(.045,.095,distance))
            if blend>0:
                for name in names:
                    try:weight=groups[name].weight(i)
                    except RuntimeError:continue
                    groups[name].add([i],weight*(1-blend),'REPLACE')
                groups[leg.name].add([i],blend,'REPLACE')
    for side in ['l','r']:
        for i in members[f'flight_{side}']:weighted(i,[f'wing_{side}_{j}' for j in [1,2,3]])
    mod=obj.modifiers.new('rig','ARMATURE');mod.object=arm;obj.parent=arm
    print('LANDMARKS',lm);print('SKIN',len(obj.data.vertices),'vertices',len(arm.data.bones),'bones')
    return arm,lm


def animate(arm,lm,name,seconds):
    action=new_action(arm,name);n=round(seconds*FPS)
    for f in range(n+1):
        t=f/FPS;phase=f/n;wave=math.sin(phase*math.tau)
        spread=0;neck=.020*wave;head=.012*wave
        delta=Vector((0,0,-.010+.002*math.cos(phase*math.tau*2)))
        targets={s:(0,0) for s in ['l','r']}
        if name=='walk':
            for side,offset in [('l',0),('r',.5)]:
                p=(phase+offset)%1;duty=.65;distance=.12*seconds*duty
                if p<duty:back=-distance/2+distance*p/duty;lift=0
                else:
                    u=(p-duty)/(1-duty);back=distance/2-distance*(u*u*(3-2*u));lift=.050*math.sin(u*math.pi)
                targets[side]=(back,lift)
            neck=.028*math.sin(phase*math.tau*2)
        elif name=='alert':
            envelope=smooth(.2,.9,t)*(1-smooth(4.4,5.1,t))
            spread=envelope*(.90+.10*math.cos((t-.9)*math.tau/1.6))
            for side,begin in [('l',1.0),('r',2.65)]:
                u=(t-begin)/1.25
                if 0<u<1:targets[side]=(-.024*math.sin(u*math.pi),.065*math.sin(u*math.pi)**2)
            neck=.055*envelope+.020*wave;head=.035*envelope*math.sin(t*5)
        key_loc(arm,f,'pelvis',arm.data.bones['pelvis'].matrix_local.to_3x3().inverted()@delta)
        pose={'neck':world_rot(arm.pose.bones['neck'],(1,0,0),neck),
              'head':world_rot(arm.pose.bones['head'],(1,0,0),head),
              'tail_feather':world_rot(arm.pose.bones['tail_feather'],(0,0,1),.045*wave*(1+spread))}
        for side,sign in [('l',1),('r',-1)]:
            for i in [1,2,3]:
                fold=(.31-.24*spread) if i==1 else .020*math.sin(t*2-i)*spread
                sweep=((1.45 if i==1 else .08)*(1-spread))
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
    print('EXPORTED',args[1],'grounded alternating two-foot dance; independent HIGH wings')


if __name__=='__main__':main()
