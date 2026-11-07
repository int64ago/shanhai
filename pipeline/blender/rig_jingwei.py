"""Two-foot crow rig: independent feather wings and sagittal foot-contact IK.
Input: normalized +Z-forward GLB. Output: idle/walk/alert animated GLB.
Blender --background --python pipeline/blender/rig_jingwei.py -- input.glb output.glb
"""
import math
import os
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, os.path.dirname(__file__))
from rig_avian import (load, landmarks, new_action, finish_action,
                       key_pose, key_loc, world_rot, FPS)


def make_rig(obj):
    # Rodin's right toes can sit a few millimetres higher than the left. Correct
    # each contact plane before binding, fading the offset out along the shin.
    height = max(v.co.z for v in obj.data.vertices)
    width = max(v.co.x for v in obj.data.vertices) - min(v.co.x for v in obj.data.vertices)
    for sign in [1, -1]:
        low = [v.co.z for v in obj.data.vertices if sign * v.co.x > width * 0.06
               and v.co.y < height * 0.18 and v.co.z < height * 0.06]
        offset = min(low)
        for vertex in obj.data.vertices:
            p = vertex.co
            if sign * p.x > width * 0.06 and p.y < height * 0.18 and p.z < height * 0.34:
                u = max(0, min(1, (p.z / height - 0.10) / 0.24))
                p.z -= offset * (1 - u * u * (3 - 2 * u))
        print('FOOT_CONTACT', sign, 'corrected', round(offset, 5))
    obj.data.update()
    lm = landmarks(obj)
    h, span = lm['height'], lm['span']
    vs = [v.co for v in obj.data.vertices]
    low = [v for v in vs if v.z < h * 0.055]
    feet = {}
    for side, sign in [('l', 1), ('r', -1)]:
        pts = [v for v in low if sign * v.x > span * 0.025]
        feet[side] = Vector((sum(v.x for v in pts) / len(pts),
                             sum(v.y for v in pts) / len(pts) + h * 0.045,
                             h * 0.042))
    lm['feet'] = feet
    lm['pelvis'] = Vector((0, sum(p.y for p in feet.values()) / 2, h * 0.44))
    lm['chest'] = Vector((0, lm['pelvis'].y - h * 0.04, h * 0.65))
    lm['neck_base'] = Vector((0, lm['chest'].y - h * 0.07, h * 0.75))
    lm['tail_base'] = Vector((0, lm['pelvis'].y + h * 0.12, h * 0.4))
    # Crow tail extends downward behind the feet, unlike a crane's horizontal plumes.
    rear = max(vs, key=lambda v: v.y)
    lm['tail_tip'] = Vector((0, rear.y, rear.z))
    arm = bpy.data.objects.new('rig', bpy.data.armatures.new('rig'))
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.data.edit_bones

    def bone(name, a, b, parent=None, deform=True):
        item = eb.new(name)
        item.head, item.tail = a, b
        item.use_deform = deform
        if parent:
            item.parent = eb[parent]
        return item

    bone('root', (0, 0, 0), (0, 0, h * 0.1), deform=False)
    bone('pelvis', lm['pelvis'], lm['chest'], 'root')
    bone('chest', lm['chest'], lm['neck_base'], 'pelvis')
    bone('neck', lm['neck_base'], lm['head_base'], 'chest')
    bone('head', lm['head_base'], lm['beak_tip'], 'neck')
    bone('tail_feather', lm['tail_base'], lm['tail_tip'], 'pelvis')
    for side, foot in feet.items():
        hip = Vector((foot.x, foot.y + h * 0.02, h * 0.37))
        knee = Vector((foot.x, foot.y + h * 0.065, h * 0.21))
        bone(f'leg_{side}_upper', hip, knee, 'pelvis')
        bone(f'leg_{side}_lower', knee, foot, f'leg_{side}_upper')
        bone(f'foot_{side}', foot, foot + Vector((0, -h * 0.08, -h * 0.035)), f'leg_{side}_lower')
    for side in ['l', 'r']:
        points = lm[f'wing_{side}']
        for i in range(3):
            bone(f'wing_{side}_{i + 1}', points[i], points[i + 1], 'chest' if i == 0 else f'wing_{side}_{i}')
    bone('beak_attach', lm['beak_tip'], lm['beak_tip'] + Vector((0, -0.03, 0)), 'head', False)
    bpy.ops.object.mode_set(mode='OBJECT')
    print('LANDMARKS', {k: tuple(v) for k, v in lm.items() if isinstance(v, Vector)})
    print('LEGS', {k: tuple(v) for k, v in feet.items()})
    return arm, lm


def skin(obj, arm, lm):
    """Anatomical distance weights keep wing feathers independent of the belly.
    Explicit toe weights preserve the contact plane; the shoulder transitions
    smoothly from chest to wing rather than rigidly cutting the silhouette.
    """
    h, span = lm['height'], lm['span']
    bones = {b.name: b for b in arm.data.bones if b.use_deform}
    groups = {name: obj.vertex_groups.new(name=name) for name in bones}
    for v in obj.data.vertices:
        p = v.co
        side = 'l' if p.x >= 0 else 'r'
        leg = [f'leg_{side}_upper', f'leg_{side}_lower', f'foot_{side}']
        if p.z < h * 0.10 and p.y < lm['feet'][side].y + h * 0.12:
            groups[f'foot_{side}'].add([v.index], 1, 'REPLACE')
            continue
        if p.z < h * 0.34 and p.y < lm['feet'][side].y + h * 0.12:
            names = leg
        elif abs(p.x) > span * 0.14 and p.z > h * 0.38:
            names = [f'wing_{side}_{i}' for i in [1, 2, 3]]
            if abs(p.x) < span * 0.21:
                names += ['chest']
        elif p.y > lm['tail_base'].y and p.z < h * 0.45:
            names = ['tail_feather', 'pelvis']
        else:
            names = ['pelvis', 'chest', 'neck', 'head']
            if p.z < h * 0.43:
                names += leg[:1]
        scored = []
        for name in names:
            b = bones[name]
            a, end = b.head_local, b.tail_local
            ab = end - a
            t = max(0, min(1, (p - a).dot(ab) / max(ab.length_squared, 1e-8)))
            distance = max((a + ab * t - p).length, 1e-4)
            scored.append((distance, name))
        scored.sort()
        scored = scored[:3]
        total = sum(d ** -5.5 for d, _ in scored)
        for d, name in scored:
            groups[name].add([v.index], d ** -5.5 / total, 'REPLACE')
    mod = obj.modifiers.new('rig', 'ARMATURE')
    mod.object = arm
    obj.parent = arm
    print('SKIN anatomical distance weights', len(obj.data.vertices))


def set_segment(pb, a, b):
    rest = pb.bone
    rotation = (rest.tail_local - rest.head_local).rotation_difference(b - a)
    pb.matrix = Matrix.Translation(a) @ rotation.to_matrix().to_4x4() @ rest.matrix_local.to_quaternion().to_matrix().to_4x4()
    bpy.context.view_layer.update()


def contact(arm, lm, frame, pelvis_delta, backward=0, lift=0):
    for side, ankle in lm['feet'].items():
        upper = arm.pose.bones[f'leg_{side}_upper']
        lower = arm.pose.bones[f'leg_{side}_lower']
        foot = arm.pose.bones[f'foot_{side}']
        hip = upper.bone.head_local + pelvis_delta
        target = ankle + Vector((0, backward, lift))
        axis = target - hip
        distance = axis.length
        direction = axis.normalized()
        l1, l2 = upper.bone.length, lower.bone.length
        distance = min(distance, (l1 + l2) * 0.9999)
        along = (l1 * l1 - l2 * l2 + distance * distance) / (2 * distance)
        perpendicular = Vector((0, -direction.z, direction.y)).normalized()
        knee = hip + direction * along + perpendicular * math.sqrt(max(0, l1 * l1 - along * along))
        set_segment(upper, hip, knee)
        set_segment(lower, knee, target)
        # Keep the toes parallel to their original ground plane throughout stance.
        foot.matrix = Matrix.Translation(target - ankle) @ foot.bone.matrix_local
        bpy.context.view_layer.update()
        for pb in [upper, lower, foot]:
            pb.keyframe_insert('rotation_quaternion', frame=frame)
            pb.keyframe_insert('location', frame=frame)


def animate(arm, lm, name, seconds):
    action = new_action(arm, name)
    h = lm['height']
    n = round(seconds * FPS)
    for f in range(n + 1):
        phase = f / n
        t = phase * math.tau
        backward, lift = 0, 0
        if name == 'walk':
            # Half-cycle planted: the feet retreat at exactly 0.16 m/s, matching
            # the runtime path. Airborne return completes the two-foot hop.
            if phase <= 0.5:
                backward = -0.048 + 0.192 * phase
            else:
                u = (phase - 0.5) * 2
                backward = 0.048 - 0.096 * (u * u * (3 - 2 * u))
                lift = h * 0.095 * math.sin(math.pi * u)
            delta = Vector((0, 0, lift * 0.75))
            fold = 0.48 + 0.16 * math.cos(t)
            head_tilt = 0.035 * math.sin(t)
        elif name == 'alert':
            delta = Vector((0, 0, h * 0.004 * math.sin(t)))
            fold = 0.10 + 0.55 * math.sin(t * 2)
            head_tilt = 0.10 + 0.14 * math.sin(t)
        else:
            delta = Vector((0, 0, h * 0.003 * math.sin(t * 2)))
            fold = 0.82 + 0.025 * math.sin(t * 2)
            head_tilt = 0.035 * math.sin(t)
        local_delta = arm.data.bones['pelvis'].matrix_local.to_3x3().inverted() @ delta
        key_loc(arm, f, 'pelvis', local_delta)
        pose = {
            'head': world_rot(arm.pose.bones['head'], (1, 0, 0), head_tilt),
            'neck': world_rot(arm.pose.bones['neck'], (0, 0, 1), 0.035 * math.sin(t)),
            'tail_feather': world_rot(arm.pose.bones['tail_feather'], (1, 0, 0), 0.025 * math.sin(t)),
        }
        for side, sign in [('l', 1), ('r', -1)]:
            for i in [1, 2, 3]:
                angle = fold if i == 1 else (0.10 if name == 'idle' else 0.08 * math.sin(t * 2 - i * 0.35))
                pose[f'wing_{side}_{i}'] = world_rot(arm.pose.bones[f'wing_{side}_{i}'], (0, 1, 0), sign * angle)
        key_pose(arm, f, pose)
        bpy.context.view_layer.update()
        contact(arm, lm, f, delta, backward, lift)
    finish_action(arm, action)
    # Dense samples preserve linear contact velocity and prevent Bezier foot overshoot.
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    for key in fc.keyframe_points:
                        key.interpolation = 'LINEAR'


def main():
    args = sys.argv[sys.argv.index('--') + 1:]
    obj = load(args[0])
    bpy.context.scene.render.fps = FPS
    arm, lm = make_rig(obj)
    skin(obj, arm, lm)
    animate(arm, lm, 'idle', 4)
    animate(arm, lm, 'walk', 1.2)
    animate(arm, lm, 'alert', 2.4)
    bpy.ops.export_scene.gltf(filepath=args[1], export_format='GLB', export_animations=True,
                              export_animation_mode='NLA_TRACKS', export_skins=True,
                              export_def_bones=False)
    print('EXPORTED', args[1], 'bones', len(arm.data.bones))


if __name__ == '__main__':
    main()
