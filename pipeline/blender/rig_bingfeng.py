"""Bingfeng: two independently animated pig heads and four planted hooves.

Reuses the existing quadruped skin fallbacks and planted IK baker. The second
head is a proper deform chain parented to hips, not a tail or an inert copy.
Usage: blender -b --python rig_bingfeng.py -- body_clean.glb body_rig.glb
"""
import argparse
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_quadruped as rig
from animate_chenghuang import animate, fill_unweighted, world_rot
from prepare_huan import stitch_skin


def blend_front_head(obj):
    """Keep the face rigid while blending its neck continuously into the body."""
    target = obj.vertex_groups['head']
    for vertex in obj.data.vertices:
        # The rear duplicate lies at positive Y and is handled separately.
        t = min(1.0, max(0.0, (-vertex.co.y - .15) / .15))
        t *= min(1.0, max(0.0, (vertex.co.z - .25) / .10))
        t = t * t * (3 - 2 * t)
        if t == 0:
            continue
        weights = {g.group: g.weight * (1 - t) for g in vertex.groups}
        weights[target.index] = weights.get(target.index, 0) + t
        for group in obj.vertex_groups:
            group.remove([vertex.index])
        for index, weight in weights.items():
            if weight > 0:
                obj.vertex_groups[index].add([vertex.index], weight, 'REPLACE')


def rear_chain(arm):
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    bones = arm.data.edit_bones
    neck = bones.new('rear_neck')
    neck.head = Vector((0, .275, .42))
    neck.tail = Vector((0, .40, .39))
    neck.parent = bones['hips']
    head = bones.new('rear_head')
    head.head = neck.tail
    head.tail = Vector((0, .59, .39))
    head.parent = neck
    head.use_connect = True
    # Modest knee bends provide real reach for the .18m stance displacement.
    for side in ('l', 'r'):
        for end, sign in [('front', 1), ('back', -1)]:
            upper = bones[f'{end}_{side}_upper']
            lower = bones[f'{end}_{side}_lower']
            point = upper.tail.copy()
            point.y += sign * .045
            upper.tail = point
            lower.head = point
    bpy.ops.object.mode_set(mode='OBJECT')


def pose_heads(arm, action, t):
    bones = arm.pose.bones
    # Keep the heavy necks close to the torso; only the heads survey outward.
    amplitude = .15 if action == 'alert' else .035
    front_turn = amplitude * math.sin(t)
    rear_turn = amplitude * math.sin(t + math.pi)
    bones['neck'].rotation_quaternion = world_rot(bones['neck'], (0, 0, 1), front_turn)
    bones['head'].rotation_quaternion = world_rot(bones['head'], (1, 0, 0), .025 * math.sin(t * 2))
    bones['rear_neck'].rotation_quaternion = world_rot(bones['rear_neck'], (0, 0, 1), rear_turn)
    bones['rear_head'].rotation_quaternion = world_rot(bones['rear_head'], (1, 0, 0), -.025 * math.sin(t * 2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    obj = rig.load(args.input)
    bpy.context.scene.render.fps = rig.FPS
    lm = rig.landmarks(obj)
    print('BINGFENG legs', {k: tuple(v) for k, v in lm['legs'].items()})
    arm = rig.build_armature(lm)
    rear_chain(arm)
    rig.skin(obj, arm)
    rig.bind_rigid_parts(obj, arm, ['bingfeng_rear:rear_head'])
    blend_front_head(obj)
    fill_unweighted(arm)
    # The HIGH atlas has coincident vertices at UV boundaries; they must deform
    # identically, including where a head's neck transitions into the torso.
    stitch_skin(obj)
    animate(arm, pose_extra=pose_heads)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB', export_animations=True,
                             export_animation_mode='NLA_TRACKS', export_skins=True, export_def_bones=False)
    print('EXPORTED BINGFENG', args.output, 'bones', len(arm.data.bones))


if __name__ == '__main__':
    main()
