"""Longzhi-specific continuous skin, nine necks/nine tails and planted four-paw IK.
The prepared sidecar supplies independent surface-region labels; no organ-count
claim is inferred from bone names. Run only after the actual anatomy review.
"""
import argparse,json,math,sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import rig_quadruped as shared
from rig_yingzhao import contact
FPS=30
DURATIONS={'idle':4.8,'walk':2.4,'special':4.8}
STRIDE=.07
DUTY=.68
RADIUS=3.
SPEED=STRIDE/(DUTY*DURATIONS['walk'])


def clamp(t):return max(0.,min(1.,t))
def smooth(t):t=clamp(t);return t*t*(3-2*t)
def distseg(p,a,b):
    delta=b-a;t=clamp((p-a).dot(delta)/delta.length_squared);return (p-a-delta*t).length


def build(obj,regions):
    low=[v.co for v in obj.data.vertices if v.co.z<.035];mid=(min(v.y for v in low)+max(v.y for v in low))*.5;feet={}
    for fb in ('front','back'):
        for side in ('l','r'):
            points=[p for p in low if (p.y<mid)==(fb=='front') and (p.x>0)==(side=='l')];assert points
            feet[fb+'_'+side]=sum(points,Vector())/len(points)
    data=bpy.data.armatures.new('longzhi_rig');arm=bpy.data.objects.new('longzhi_rig',data);bpy.context.scene.collection.objects.link(arm);bpy.context.view_layer.objects.active=arm;bpy.ops.object.mode_set(mode='EDIT');bones=data.edit_bones
    def bone(name,a,b,parent=None):
        item=bones.new(name);item.head=a;item.tail=b
        if parent:item.parent=bones[parent]
        return item
    bone('root',(0,0,0),(0,0,.10));bone('hips',(0,.30,.45),(0,.10,.47),'root');bone('spine1',(0,.10,.47),(0,-.10,.47),'hips');bone('spine2',(0,-.10,.47),(0,-.28,.47),'spine1');bone('chest',(0,-.28,.47),(0,-.33,.57),'spine2')
    for name,foot in feet.items():
        front=name.startswith('front');top=Vector((foot.x*.80,foot.y+(.06 if front else .025),.49 if front else .51));knee=Vector((foot.x,foot.y+(.095 if front else .115),.27 if front else .29));ankle=Vector((foot.x,foot.y+.035,.075));toe=Vector((foot.x,foot.y-.045,.025));parent='chest' if front else 'hips';bone(name+'_upper',top,knee,parent);bone(name+'_lower',knee,ankle,name+'_upper');bone(name+'_foot',ankle,toe,name+'_lower')
    for index,r in enumerate(regions):
        root=Vector(r['root']);tip=Vector(r['collar'] if r['role']=='head' else r['tip']);prefix=r['name'];parent='chest' if r['role']=='head' else 'hips';count=2 if r['role']=='head' else 5
        for j in range(count):bone(prefix+f'_chain_{j}',root.lerp(tip,j/count),root.lerp(tip,(j+1)/count),parent if j==0 else prefix+f'_chain_{j-1}')
        if r['role']=='head':bone(prefix+'_skull',tip,Vector(r['tip']),prefix+'_chain_1')
    bpy.ops.object.mode_set(mode='OBJECT');return arm,feet


def body_weights(p,bones):
    fb='front' if p.y<0 else 'back';side='l' if p.x>0 else 'r';prefix=fb+'_'+side
    distance=min(distseg(p,bones[prefix+'_'+part].head_local,bones[prefix+'_'+part].tail_local) for part in ('upper','lower','foot'))
    proximity=smooth(abs(p.x)/.08)*(1-smooth((distance-.07)/.10))
    legblend=(1-smooth((p.z-.28)/.20))*(1-smooth((p.z-.035)/.115)*(1-proximity))
    foot=1-smooth((p.z-.065)/.105);upper=smooth((p.z-.17)/.20)*(1-foot)
    return {'hips':1-legblend,prefix+'_foot':foot*legblend,prefix+'_lower':(1-foot-upper)*legblend,prefix+'_upper':upper*legblend},distance


def bind(obj,arm,reference):
    tree=KDTree(len(reference['restPoints']))
    for i,p in enumerate(reference['restPoints']):tree.insert(p,i)
    tree.balance();obj.vertex_groups.clear();groups={bone.name:obj.vertex_groups.new(name=bone.name) for bone in arm.data.bones};bones=arm.data.bones;regions=reference['regions'];maximum=0
    names=list(groups);boneindex={name:i for i,name in enumerate(names)};dense=np.zeros((len(reference['restPoints']),len(names)),np.float32);fixed=np.zeros(len(dense),bool);spatial=np.zeros(len(dense),np.float32);mapping=[]
    for vertex in obj.data.vertices:
        p=vertex.co;_,i,error=tree.find(p);mapping.append(i);maximum=max(maximum,error);assert error<2e-5
        label=reference['regionLabels'][i]
        lower,distance=body_weights(p,bones)
        spatial[i]=(1-smooth((p.z-.40)/.08))*(1-smooth((distance-.12)/.10))
        if label:
            r=regions[label-1];prefix=r['name'];root=Vector(r['root']);tip=Vector(r['collar'] if r['role']=='head' else r['tip']);axis=tip-root;h=(p-root).dot(axis.normalized());t=clamp(h/axis.length);parent='chest' if r['role']=='head' else 'hips';blend=smooth(h/(.075 if r['role']=='head' else .10));weights={parent:1-blend}
            if r['role']=='head':
                if t>=.84:part={prefix+'_skull':1.}
                elif t>.45:
                    q=smooth((t-.45)/.39);part={prefix+'_chain_1':1-q,prefix+'_skull':q}
                else:
                    q=smooth(t/.45);part={prefix+'_chain_0':1-q,prefix+'_chain_1':q}
            else:
                q=clamp(t)*4;j=min(3,int(q));f=q-j;part={prefix+f'_chain_{j}':1-f,prefix+f'_chain_{j+1}':f}
            for name,w in part.items():weights[name]=weights.get(name,0)+w*blend
        else:
            weights=lower
        if label and spatial[i]>0:
            weights={name:w*(1-spatial[i]) for name,w in weights.items()}
            for name,w in lower.items():weights[name]=weights.get(name,0)+w*spatial[i]
        weights=sorted(((name,w) for name,w in weights.items() if w>1e-5),key=lambda q:q[1],reverse=True)[:4];total=sum(w for _,w in weights)
        for name,w in weights:dense[i,boneindex[name]]=w/total
        fixed[i]=p.z<.065 or (p.z>=.48 and label and reference['regions'][label-1]['role']=='head' and t>=.84)
    # Smooth on the independent welded surface so UV seam copies keep identical
    # weights. Preserve complete skulls and distal paws exactly.
    pairs=np.unique(np.sort(np.array([[mapping[a],mapping[b]] for edge in obj.data.edges for a,b in [edge.vertices]],dtype=np.int32),axis=1),axis=0);a,b=pairs.T;degree=np.bincount(np.concatenate([a,b]),minlength=len(dense));degree=np.maximum(1,degree)[:,None];original=dense.copy()
    for iteration in range(18):
        sums=np.zeros_like(dense);np.add.at(sums,a,dense[b]);np.add.at(sums,b,dense[a]);dense=dense*.30+sums/degree*.70;dense[fixed]=original[fixed]
    # The native lower limbs contain highly irregular remesh triangulation.
    # Use their continuous spatial field directly; graph averaging on that
    # topology creates steep gradients across adjacent narrow triangles.
    dense=dense*(1-spatial[:,None])+original*spatial[:,None]
    # These torso bones have identical static pose transforms in all clips.
    # Coalesce their influence before the four-joint limit, avoiding rank swaps
    # between redundant torso influences at a moving leg's skin boundary.
    for name in ('root','spine1','spine2','chest'):
        dense[:,boneindex['hips']]+=dense[:,boneindex[name]];dense[:,boneindex[name]]=0
    obj.vertex_groups.clear();groups=[obj.vertex_groups.new(name=name) for name in names]
    for vertex,i in zip(obj.data.vertices,mapping):
        weights=dense[i];indices=np.argsort(weights)[-4:];total=weights[indices].sum()
        for j in indices:
            if weights[j]>1e-6:groups[j].add([vertex.index],float(weights[j]/total),'REPLACE')
    modifier=obj.modifiers.new('longzhi_continuous_skin','ARMATURE');modifier.object=arm;obj.parent=arm
    return maximum


def animate(arm,regions,feet):
    phase={'back_l':0,'front_l':.25,'back_r':.5,'front_r':.75}
    for clip,seconds in DURATIONS.items():
        action=shared.new_action(arm,clip);n=round(seconds*FPS)
        for frame in range(n+1):
            t=frame/FPS;cycle=frame/n;pose={}
            for i,r in enumerate(regions):
                prefix=r['name'];special=math.sin(math.pi*cycle)**2 if clip=='special' else 0.;frequency=math.tau*cycle;phaseoffset=i*.72
                if r['role']=='head':
                    yaw=(.012 if clip=='walk' else .018)*math.sin(frequency+phaseoffset);pitch=.012*math.cos(frequency*2+phaseoffset)-.055*special
                    for j in range(2):
                        pb=arm.pose.bones[prefix+f'_chain_{j}'];pose[pb.name]=shared.world_rot(pb,shared.Z,yaw*.5)@shared.world_rot(pb,shared.X,pitch*.5)
                    pb=arm.pose.bones[prefix+'_skull'];pose[pb.name]=shared.world_rot(pb,shared.Z,-yaw*.3)
                else:
                    for j in range(5):
                        pb=arm.pose.bones[prefix+f'_chain_{j}'];amp=(.007+.012*special)*(j+1)/5;pose[pb.name]=shared.world_rot(pb,shared.X,amp*math.sin(frequency+phaseoffset-j*.55))@shared.world_rot(pb,shared.Z,amp*.7*math.cos(frequency+phaseoffset-j*.45))
            shared.key_pose(arm,frame,pose);bpy.context.view_layer.update()
            for prefix in feet:
                lateral=backward=lift=yaw=0.
                if clip=='walk':
                    p=(cycle+phase[prefix])%1
                    if p<DUTY:relative=seconds*(p-DUTY/2)
                    else:
                        q=(p-DUTY)/(1-DUTY);s=q*q*q*(10-15*q+6*q*q);m=(1-DUTY)/DUTY
                        relative=seconds*DUTY*(.5+m*q-(1+m)*s);lift=.028*math.sin(math.pi*q)**4
                    yaw=-SPEED/RADIUS*relative;ankle=arm.data.bones[prefix+'_foot'].head_local;x=ankle.x-RADIUS;y=ankle.y
                    lateral=RADIUS+math.cos(yaw)*x-math.sin(yaw)*y-ankle.x
                    backward=math.sin(yaw)*x+math.cos(yaw)*y-ankle.y
                contact(arm,prefix,frame,Vector(),lateral,backward,lift,yaw)
        shared.finish_action(arm,action)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('input',type=Path);ap.add_argument('output',type=Path);ap.add_argument('--preview');args=ap.parse_args(sys.argv[sys.argv.index('--')+1:]);reference=json.loads(args.input.with_suffix('.regions.json').read_text());bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=str(args.input));obj=next(o for o in bpy.context.scene.objects if o.type=='MESH');bpy.context.view_layer.objects.active=obj;obj.select_set(True);bpy.ops.object.transform_apply(location=True,rotation=True,scale=True);arm,feet=build(obj,reference['regions']);error=bind(obj,arm,reference);bpy.context.scene.render.fps=FPS;animate(arm,reference['regions'],feet);bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);arm.select_set(True);bpy.context.view_layer.objects.active=arm
    bpy.ops.export_scene.gltf(filepath=str(args.output),export_format='GLB',use_selection=True,export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    audit={'beast':'longzhi','bones':len(arm.data.bones),'clips':DURATIONS,'restRegionMatchMaximumError':error,'stride':STRIDE,'duty':DUTY,'walkSpeedNormalizedMps':SPEED,'walkRadiusM':RADIUS,'stance':'Inverse circular XYZ position and full sole yaw, matching runtime root movement','regions':reference['regions'],'feet':{name:list(p) for name,p in feet.items()},'accepted':False};args.output.with_suffix('.rig.json').write_text(json.dumps(audit,indent=2)+'\n');print('LONGZHI_RIG',json.dumps(audit),flush=True)

if __name__=='__main__':main()
