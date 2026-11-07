"""Ershu's own rig: continuous cervid/rabbit tissue, pinnae and ten-bone tail.

Input is prepare_ershu.py's multi-mesh sculpt. Walk uses analytic two-bone IK:
stance hooves move uniformly backwards at ground height. Its 0.19 m stride,
0.68 duty factor and 1.5 s period match Ershu.tsx's 0.1862745 m/s path.
Special is 5.4 s; tail strokes precede lift and all legs unfold before landing.
"""
import math
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_quadruped as base
from prepare_ershu import tail_center

FPS = 30
DURATION = 5.4
TAIL_BONES = 10


def smooth(a, b, x):
    t = max(0, min(1, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def extra_bones(arm):
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.data.edit_bones
    for side in (-1, 1):
        bone = eb.new(f'ear_{"l" if side == 1 else "r"}')
        bone.head = (side * 0.048, -0.285, 0.794)
        bone.tail = (side * 0.14, -0.196, 1.08)
        bone.parent = eb['head']
    for i in range(TAIL_BONES):
        bone = eb.new(f'ershu_tail_{i:02}')
        bone.head = tail_center(i / TAIL_BONES)
        bone.tail = tail_center((i + 1) / TAIL_BONES)
        bone.parent = eb['hips'] if i == 0 else eb[f'ershu_tail_{i-1:02}']
        bone.use_connect = i > 0
    bpy.ops.object.mode_set(mode='OBJECT')


def rigid(obj, arm, name):
    obj.vertex_groups.clear()
    group = obj.vertex_groups.new(name=name)
    group.add(list(range(len(obj.data.vertices))), 1, 'REPLACE')
    modifier = obj.modifiers.new('ershu rig', 'ARMATURE')
    modifier.object = arm
    obj.parent = arm


def skin_tail(obj, arm):
    obj.vertex_groups.clear()
    groups = [obj.vertex_groups.new(name=f'ershu_tail_{i:02}') for i in range(TAIL_BONES)]
    for vertex in obj.data.vertices:
        t = max(0, min(1, (vertex.co.y - 0.387) / 0.79))
        k = max(0, min(TAIL_BONES - 1, t * TAIL_BONES - 0.5))
        lo = int(k)
        fraction = k - lo
        groups[lo].add([vertex.index], 1 - fraction, 'REPLACE')
        if fraction and lo + 1 < TAIL_BONES:
            groups[lo + 1].add([vertex.index], fraction, 'REPLACE')
    modifier = obj.modifiers.new('ershu flying tail', 'ARMATURE')
    modifier.object = arm
    obj.parent = arm


def tail_pose(arm, t, strength):
    pose = {}
    for i in range(TAIL_BONES):
        bone = arm.pose.bones[f'ershu_tail_{i:02}']
        angle = strength * (0.13 * math.sin(t * 7.2 - i * 0.43))
        pose[bone.name] = base.world_rot(bone, base.X, angle) @ base.world_rot(bone, base.Z, strength * 0.06 * math.sin(t * 3.6 - i * 0.32))
    return pose


def ears(arm, t, amplitude):
    return {f'ear_{side}': base.world_rot(arm.pose.bones[f'ear_{side}'], base.X, amplitude * math.sin(t * 2.0 + offset)) for side, offset in [('l', 0), ('r', 0.7)]}


def idle(arm):
    action = base.new_action(arm, 'idle')
    for frame in range(121):
        t = frame / FPS
        pose = tail_pose(arm, t * math.tau / 4 / 3.6, 0.10)
        pose.update(ears(arm, math.sin(t * math.tau / 4), 0.045))
        pose['head'] = base.world_rot(arm.pose.bones['head'], base.Z, 0.032 * math.sin(t * math.tau / 4))
        pose['neck'] = base.world_rot(arm.pose.bones['neck'], base.X, 0.008 * math.sin(t * math.pi))
        # Exact cyclic endpoints, including the tail, avoid an idle-loop hitch.
        if frame == 120:
            pose = tail_pose(arm, 0, 0.10)
            pose.update(ears(arm, 0, 0.045))
            pose['head'] = Quaternion()
            pose['neck'] = Quaternion()
        base.key_pose(arm, frame, pose)
    base.finish_action(arm, action)


def leg_ik(arm, leg, travel, lift):
    upper = arm.pose.bones[f'{leg}_upper']
    lower = arm.pose.bones[f'{leg}_lower']
    foot = arm.pose.bones[f'{leg}_foot']
    a = upper.bone.head_local
    b = lower.bone.head_local
    c = foot.bone.head_local
    l1 = math.hypot(b.y - a.y, b.z - a.z)
    l2 = math.hypot(c.y - b.y, c.z - b.z)
    dy, dz = c.y + travel - a.y, c.z + lift - a.z
    distance = min(math.hypot(dy, dz), (l1 + l2) * 0.99999)
    direction = math.atan2(dy, -dz)
    alpha = math.acos(max(-1, min(1, (l1*l1 + distance*distance - l2*l2) / (2*l1*distance))))
    beta = math.acos(max(-1, min(1, (l2*l2 + distance*distance - l1*l1) / (2*l2*distance))))
    bend = 1 if leg.startswith('front') else -1
    desired_upper = direction + bend * alpha
    desired_lower = direction - bend * beta
    rest_upper = math.atan2(b.y - a.y, a.z - b.z)
    rest_lower = math.atan2(c.y - b.y, b.z - c.z)
    u = desired_upper - rest_upper
    lower_world = desired_lower - rest_lower
    return {
        upper.name: base.world_rot(upper, base.X, u),
        lower.name: base.world_rot(lower, base.X, lower_world - u),
        foot.name: base.world_rot(foot, base.X, -lower_world),
    }


def walk(arm):
    action = base.new_action(arm, 'walk')
    phases = {'back_l': 0, 'front_l': 0.25, 'back_r': 0.5, 'front_r': 0.75}
    frames = 45
    for frame in range(frames + 1):
        t = frame / FPS
        pose = tail_pose(arm, t * math.tau / 1.5 / 3.6, 0.18)
        pose.update(ears(arm, t * math.pi / 1.5, 0.025))
        for leg, offset in phases.items():
            phase = (frame / frames + offset) % 1
            swing, lift = base.leg_cycle(phase, duty=0.68)
            pose.update(leg_ik(arm, leg, -0.095 * swing, 0.018 + 0.047 * lift))
        pose['head'] = base.world_rot(arm.pose.bones['head'], base.X, 0.012 * math.sin(t * math.tau / 1.5))
        if frame == frames:
            # Auxiliary appendages use a cyclic frequency as well.
            pose.update(tail_pose(arm, 0, 0.18))
            pose.update(ears(arm, 0, 0.025))
        base.key_pose(arm, frame, pose)
        base.key_loc(arm, frame, 'root', Vector((0, -0.018, 0)))
    base.finish_action(arm, action)


def special(arm):
    action = base.new_action(arm, 'special')
    for frame in range(round(DURATION * FPS) + 1):
        t = frame / FPS
        stroke = smooth(0.0, 0.45, t) * (1 - smooth(4.0, 5.15, t))
        folded = smooth(0.75, 1.5, t) * (1 - smooth(3.3, 4.25, t))
        pose = tail_pose(arm, t, stroke)
        pose.update(ears(arm, t, 0.10 * stroke))
        for leg in ('front_l', 'front_r', 'back_l', 'back_r'):
            front = leg.startswith('front')
            u, l = (0.62, -1.35) if front else (-0.62, 1.28)
            for part, angle in [('upper', u), ('lower', l), ('foot', -(u+l)*0.8)]:
                bone = arm.pose.bones[f'{leg}_{part}']
                pose[bone.name] = base.world_rot(bone, base.X, angle * folded)
        pose['head'] = base.world_rot(arm.pose.bones['head'], base.X, -0.04 * stroke)
        base.key_pose(arm, frame, pose)
    base.finish_action(arm, action)


def main():
    source, output = sys.argv[sys.argv.index('--') + 1:]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    body = next(o for o in meshes if o.name == 'ershu_cervid_rabbit_sculpt')
    for obj in meshes:
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    lm = base.landmarks(body)
    lm.update(height=0.85, head=Vector((0, -0.32, 0.77)), snout=Vector((0, -0.466, 0.739)), rear=Vector((0, 0.387, 0.610)))
    arm = base.build_armature(lm)
    arm.name = 'ershu_rig'
    extra_bones(arm)
    base.skin(body, arm)
    # No influence from ears/tail on torso; heat weights can leak across close roots.
    for group in list(body.vertex_groups):
        if group.name.startswith(('ershu_tail_', 'ear_')):
            body.vertex_groups.remove(group)
    missing = 0
    torso_bones = [b for b in arm.data.bones if b.use_deform and not b.name.startswith(('ershu_tail_', 'ear_'))]
    for vertex in body.data.vertices:
        if not any(g.weight > 1e-4 for g in vertex.groups):
            nearest = min(torso_bones, key=lambda b: (b.head_local - vertex.co).length_squared)
            body.vertex_groups[nearest.name].add([vertex.index], 1, 'REPLACE')
            missing += 1
    # Restrict the upper torso and beard to axial bones. Folding legs must not
    # pull the neck cap into shoulder spikes through heat-weight proximity.
    axial = [arm.data.bones[n] for n in ('hips', 'spine1', 'spine2', 'chest', 'neck', 'head')]
    for vertex in body.data.vertices:
        z = vertex.co.z
        if z <= 0.38:
            continue
        blend = smooth(0.38, 0.49, z)
        weights = {body.vertex_groups[g.group].name: g.weight * (1 - blend) for g in vertex.groups}
        def segment_distance(bone):
            delta=bone.tail_local-bone.head_local
            u=max(0,min(1,(vertex.co-bone.head_local).dot(delta)/delta.length_squared))
            return max(.005,(vertex.co-bone.head_local-u*delta).length)
        candidates=sorted(axial,key=segment_distance)[:3]
        scores=[segment_distance(bone)**-4 for bone in candidates]
        for bone,score in zip(candidates,scores):
            weights[bone.name]=weights.get(bone.name,0)+blend*score/sum(scores)
        for group in body.vertex_groups:
            group.remove([vertex.index])
        for name, weight in weights.items():
            if weight > 1e-6:
                body.vertex_groups[name].add([vertex.index], weight, 'REPLACE')
    # The entire hoof, including the flattened sole, follows its foot rigidly.
    feet=[arm.data.bones[f'{leg}_foot'] for leg in ('front_l','front_r','back_l','back_r')]
    for vertex in body.data.vertices:
        if vertex.co.z>.07:continue
        foot=min(feet,key=lambda bone:(bone.head_local-vertex.co).length_squared)
        for group in body.vertex_groups:group.remove([vertex.index])
        body.vertex_groups[foot.name].add([vertex.index],1,'REPLACE')
    base.normalize_weights(body)
    print('ERSHU_SKIN filled', missing, 'unweighted', base.unweighted_count(body))
    for obj in meshes:
        if obj is body:
            continue
        if obj.name == 'ershu_tail':
            skin_tail(obj, arm)
        elif obj.name.startswith('ershu_ear_'):
            side = 'l' if obj.name == 'ershu_ear_1' else 'r'
            rigid(obj, arm, f'ear_{side}')
        else:
            rigid(obj, arm, 'head')
    bpy.context.scene.render.fps = FPS
    idle(arm)
    walk(arm)
    special(arm)
    bpy.context.scene.frame_set(0)
    bpy.ops.export_scene.gltf(filepath=output, export_format='GLB', export_animations=True, export_animation_mode='NLA_TRACKS', export_skins=True, export_def_bones=False)
    print('ERSHU_EXPORTED bones', len(arm.data.bones), 'meshes', len(meshes), 'actions', [(a.name, tuple(a.frame_range)) for a in bpy.data.actions])


if __name__ == '__main__':
    main()
