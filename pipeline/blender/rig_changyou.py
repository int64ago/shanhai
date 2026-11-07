"""Dedicated long-arm primate rig from new HIGH body + four HIGH ear instances.
Usage: Blender --background --python rig_changyou.py -- assembled.glb rigged.glb
"""
import math
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
from mathutils import Vector
import rig_quadruped as base
from rig_yingzhao import contact

FPS = 30
SECONDS = 2.4
RADIUS = 1.0
SPEED = .08
DUTY = .66


def smooth(a, b, x):
    t = max(0, min(1, (x-a)/(b-a)))
    return t*t*(3-2*t)


def make_rig():
    data = bpy.data.armatures.new('changyou_anatomy')
    arm = bpy.data.objects.new('changyou_rig', data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(name, head, tail, parent=None):
        b = data.edit_bones.new(name); b.head = head; b.tail = tail
        if parent: b.parent = data.edit_bones[parent]
        return b
    bone('root', (0,0,0), (0,0,.12))
    bone('hips', (0,.035,.61), (0,.01,.76), 'root')
    bone('chest', (0,.01,.76), (0,-.035,.96), 'hips')
    bone('neck', (0,-.035,.96), (0,-.12,1.055), 'chest')
    bone('head', (0,-.12,1.055), (0,-.15,1.235), 'neck')
    for side, label in [(1,'l'),(-1,'r')]:
        bone(f'leg_{label}_upper', (side*.105,.005,.62), (side*.17,-.12,.32), 'hips')
        bone(f'leg_{label}_lower', (side*.17,-.12,.32), (side*.15,-.055,.07), f'leg_{label}_upper')
        bone(f'leg_{label}_foot', (side*.15,-.055,.07), (side*.15,-.18,.035), f'leg_{label}_lower')
        bone(f'arm_{label}_upper', (side*.18,-.06,.95), (side*.28,-.09,.65), 'chest')
        bone(f'arm_{label}_lower', (side*.28,-.09,.65), (side*.35,-.12,.3), f'arm_{label}_upper')
        bone(f'arm_{label}_hand', (side*.35,-.12,.3), (side*.36,-.14,.13), f'arm_{label}_lower')
        for index, z in [(0,1.20),(1,1.075)]:
            bone(f'ear_{label}_{index}', (side*.078,-.137,z), (side*.15,-.137,z+.02), 'head')
    points = [(0,.09,.51),(0,.16,.40),(-.05,.22,.27),(-.11,.26,.10),(.10,.24,.045),(.29,.15,.07)]
    for i in range(5): bone(f'tail_{i}',points[i],points[i+1], 'hips' if i == 0 else f'tail_{i-1}')
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm


def distance(p, bone):
    a = bone.head_local; d = bone.tail_local-a
    t = max(0,min(1,(p-a).dot(d)/d.length_squared))
    return (p-a-d*t).length


def bind(obj, arm):
    groups = {b.name: obj.vertex_groups.new(name=b.name) for b in arm.data.bones}
    if obj.name.startswith('changyou_ear_'):
        name = obj.name.replace('changyou_', '')
        groups[name].add(list(range(len(obj.data.vertices))), 1, 'REPLACE')
    else:
        # Follow the tail's connected surface below its rump junction. A pure
        # Y threshold mistakes a curled tip for a leg when it turns forward.
        adjacency = [[] for _ in obj.data.vertices]
        for edge in obj.data.edges:
            a,b = edge.vertices; adjacency[a].append(b); adjacency[b].append(a)
        # glTF duplicates vertices along UV seams. Connect coincident positions
        # for this anatomical flood without modifying UVs or runtime geometry.
        coincident = {}
        for v in obj.data.vertices:
            key=tuple(round(x,6) for x in v.co)
            if key in coincident:
                other=coincident[key];adjacency[v.index].append(other);adjacency[other].append(v.index)
            else:coincident[key]=v.index
        seed = max(obj.data.vertices,key=lambda v:v.co.y).index
        tail_vertices = {seed}; pending = [seed]
        while pending:
            for i in adjacency[pending.pop()]:
                p = obj.data.vertices[i].co
                if i not in tail_vertices and p.z < .50:
                    tail_vertices.add(i); pending.append(i)
        print('TAIL_CONNECTED_VERTICES',len(tail_vertices))
        hand_vertices = set()
        for side in [-1,1]:
            seed = max((v for v in obj.data.vertices if v.co.z<.36),key=lambda v:side*v.co.x).index
            pending=[seed];hand_vertices.add(seed)
            while pending:
                for i in adjacency[pending.pop()]:
                    p=obj.data.vertices[i].co
                    if i not in hand_vertices and p.z<.36 and side*p.x>.24:
                        hand_vertices.add(i);pending.append(i)
        print('HANDS_CONNECTED_VERTICES',len(hand_vertices))
        for v in obj.data.vertices:
            p = v.co; side = 'l' if p.x > 0 else 'r'
            if v.index in tail_vertices or (p.y > .12 and p.z < .64):
                names = [f'tail_{i}' for i in range(5)]
            elif p.z > 1.025 and abs(p.x) < .14:
                names = ['head']
            elif v.index in hand_vertices or (p.z > .18 and abs(p.x) > .245 - .08*smooth(.3,.9,p.z)):
                names = [f'arm_{side}_{part}' for part in ['upper','lower','hand']]
            elif p.z < .65:
                names = [f'leg_{side}_{part}' for part in ['upper','lower','foot']]
            else:
                names = ['hips','chest','neck','head']
            weights = {n: 1/max(.008,distance(p,arm.data.bones[n]))**6 for n in names}
            if names[0].startswith('leg_') and p.z < .085:
                # The entire sole is rigid to its foot; ankle blends above it.
                w = 1-smooth(.045,.085,p.z)
                total = sum(weights.values())
                weights = {n:value/total*(1-w) for n,value in weights.items()}
                foot = f'leg_{side}_foot'; weights[foot] += w
            total = sum(weights.values())
            for n,w in weights.items():
                if w/total > 1e-6: groups[n].add([v.index],w/total,'REPLACE')
        bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True)
        bpy.context.view_layer.objects.active=obj
        bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
        bpy.ops.object.vertex_group_smooth(group_select_mode='ALL',factor=.55,repeat=8)
        bpy.ops.object.mode_set(mode='OBJECT')
        # Smoothing is for soft junctions; preserve every actual sole as rigid.
        for v in obj.data.vertices:
            p=v.co
            if v.index not in tail_vertices and v.index not in hand_vertices and p.z < .045 and abs(p.x)<.30 and p.y<.09:
                for g in obj.vertex_groups:g.remove([v.index])
                groups[f'leg_{"l" if p.x>0 else "r"}_foot'].add([v.index],1,'REPLACE')
    mod = obj.modifiers.new('Primate anatomy', 'ARMATURE'); mod.object = arm
    obj.parent = arm
    base.normalize_weights(obj)
    assert base.unweighted_count(obj) == 0


def animate(arm, name, seconds):
    action = base.new_action(arm, name); count = round(seconds*FPS)
    for f in range(count+1):
        t=f/FPS; phase=f/count
        display = smooth(.15,1,t)*(1-smooth(2.6,3.8,t)) if name == 'special' else 0
        delta = Vector((0,0,-.008 if name == 'walk' else 0))
        pose = {'head':base.world_rot(arm.pose.bones['head'],base.X,-.07*display+.012*math.sin(phase*math.tau)),
                'chest':base.world_rot(arm.pose.bones['chest'],base.X,.006*math.sin(phase*math.tau))}
        for side,label in [(1,'l'),(-1,'r')]:
            swing = side*.12*math.sin(phase*math.tau) if name == 'walk' else .02*math.sin(phase*math.tau)
            upper = arm.pose.bones[f'arm_{label}_upper']
            lower = arm.pose.bones[f'arm_{label}_lower']
            pose[upper.name] = base.world_rot(upper,base.X,swing-.12*display) @ base.world_rot(upper,base.Y,-side*.08*display)
            pose[lower.name] = base.world_rot(lower,base.X,-.10*display)
            for i in range(2):
                b=arm.pose.bones[f'ear_{label}_{i}']
                pose[b.name]=base.world_rot(b,base.Z,side*(.012+.02*display)*math.sin(t*3+i*.8))
        for i in range(5):
            b=arm.pose.bones[f'tail_{i}']
            pose[b.name]=base.world_rot(b,base.Y,.018*math.sin(phase*math.tau-i*.4))
        base.key_loc(arm,f,'root',arm.data.bones['root'].matrix_local.to_3x3().inverted()@delta)
        base.key_pose(arm,f,pose);bpy.context.view_layer.update()
        for label,offset in [('l',0),('r',.5)]:
            lateral=backward=lift=yaw=0
            if name == 'walk':
                p=(phase+offset)%1
                if p < DUTY: relative=seconds*(p-DUTY/2)
                else:
                    u=(p-DUTY)/(1-DUTY)
                    relative=seconds*DUTY*(.5-u*u*(3-2*u));lift=.045*math.sin(math.pi*u)
                yaw=-SPEED/RADIUS*relative
                ankle=arm.data.bones[f'leg_{label}_foot'].head_local
                x=ankle.x-RADIUS;y=ankle.y
                lateral=RADIUS+math.cos(yaw)*x-math.sin(yaw)*y-ankle.x
                backward=math.sin(yaw)*x+math.cos(yaw)*y-ankle.y
            contact(arm,f'leg_{label}',f,delta,lateral,backward,lift,yaw)
    base.finish_action(arm,action)
    for fc in base.action_fcurves(action):
        for key in fc.keyframe_points: key.interpolation='LINEAR'


def main():
    source,output=sys.argv[sys.argv.index('--')+1:]
    bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.import_scene.gltf(filepath=source)
    meshes=[o for o in bpy.context.scene.objects if o.type=='MESH']
    for obj in meshes:
        bpy.ops.object.select_all(action='DESELECT');obj.select_set(True)
        bpy.context.view_layer.objects.active=obj
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
        bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    bpy.ops.object.select_all(action='DESELECT')
    arm=make_rig()
    for obj in meshes:bind(obj,arm)
    bpy.context.scene.render.fps=FPS
    for name,seconds in [('idle',4),('walk',SECONDS),('special',4)]:animate(arm,name,seconds)
    bpy.context.scene.frame_set(0)
    bpy.ops.export_scene.gltf(filepath=output,export_format='GLB',export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    print('CHANGYOU_RIG',len(arm.data.bones),'bones',len(meshes),'meshes')


if __name__=='__main__':main()
