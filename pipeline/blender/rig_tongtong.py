"""Tongtong's grounded pig gait and restrained pearl-bearing display.

Offline only. Uses the quadruped weighting fallbacks, then gives each hoof an
analytic two-bone solve. The 1.6-second gait travels at runtime's 0.3 m/s;
stance hooves move uniformly backwards and remain level. No external pearl.
Usage: blender -b --python pipeline/blender/rig_tongtong.py -- in.glb out.glb
"""
from collections import defaultdict
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_quadruped as rig
from rig_quadruped import FPS, X, Z, finish_action, key_loc, key_pose, new_action, world_rot

LEGS = ('front_l', 'front_r', 'back_l', 'back_r')
WALK_SECONDS = 1.6
DUTY = 0.66
SPEED = 0.3


def plane(v):
    return Vector((v.y, v.z))


def angle(a, b):
    return math.atan2(a.x * b.y - a.y * b.x, a.dot(b))


def solve_leg(arm, leg, offset, lift, drop):
    upper, lower = (arm.data.bones[f'{leg}_{part}'] for part in ('upper', 'lower'))
    top, knee, ankle = plane(upper.head_local), plane(upper.tail_local), plane(lower.tail_local)
    moved = top - Vector((0, drop))
    target = ankle + Vector((offset, lift))
    l1, l2 = (knee - top).length, (ankle - knee).length
    reach = target - moved
    distance = min(reach.length, l1 + l2 - 1e-6)
    if reach.length > l1 + l2 + 1e-4:
        raise RuntimeError(f'{leg}: unreachable hoof target {reach.length} > {l1 + l2}')
    along = (l1 * l1 - l2 * l2 + distance * distance) / (2 * distance)
    height = math.sqrt(max(0, l1 * l1 - along * along))
    unit = reach.normalized()
    normal = Vector((-unit.y, unit.x))
    side = 1 if (knee - top).dot(Vector((-(ankle - top).y, (ankle - top).x))) >= 0 else -1
    new_knee = moved + unit * along + normal * height * side
    upper_angle = angle(knee - top, new_knee - moved)
    lower_angle = angle(ankle - knee, target - new_knee) - upper_angle
    return upper_angle, lower_angle, -upper_angle - lower_angle


def key_legs(arm, frame, offsets, drop):
    pose = {}
    for leg in LEGS:
        offset, lift = offsets.get(leg, (0, 0))
        for part, rotation in zip(('upper', 'lower', 'foot'), solve_leg(arm, leg, offset, lift, drop)):
            bone = arm.pose.bones[f'{leg}_{part}']
            pose[bone.name] = world_rot(bone, X, rotation)
    key_pose(arm, frame, pose)
    # root points up, so its local Y is world Z.
    key_loc(arm, frame, 'root', Vector((0, -drop, 0)))


def idle(arm, lm):
    action = new_action(arm, 'idle')
    n = FPS * 4
    for frame in range(0, n + 1, 2):
        phase = frame / n * math.tau
        drop = lm['height'] * (0.035 + 0.003 * math.sin(phase * 2))
        key_legs(arm, frame, {}, drop)
        key_pose(arm, frame, {
            'neck': world_rot(arm.pose.bones['neck'], X, 0.018 * math.sin(phase * 2)),
            'head': world_rot(arm.pose.bones['head'], Z, 0.035 * math.sin(phase)),
        })
    finish_action(arm, action)


def walk(arm, lm):
    action = new_action(arm, 'walk')
    n = round(FPS * WALK_SECONDS)
    phases = {'back_l': 0, 'front_l': 0.25, 'back_r': 0.5, 'front_r': 0.75}
    span = SPEED * WALK_SECONDS * DUTY
    for frame in range(n + 1):
        t = frame / n
        offsets = {}
        for leg, phase in phases.items():
            p = (t + phase) % 1
            if p < DUTY:
                offset, lift = -span / 2 + SPEED * WALK_SECONDS * p, 0
            else:
                q = (p - DUTY) / (1 - DUTY)
                s = q * q * (3 - 2 * q)
                offset, lift = span / 2 - span * s, 0.07 * math.sin(q * math.pi) ** 2
            offsets[leg] = (offset, lift)
        drop = lm['height'] * (0.045 + 0.003 * math.cos(t * math.tau * 2))
        key_legs(arm, frame, offsets, drop)
        key_pose(arm, frame, {
            'neck': world_rot(arm.pose.bones['neck'], X, 0.02 * math.sin(t * math.tau * 2)),
        })
    finish_action(arm, action)
    # Dense linear keys retain constant stance velocity through glTF sampling.
    for curve in rig.action_fcurves(action):
        for point in curve.keyframe_points:
            point.interpolation = 'LINEAR'


def alert(arm, lm):
    action = new_action(arm, 'alert')
    n = round(FPS * 4.6)
    for frame in range(0, n + 1, 2):
        t = frame / n
        envelope = math.sin(t * math.pi) ** 2
        drop = lm['height'] * (0.035 + 0.018 * envelope)
        key_legs(arm, frame, {}, drop)
        key_pose(arm, frame, {
            'neck': world_rot(arm.pose.bones['neck'], X, -0.08 * envelope),
            'head': world_rot(arm.pose.bones['head'], X, -0.035 * envelope + 0.012 * math.sin(t * math.tau * 4) * envelope),
        })
    finish_action(arm, action)


def bind_hooves(obj, lm):
    """Keep the split hoof capsule rigid, blending into the lower leg above it."""
    height = lm['height']
    for vertex in obj.data.vertices:
        z = vertex.co.z / height
        if z >= 0.16:
            continue
        leg = min(LEGS, key=lambda name: (vertex.co.x - lm['legs'][name].x) ** 2 + (vertex.co.y - lm['legs'][name].y) ** 2)
        blend = 1.0 if z <= 0.10 else (0.16 - z) / 0.06
        original = {group.group: group.weight * (1 - blend) for group in vertex.groups}
        target = obj.vertex_groups[f'{leg}_foot'].index
        original[target] = original.get(target, 0) + blend
        for group in obj.vertex_groups:
            group.remove([vertex.index])
        for index, weight in original.items():
            if weight > 1e-6:
                obj.vertex_groups[index].add([vertex.index], weight, 'REPLACE')


def stitch_seams(obj):
    """Share the same four weights across UV splits, before the only export.

    Based on stitch_lili_skin.py; keeping the operation in this scene preserves
    the 30fps action timing instead of resampling a second import at 24fps.
    """
    tree = KDTree(len(obj.data.vertices))
    for vertex in obj.data.vertices:
        tree.insert(vertex.co, vertex.index)
    tree.balance()
    seen, repaired = set(), 0
    for seed in obj.data.vertices:
        if seed.index in seen:
            continue
        indices, pending = {seed.index}, [seed.index]
        while pending:
            for _, index, _ in tree.find_range(obj.data.vertices[pending.pop()].co, 1e-5):
                if index not in indices:
                    indices.add(index)
                    pending.append(index)
        seen.update(indices)
        if len(indices) < 2:
            continue
        weights = defaultdict(float)
        for index in indices:
            for group in obj.data.vertices[index].groups:
                weights[group.group] += group.weight
        strongest = sorted(weights.items(), key=lambda item: (-item[1], item[0]))[:4]
        total = sum(weight for _, weight in strongest)
        if total <= 0:
            raise RuntimeError('Unweighted UV seam')
        for group in obj.vertex_groups:
            group.remove(list(indices))
        for index, weight in strongest:
            obj.vertex_groups[index].add(list(indices), weight / total, 'REPLACE')
        repaired += 1
    print('TONGTONG stitched seam groups', repaired)


def main():
    args = rig.parse_args()
    obj = rig.load(args.input)
    bpy.context.scene.render.fps = FPS
    lm = rig.landmarks(obj)
    arm = rig.build_armature(lm)
    # More generous elbow/hock bend leaves room for a low pig's short stride.
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    for leg in LEGS:
        upper = arm.data.edit_bones[f'{leg}_upper']
        lower = arm.data.edit_bones[f'{leg}_lower']
        joint = upper.tail.copy()
        joint.y += (0.11 if leg.startswith('front') else -0.11) * lm['height']
        upper.tail = joint
        lower.head = joint
    bpy.ops.object.mode_set(mode='OBJECT')
    rig.skin(obj, arm)
    bind_hooves(obj, lm)
    stitch_seams(obj)
    print('TONGTONG landmarks', {key: tuple(round(c, 4) for c in value) for key, value in lm['legs'].items()})
    idle(arm, lm)
    walk(arm, lm)
    alert(arm, lm)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB', export_animations=True,
                              export_animation_mode='NLA_TRACKS', export_skins=True, export_def_bones=False)
    print('TONGTONG EXPORTED', args.output, 'triangles', len(obj.data.polygons), 'bones', len(arm.data.bones))


if __name__ == '__main__':
    main()
