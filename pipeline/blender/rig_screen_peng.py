"""Screen Peng's lateral head chains and four-paw planted gait.
Own idle/walk/alert clips. Walk is a 1.8s four-beat cycle at .14 units/s,
.78 stance duty, flat counter-rotated paws. Alert looks outward with all four
paws fixed. The text records no species, gait or sound; all are inference.
"""
import math
import sys
from pathlib import Path
import bpy
from mathutils import Vector
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import rig_quadruped as rig
from rig_quadruped import X, new_action, finish_action, key_loc, key_pose, world_rot
# Dense sampling includes exact quarter-cycle paw landings and keeps the
# nonlinear IK interpolation flat through the stance/swing boundaries.
FPS=120
LEGS=('front_l','front_r','back_l','back_r')


def smooth(a,b,x):
    t=max(0,min(1,(x-a)/(b-a)));return t*t*(3-2*t)


def tail_point(t):
    return Vector((.055*math.sin(t*math.pi),.40+.60*t,.61-.25*math.sin(t*math.pi*.8)))


def make_rig(obj):
    lm=rig.landmarks(obj);arm=rig.build_armature(lm,headless=True)
    bpy.context.view_layer.objects.active=arm;bpy.ops.object.mode_set(mode='EDIT');eb=arm.data.edit_bones
    for side,sign in [('l',1),('r',-1)]:
        root=Vector((sign*.130,-.245,.845))
        points=[Vector((sign*.035,-.185,.665)),Vector((sign*.085,-.210,.735)),Vector((sign*.120,-.235,.800)),root]
        names=[f'neck_{side}',f'neck_{side}_mid',f'neck_{side}_tip']
        for i,name in enumerate(names):
            bone=eb.new(name);bone.head=points[i];bone.tail=points[i+1];bone.parent=eb['chest' if i==0 else names[i-1]]
        bone=eb.new(f'head_{side}');bone.head=root;bone.tail=root+Vector((sign*.14,-.07,.02));bone.parent=eb[names[-1]]
    for i in range(13):
        bone=eb.new(f'tail_{i}');bone.head=tail_point(i/12);bone.tail=tail_point((i+1)/12) if i<12 else tail_point(1)+Vector((0,.02,0))
        bone.parent=eb['hips'] if i==0 else eb[f'tail_{i-1}']
    bpy.ops.object.mode_set(mode='OBJECT');return arm,lm


def skin(obj,arm,lm):
    rig.skin(obj,arm)
    parts={}
    for poly in obj.data.polygons:
        name=obj.data.materials[poly.material_index].name
        for index in poly.vertices:parts[index]=name
    groups={g.name:g for g in obj.vertex_groups}
    def replace(v,weights):
        for g in obj.vertex_groups:g.remove([v.index])
        for name,w in weights.items():
            if w>1e-6:groups[name].add([v.index],w,'REPLACE')
    for v in obj.data.vertices:
        part=parts[v.index]
        if part.startswith('ScreenPengHead') or (v.co.y<-.04 and v.co.z>.645):
            # Shared welded vertices receive one continuous field independent
            # of their UV/material boundary. The fork's centre stays on chest;
            # above the saddle each side has its own three-bone neck chain.
            weights={};side_weight=max(0,min(1,(v.co.x+.025)/.050))
            for side,w in [('l',side_weight),('r',1-side_weight)]:
                sign=1 if side=='l' else -1
                normal=Vector((sign*.65*math.sin(math.radians(48)),-.65*math.cos(math.radians(48)),.76)).normalized()
                d=(v.co-Vector((sign*.130,-.245,.845))).dot(normal)
                t=max(0,min(1.2,max((v.co.z-.645)/.200,.90+d/.10)))
                anchors=[(0,'chest'),(.27,f'neck_{side}'),(.60,f'neck_{side}_mid'),(.90,f'neck_{side}_tip'),(1.20,f'head_{side}')]
                for (a,an),(b,bn) in zip(anchors,anchors[1:]):
                    if a<=t<=b:
                        f=(t-a)/(b-a);weights[an]=weights.get(an,0)+w*(1-f);weights[bn]=weights.get(bn,0)+w*f;break
                else:weights[f'head_{side}']=weights.get(f'head_{side}',0)+w
            replace(v,weights)
        elif part.startswith('ScreenPengTail'):
            t=max(0,min(12,(v.co.y-.40)/.60*12));a=min(12,int(t));b=min(12,a+1)
            weights={f'tail_{a}':1-(t-a)}
            weights[f'tail_{b}']=weights.get(f'tail_{b}',0)+(t-a);replace(v,weights)
        elif v.co.z<.14:
            leg=min(lm['legs'],key=lambda n:(Vector((v.co.x,v.co.y,0))-lm['legs'][n]).length_squared)
            w=1-smooth(.08,.14,v.co.z);old={g.group:g.weight for g in v.groups}
            for index,weight in old.items():obj.vertex_groups[index].add([v.index],weight*(1-w),'REPLACE')
            foot=groups[f'{leg}_foot'];foot.add([v.index],old.get(foot.index,0)*(1-w)+w,'REPLACE')
    rig.normalize_weights(obj);print('SKIN Screen Peng: two independent three-bone neck chains, continuous welded shoulder weights, 13 tail bones, rigid soles')


def solve(arm,leg,drop,stride=0,lift=0):
    upper=arm.data.bones[f'{leg}_upper'];lower=arm.data.bones[f'{leg}_lower']
    top=Vector((upper.head_local.y,upper.head_local.z-drop));ankle=Vector((lower.tail_local.y+stride,lower.tail_local.z+lift))
    u=Vector((upper.tail_local.y-upper.head_local.y,upper.tail_local.z-upper.head_local.z))
    l=Vector((lower.tail_local.y-lower.head_local.y,lower.tail_local.z-lower.head_local.z))
    reach=ankle-top;distance=min(reach.length,(u.length+l.length)*.9999)
    along=(u.length_squared-l.length_squared+distance*distance)/(2*distance)
    axis=reach.normalized();normal=Vector((-axis.y,axis.x));side=-1 if leg.startswith('front') else 1
    joint=top+axis*along+normal*math.sqrt(max(0,u.length_squared-along*along))*side
    def angle(a,b):return math.atan2(a.x*b.y-a.y*b.x,a.dot(b))
    a=angle(u,joint-top);b=angle(l,ankle-joint)-a
    return a,b,-a-b


def animate(arm,lm,name,seconds):
    action=new_action(arm,name);n=round(seconds*FPS)
    phases={'back_l':0,'front_l':.25,'back_r':.5,'front_r':.75}
    for f in range(n+1):
        t=f/FPS;phase=f/n;targets={leg:(0,0) for leg in LEGS}
        drop=.022+.002*math.sin(phase*math.tau);display=0
        if name=='walk':
            drop=.032;distance=.14*seconds*.78
            for leg,offset in phases.items():
                p=(phase+offset)%1
                if p<.78:stride=-distance/2+distance*p/.78;lift=0
                else:
                    u=(p-.78)/.22;stride=distance/2-distance*(u*u*(3-2*u));lift=.045*math.sin(u*math.pi)
                targets[leg]=(stride,lift)
        elif name=='alert':display=smooth(.4,1.4,t)*(1-smooth(3.0,4.0,t))
        pose={}
        for leg,(stride,lift) in targets.items():
            for part,angle in zip(('upper','lower','foot'),solve(arm,leg,drop,stride,lift)):
                pb=arm.pose.bones[f'{leg}_{part}'];pose[pb.name]=world_rot(pb,X,angle)
        for side,sign in [('l',1),('r',-1)]:
            for i,suffix in enumerate(['','_mid','_tip']):
                pb=arm.pose.bones[f'neck_{side}{suffix}']
                angle=sign*(.010*math.sin(phase*math.tau+sign*.6-i*.4)+(.025+i*.009)*display)
                pose[pb.name]=world_rot(pb,(0,0,1),angle)
            pb=arm.pose.bones[f'head_{side}'];pose[pb.name]=world_rot(pb,X,.022*math.sin(phase*math.tau+sign)+.035*display)
        for i in range(13):
            pb=arm.pose.bones[f'tail_{i}'];pose[pb.name]=world_rot(pb,(0,0,1),.018*math.sin(phase*math.tau-i*.4))
        key_pose(arm,f,pose);key_loc(arm,f,'root',Vector((0,-drop,0)))
    finish_action(arm,action)
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    for key in fc.keyframe_points:key.interpolation='LINEAR'


def main():
    args=sys.argv[sys.argv.index('--')+1:];obj=rig.load(args[0]);bpy.context.scene.render.fps=FPS
    arm,lm=make_rig(obj);skin(obj,arm,lm)
    for name,seconds in [('idle',4),('walk',1.8),('alert',4.4)]:animate(arm,lm,name,seconds)
    bpy.ops.export_scene.gltf(filepath=args[1],export_format='GLB',export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    print('EXPORTED',args[1],'bones',len(arm.data.bones))


if __name__=='__main__':main()
