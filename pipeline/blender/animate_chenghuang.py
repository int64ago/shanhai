"""Bake planted-paw fox motions over the standard quadruped skin.

Input is rig_quadruped.py's output. Temporary two-link IK constraints hold
ankles to fixed-height targets and cancel foot pitch; only baked bones export.
Walk stance moves .18 m over .6 s, matching Quadruped's .3 m/s stage speed.
"""
import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

FPS = 30
PHASE = {'back_l': 0, 'front_l': 0.25, 'back_r': 0.5, 'front_r': 0.75}


def cycle(p):
    if p < 0.6:
        return -0.09 + 0.18 * p / 0.6, 0
    q = (p - 0.6) / 0.4
    return 0.09 - 0.18 * q * q * (3 - 2 * q), 0.055 * math.sin(q * math.pi)


def world_rot(pb, axis, angle):
    return Quaternion(pb.bone.matrix_local.to_3x3().inverted() @ Vector(axis), angle)


def reset(arm):
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = Quaternion()
        pb.location = Vector()
        pb.scale = Vector((1, 1, 1))


def fill_unweighted(arm):
    """Heat weighting may leave a handful of vertices below the global fallback threshold."""
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH' or not any(m.type == 'ARMATURE' and m.object == arm for m in obj.modifiers):
            continue
        # The glTF exporter puts a few heat-weight misses on neutral_bone.
        # Rebind those as well, rather than carrying a stationary fallback joint.
        groups = {g.index: g.name for g in obj.vertex_groups
                  if g.name in arm.data.bones and g.name != 'neutral_bone'}
        fixed = 0
        for vertex in obj.data.vertices:
            if sum(g.weight for g in vertex.groups if g.group in groups) > 1e-6:
                continue
            point = arm.matrix_world.inverted() @ obj.matrix_world @ vertex.co
            def distance(bone):
                a, b = bone.head_local, bone.tail_local
                ab = b - a
                t = max(0, min(1, (point - a).dot(ab) / max(ab.length_squared, 1e-10)))
                return (point - a - ab * t).length_squared
            closest = min((b for b in arm.data.bones if b.name not in ['root', 'tail_attach', 'neutral_bone']), key=distance)
            for group in obj.vertex_groups:
                group.remove([vertex.index])
            group = obj.vertex_groups.get(closest.name) or obj.vertex_groups.new(name=closest.name)
            group.add([vertex.index], 1, 'REPLACE')
            fixed += 1
        neutral = obj.vertex_groups.get('neutral_bone')
        if neutral:
            obj.vertex_groups.remove(neutral)
        print('SKIN_FILL_UNWEIGHTED', obj.name, fixed)
    if arm.data.bones.get('neutral_bone'):
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode='EDIT')
        arm.data.edit_bones.remove(arm.data.edit_bones['neutral_bone'])
        bpy.ops.object.mode_set(mode='OBJECT')


def animate(arm):
    arm.animation_data_clear()
    reset(arm)
    targets, constraints = {}, []
    for leg in PHASE:
        lower = arm.pose.bones[leg + '_lower']
        foot = arm.pose.bones[leg + '_foot']
        ankle = lower.bone.tail_local.copy()
        target = bpy.data.objects.new(leg + '_ankle_target', None)
        bpy.context.scene.collection.objects.link(target)
        target.location = arm.matrix_world @ ankle
        target.rotation_mode = 'QUATERNION'
        target.rotation_quaternion = (arm.matrix_world @ foot.bone.matrix_local).to_quaternion()
        ik = lower.constraints.new('IK')
        ik.target = target
        ik.chain_count = 2
        ik.use_stretch = False
        ik.iterations = 100
        pin = foot.constraints.new('COPY_ROTATION')
        pin.target = target
        pin.target_space = 'WORLD'
        pin.owner_space = 'WORLD'
        targets[leg] = (target, ankle)
        constraints.extend([(lower, ik), (foot, pin)])

    samples = {}
    max_error = 0
    for name, duration in [('idle', 4), ('walk', 1), ('alert', 2)]:
        frames = []
        for f in range(duration * FPS + 1):
            reset(arm)
            t = f / (duration * FPS) * math.tau
            arm.pose.bones['spine1'].rotation_quaternion = world_rot(arm.pose.bones['spine1'], (1, 0, 0), 0.006 * math.sin(t * 2))
            if name == 'walk':
                arm.pose.bones['spine2'].rotation_quaternion = world_rot(arm.pose.bones['spine2'], (0, 0, 1), 0.012 * math.sin(t))
            if name == 'alert':
                arm.pose.bones['neck'].rotation_quaternion = world_rot(arm.pose.bones['neck'], (1, 0, 0), -0.14) @ world_rot(arm.pose.bones['neck'], (0, 0, 1), 0.08 * math.sin(t))
                arm.pose.bones['head'].rotation_quaternion = world_rot(arm.pose.bones['head'], (1, 0, 0), 0.06)
            else:
                arm.pose.bones['neck'].rotation_quaternion = world_rot(arm.pose.bones['neck'], (0, 0, 1), 0.045 * math.sin(t))
            for leg, (target, ankle) in targets.items():
                pos = ankle.copy()
                if name == 'walk':
                    back, lift = cycle((f / FPS + PHASE[leg]) % 1)
                    pos.y += back
                    pos.z += lift
                target.location = arm.matrix_world @ pos
            bpy.context.scene.frame_set(f)
            bpy.context.view_layer.update()
            evaluated = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
            frames.append({pb.name: evaluated.pose.bones[pb.name].matrix.copy() for pb in arm.pose.bones})
            for leg, (target, _) in targets.items():
                actual = arm.matrix_world @ evaluated.pose.bones[leg + '_lower'].tail
                max_error = max(max_error, (actual - target.location).length)
        samples[name] = frames
    print('ANKLE_TARGET_MAX_ERROR', round(max_error, 6))
    if max_error > 0.025:
        raise RuntimeError('The ankle target is outside the reach of the fox skeleton')
    for bone, constraint in constraints:
        bone.constraints.remove(constraint)
    for target, _ in targets.values():
        bpy.data.objects.remove(target, do_unlink=True)

    arm.animation_data_create()
    for name, frames in samples.items():
        action = bpy.data.actions.new(name)
        arm.animation_data.action = action
        for frame, matrices in enumerate(frames):
            # Convert explicitly using the sampled parent matrix. A pose-matrix
            # setter can otherwise read the previous frame's evaluated parent.
            for pb in arm.pose.bones:
                parent = pb.parent
                kwargs = ({'parent_matrix': matrices[parent.name],
                           'parent_matrix_local': parent.bone.matrix_local} if parent else {})
                pb.matrix_basis = pb.bone.convert_local_to_pose(
                    matrices[pb.name], pb.bone.matrix_local, invert=True, **kwargs)
                pb.keyframe_insert('location', frame=frame)
                pb.keyframe_insert('rotation_quaternion', frame=frame)
                pb.keyframe_insert('scale', frame=frame)
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:
                            key.interpolation = 'LINEAR'
        max_bake_error = 0
        for frame, matrices in enumerate(frames):
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()
            for pb in arm.pose.bones:
                max_bake_error = max(max_bake_error, (pb.matrix.translation - matrices[pb.name].translation).length)
        print('BAKE_MAX_POSITION_ERROR', name, round(max_bake_error, 6))
        if max_bake_error > 0.001:
            raise RuntimeError(f'{name}: baked bone poses differ from the planted IK samples')
        track = arm.animation_data.nla_tracks.new()
        track.name = name
        track.strips.new(name, 0, action)
        track.mute = True
        arm.animation_data.action = None
    reset(arm)
    bpy.context.scene.frame_set(0)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input')
    p.add_argument('output')
    a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=a.input)
    arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    bpy.context.scene.render.fps = FPS
    fill_unweighted(arm)
    animate(arm)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', export_animations=True,
                              export_animation_mode='NLA_TRACKS', export_skins=True, export_def_bones=False)
    print('EXPORTED', a.output)


if __name__ == '__main__':
    main()
