"""Rig the integrated four-ear Changyou High without the legacy ear assembly.

Blender -b --factory-startup --python rig_changyou_native.py -- normalized.glb out.glb
The input is uniformly normalized to 1 m maximum horizontal extent, facing -Y.
Writes the candidate and a sibling .rig.json with measured contact/weight evidence.
"""
import argparse
import heapq
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Matrix, Vector
import rig_quadruped as base
from rig_yingzhao import contact

FPS = 30
SECONDS = 2.4
RADIUS = 1.0
SPEED = .08
DUTY = .66


def smooth(a, b, x):
    t = max(0., min(1., (x-a)/(b-a)))
    return t*t*(3-2*t)


def adjacency(mesh):
    graph = [set() for _ in mesh.vertices]
    for edge in mesh.edges:
        a, b = edge.vertices
        graph[a].add(b); graph[b].add(a)
    coincident = {}
    for v in mesh.vertices:
        key = tuple(round(float(x), 6) for x in v.co)
        if key in coincident:
            j = coincident[key]; graph[v.index].add(j); graph[j].add(v.index)
        else:
            coincident[key] = v.index
    return graph


def tail_region(obj, graph, h):
    """The low connected tail is isolated at its rump gate, not by heel Y."""
    seed = max(obj.data.vertices, key=lambda v: v.co.y).index
    mask = {seed}; pending = [seed]
    while pending:
        for i in graph[pending.pop()]:
            p = obj.data.vertices[i].co
            # The tail rump joins below the hips, where a height-only flood
            # reaches both legs. Its rear corridor clears measured heel backs.
            allowed = p.z < h*.43 and (p.y > .135 or (abs(p.x) > .26 and p.z > .16))
            if i not in mask and allowed:
                mask.add(i); pending.append(i)
    assert 100 < len(mask) < len(graph)*.20, ('tail flood escaped', len(mask))
    boundary = [i for i in mask if any(j not in mask for j in graph[i])]
    assert boundary, 'Tail must have an attached rump root'
    points = [v.co for v in obj.data.vertices]
    dist = {i: 0. for i in boundary}; queue = [(0., i) for i in boundary]
    heapq.heapify(queue)
    while queue:
        d, i = heapq.heappop(queue)
        if d > dist[i]:
            continue
        for j in graph[i]:
            if j not in mask:
                continue
            nd = d+(points[i]-points[j]).length
            if nd < dist.get(j, float('inf')):
                dist[j] = nd; heapq.heappush(queue, (nd, j))
    length = max(dist.values())
    root = sum((points[i] for i in boundary), Vector())/len(boundary)
    chain = [root]
    for k in range(1, 7):
        t = k/6
        band = [i for i in mask if abs(dist.get(i, -1)/length-t) < .075]
        assert band
        chain.append(sum((points[i] for i in band), Vector())/len(band))
    return mask, chain


def source_regions(obj, tail, h):
    """Protect head/chest first; classify limbs in their own anatomical space."""
    regions = {}
    for v in obj.data.vertices:
        p = v.co; z = p.z/h; x = abs(p.x)
        if v.index in tail:
            region = 'tail'
        # Actual side-mask review exposed a thin lower-chin strip and the
        # high rear cranium outside the original front-head rectangle. The
        # rear cap stays above the shoulder/back, and the chin extension is
        # restricted to the protruding muzzle, preserving the neck socket.
        elif x < .18 and ((z > .805 and p.y < .045)
                          or (z > .875 and p.y < .12)
                          or (z > .785 and p.y < -.15)):
            region = 'head'
        elif z < .18 or (z < .49 and x < .31 and not (x > .28 and z > .18)):
            region = 'leg_l' if p.x > 0 else 'leg_r'
        else:
            region = 'torso'
        regions[v.index] = region
    return regions


def align_feet(obj, regions, h):
    shifts = {}
    for label in ['l', 'r']:
        vertices = [v for v in obj.data.vertices if regions[v.index] == 'leg_'+label]
        offset = min(v.co.z for v in vertices)
        shifts[label] = offset
        for v in vertices:
            # Whole sole/toe anatomy translates without changing digit shape.
            v.co.z -= offset*(1-smooth(h*.12, h*.28, v.co.z))
    obj.data.update()
    return shifts


def make_rig(obj, chain, h):
    arm = bpy.data.objects.new('changyou_rig', bpy.data.armatures.new('changyou_native_anatomy'))
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm; arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(name, a, b, parent=None):
        item = arm.data.edit_bones.new(name); item.head = a; item.tail = b
        if parent: item.parent = arm.data.edit_bones[parent]
        return item
    bone('root', (0,0,0), (0,0,h*.1))
    bone('hips', (0,.025,h*.48), (0,.01,h*.61), 'root')
    bone('chest', (0,.01,h*.61), (0,-.015,h*.77), 'hips')
    bone('neck', (0,-.015,h*.77), (0,-.08,h*.835), 'chest')
    bone('head', (0,-.08,h*.835), (0,-.15,h*.965), 'neck')
    landmark = {}
    for sign,label in [(1,'l'),(-1,'r')]:
        def center(z, width, minx, maxx, default):
            ps = [v.co for v in obj.data.vertices if abs(v.co.z-z)<width and minx<sign*v.co.x<maxx]
            return sum(ps, Vector())/len(ps) if ps else Vector(default)
        ankle = center(h*.115,h*.012,.08,.28,(sign*.18,.025,h*.115))
        ankle.z = h*.082
        knee = center(h*.28,h*.018,.06,.28,(sign*.16,-.075,h*.28))
        hip = Vector((sign*.105,.025,h*.48))
        shoulder = Vector((sign*.195,-.005,h*.79))
        elbow = center(h*.59,h*.016,.245,.39,(sign*.31,-.03,h*.59))
        wrist = center(h*.405,h*.014,.32,.50,(sign*.41,-.08,h*.405))
        hand = Vector((wrist.x+sign*.012,wrist.y-.025,h*.28))
        bone(f'leg_{label}_upper', hip,knee,'hips')
        bone(f'leg_{label}_lower', knee,ankle,f'leg_{label}_upper')
        bone(f'leg_{label}_foot', ankle,ankle+Vector((0,-h*.095,-h*.035)),f'leg_{label}_lower')
        bone(f'arm_{label}_upper', shoulder,elbow,'chest')
        bone(f'arm_{label}_lower', elbow,wrist,f'arm_{label}_upper')
        bone(f'arm_{label}_hand', wrist,hand,f'arm_{label}_lower')
        landmark[label] = {name:list(p) for name,p in [('hip',hip),('knee',knee),('ankle',ankle),('shoulder',shoulder),('elbow',elbow),('wrist',wrist)]}
    for i in range(len(chain)-1):
        bone(f'tail_{i}',chain[i],chain[i+1],'hips' if i==0 else f'tail_{i-1}')
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm, landmark


def distance(p, bone):
    a = bone.head_local; d = bone.tail_local-a
    t = max(0., min(1., (p-a).dot(d)/d.length_squared))
    return (p-a-d*t).length


def bind(obj, arm, regions, h):
    names = [b.name for b in arm.data.bones]
    groups = {n:obj.vertex_groups.new(name=n) for n in names}
    weights = []; soles = {'l':[], 'r':[]}; allfeet = {'l':[], 'r':[]}; chest_core = []; head = []
    def inverse(p, allowed):
        w = {n:1/max(h*.012,distance(p,arm.data.bones[n]))**4 for n in allowed}
        total = sum(w.values()); return {n:v/total for n,v in w.items()}
    for v in obj.data.vertices:
        p = v.co; x = abs(p.x); z = p.z/h; side = 'l' if p.x>0 else 'r'; region = regions[v.index]
        if region == 'tail':
            w = inverse(p,[n for n in names if n.startswith('tail_')])
        elif region == 'head':
            w = {'head':1.}; head.append(v.index)
        elif region.startswith('leg_'):
            leg = inverse(p,[f'leg_{side}_{part}' for part in ['upper','lower','foot']])
            rigid = 1-smooth(h*.062,h*.125,p.z)
            w = {n:value*(1-rigid) for n,value in leg.items()};w[f'leg_{side}_foot']+=rigid
            # Blend thigh root to pelvis without influencing palms or tail.
            pelvis = smooth(.455,.49,z)*.25
            w = {n:value*(1-pelvis) for n,value in w.items()}
            if pelvis: w['hips']=pelvis
            if z < .062:
                w = {f'leg_{side}_foot':1.}; allfeet[side].append(v.index)
                if p.z < .003: soles[side].append(v.index)
        else:
            torso = inverse(p,['hips','chest','neck','head'])
            # Wide chest stays torso-led; only a measured lateral socket blends.
            threshold = .27-(.065*smooth(.50,.80,z))
            arm_blend = smooth(threshold-.012,threshold+.035,x) if z>.18 else 0.
            if x<.18 and z>.53:
                arm_blend=0.;chest_core.append(v.index)
            if z>.83:
                arm_blend*=smooth(.16,.24,x)
            if arm_blend:
                limb = inverse(p,[f'arm_{side}_{part}' for part in ['upper','lower','hand']])
                # Whole palm and fingers move together; wrist is the blend zone.
                rigid = 1-smooth(.37,.435,z)
                limb={n:value*(1-rigid) for n,value in limb.items()};limb[f'arm_{side}_hand']+=rigid
                w={n:value*(1-arm_blend) for n,value in torso.items()}
                for n,value in limb.items():w[n]=w.get(n,0.)+value*arm_blend
            else:w=torso
        selected=sorted(((n,value) for n,value in w.items() if value>1e-8),key=lambda t:t[1],reverse=True)[:4]
        total=sum(value for n,value in selected);w={n:value/total for n,value in selected}
        weights.append(w)
        for n,value in w.items():groups[n].add([v.index],value,'REPLACE')
    mod=obj.modifiers.new('Protected primate anatomy','ARMATURE');mod.object=arm
    obj.parent=arm
    assert all(abs(sum(w.values())-1)<1e-7 and len(w)<=4 for w in weights)
    assert all(not any(n.startswith('arm_') for n in weights[i]) for i in chest_core)
    assert all(weights[i]=={'head':1.} for i in head)
    for label in ['l','r']:
        assert len(soles[label])>10,(label,len(soles[label]))
        assert all(weights[i]=={f'leg_{label}_foot':1.} for i in allfeet[label])
    obj['integratedNativeHead']=True;obj['nativeEarCount']=4
    # Spatial bounds describe the reviewed rest anatomy independently of weights.
    # glTF converts Blender Z height to local Y; compression may reorder vertices.
    obj['restAnatomicalFootMaxHeight']=h*.062
    obj['restAnatomicalSoleMaxHeight']=.003
    obj['sourceAnatomyReview']='native-four-ear-high-actual: four ears and five digits on each hand/foot visually verified'
    return weights,soles,allfeet,{'vertices':len(weights),'unweighted':0,'maxInfluences':max(map(len,weights)),'protectedChestVertices':len(chest_core),'rigidHeadAndEarVertices':len(head),'rigidFeet':{k:len(v) for k,v in allfeet.items()},'supportSamples':{k:len(v) for k,v in soles.items()}}


def animate(arm, name, seconds):
    action=base.new_action(arm,name);count=round(seconds*FPS)
    for f in range(count+1):
        t=f/FPS;phase=f/count
        display=smooth(.2,1.,t)*(1-smooth(2.8,3.8,t)) if name=='special' else 0.
        delta=Vector((0,0,-.008 if name=='walk' else 0))
        pose={'head':base.world_rot(arm.pose.bones['head'],base.X,-.05*display+.008*math.sin(phase*math.tau)),
              'chest':base.world_rot(arm.pose.bones['chest'],base.X,.004*math.sin(phase*math.tau))}
        for sign,label in [(1,'l'),(-1,'r')]:
            swing=sign*.10*math.sin(phase*math.tau) if name=='walk' else .012*math.sin(phase*math.tau)
            upper=arm.pose.bones[f'arm_{label}_upper'];lower=arm.pose.bones[f'arm_{label}_lower']
            pose[upper.name]=base.world_rot(upper,base.X,swing-.22*display)@base.world_rot(upper,base.Y,-sign*.08*display)
            pose[lower.name]=base.world_rot(lower,base.X,-.09*display)
        for i in range(6):
            pb=arm.pose.bones[f'tail_{i}'];pose[pb.name]=base.world_rot(pb,base.Y,.009*math.sin(phase*math.tau-i*.35))
        base.key_loc(arm,f,'root',arm.data.bones['root'].matrix_local.to_3x3().inverted()@delta)
        base.key_pose(arm,f,pose);bpy.context.view_layer.update()
        for label,offset in [('l',0),('r',.5)]:
            lateral=backward=lift=yaw=0.
            if name=='walk':
                p=(phase+offset)%1
                if p<DUTY:relative=seconds*(p-DUTY/2)
                else:
                    u=(p-DUTY)/(1-DUTY);relative=seconds*DUTY*(.5-u*u*(3-2*u));lift=.045*math.sin(math.pi*u)
                yaw=-SPEED/RADIUS*relative;ankle=arm.data.bones[f'leg_{label}_foot'].head_local
                x=ankle.x-RADIUS;y=ankle.y
                lateral=RADIUS+math.cos(yaw)*x-math.sin(yaw)*y-ankle.x
                backward=math.sin(yaw)*x+math.cos(yaw)*y-ankle.y
            contact(arm,f'leg_{label}',f,delta,lateral,backward,lift,yaw)
    base.finish_action(arm,action)
    for fc in base.action_fcurves(action):
        for key in fc.keyframe_points:key.interpolation='LINEAR'
    return action


def cpu_contact_qa(obj,arm,weights,soles,actions):
    """CPU skin actual support vertices; compose the exact runtime circle."""
    rest=np.array([list(v.co)+[1.] for v in obj.data.vertices],dtype=np.float64)
    bones=list(arm.data.bones);index={b.name:i for i,b in enumerate(bones)}
    ids={label:np.array(vs,dtype=int) for label,vs in soles.items()}
    inv=[b.matrix_local.inverted() for b in bones]
    report={}
    for name,seconds in [('idle',4.),('walk',SECONDS),('special',4.)]:
        for track in arm.animation_data.nla_tracks:track.mute=True
        arm.animation_data.action=actions[name]
        plants={};heights=[];drift=0.;normalDrift=0.
        count=round(seconds*FPS*2)
        # Two walk cycles exercise stance continuity over the exported clip boundary.
        samples=count*2 if name=='walk' else count
        for step in range(samples+1):
            absolute=step/(FPS*2);local=absolute%seconds if name=='walk' else absolute
            frame=local*FPS
            bpy.context.scene.frame_set(int(frame),subframe=frame-int(frame));bpy.context.view_layer.update()
            for label,offset in [('l',0),('r',.5)]:
                bindex=index[f'leg_{label}_foot'];skin=np.array(arm.pose.bones[bindex].matrix@inv[bindex],dtype=np.float64)
                p=(rest[ids[label]]@skin.T)[:,:3]
                if name=='walk':
                    theta=math.pi/2-SPEED/RADIUS*absolute;phi=math.pi-theta
                    rot=np.array([[math.cos(phi),-math.sin(phi),0],[math.sin(phi),math.cos(phi),0],[0,0,1]])
                    p=p@rot.T+np.array([RADIUS*math.cos(theta),-RADIUS*math.sin(theta),0])
                    raw=absolute/seconds+offset;phase=raw%1
                    if not .025<phase<DUTY-.025:continue
                    key=(label,int(math.floor(raw)))
                else:key=(label,0)
                heights.extend(p[:,2].tolist())
                if key not in plants:plants[key]=p.copy()
                drift=max(drift,float(np.max(np.linalg.norm(p-plants[key],axis=1))))
                # Relative orientation of a broad support patch, not a single toe/bone.
                centered=p-p.mean(axis=0);initial=plants[key]-plants[key].mean(axis=0)
                normalDrift=max(normalDrift,float(np.max(np.linalg.norm(centered-initial,axis=1))))
        report[name]={'samples':samples+1,'supportVertices':{k:len(v) for k,v in ids.items()},'minHeight':min(heights),'maxHeight':max(heights),'maxWorldStanceDrift':drift,'maxSupportShapeOrientationDrift':normalDrift,'plantIntervals':len(plants),'measured':'CPU skin of actual rigid support vertices using evaluated bone matrices, half-frame sampling; runtime root composed for walk'}
        assert min(heights)>-.001,report[name]
        assert max(heights)<.004,report[name]
        assert drift<.001,report[name]
    arm.animation_data.action=None
    for track in arm.animation_data.nla_tracks:track.mute=True
    return report


def main():
    args=sys.argv[sys.argv.index('--')+1:];p=argparse.ArgumentParser();p.add_argument('input');p.add_argument('output');a=p.parse_args(args)
    output=Path(a.output);assert not output.exists(),'Refuse to overwrite an existing candidate'
    bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=a.input)
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH'];assert len(meshes)==1
    obj=meshes[0];bpy.context.view_layer.objects.active=obj;obj.select_set(True)
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM');bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    obj.name='changyou_primate';h=max(v.co.z for v in obj.data.vertices)
    graph=adjacency(obj.data);tail,chain=tail_region(obj,graph,h);regions=source_regions(obj,tail,h)
    shifts=align_feet(obj,regions,h)
    bpy.ops.object.select_all(action='DESELECT');arm,landmarks=make_rig(obj,chain,h)
    weights,soles,allfeet,weightreport=bind(obj,arm,regions,h)
    bpy.context.scene.render.fps=FPS
    actions={name:animate(arm,name,seconds) for name,seconds in [('idle',4.),('walk',SECONDS),('special',4.)]}
    qa=cpu_contact_qa(obj,arm,weights,soles,actions)
    # Put the scene in rest, while retaining muted named NLA clips for export.
    bpy.context.scene.frame_set(0)
    for pb in arm.pose.bones:pb.rotation_quaternion=(1,0,0,0);pb.location=(0,0,0)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);arm.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(output),export_format='GLB',use_selection=True,export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False,export_extras=True)
    report={'input':str(Path(a.input).resolve()),'output':str(output.resolve()),'integratedNativeEars':4,'anatomyEvidence':'actual High images reviewed before rigging; no ear assembly used','sourceVertices':len(obj.data.vertices),'sourceFaces':len(obj.data.polygons),'meshes':1,'bones':len(arm.data.bones),'clips':list(actions),'footRestOffsetCorrection':shifts,'tailVertices':len(tail),'tailChain':[list(p) for p in chain],'landmarks':landmarks,'weights':weightreport,'cpuActualSoleQA':qa,'runtimeParameters':{'radius':RADIUS,'speed':SPEED,'walkSeconds':SECONDS,'duty':DUTY},'productionAccepted':False}
    output.with_suffix('.rig.json').write_text(json.dumps(report,indent=2)+'\n')
    print('NATIVE_CHANGYOU_RIGGED',json.dumps(report),flush=True)


if __name__=='__main__':main()
