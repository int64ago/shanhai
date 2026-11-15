"""Auto-rig and animate Xixiyu (鳛鳛鱼) magpie-fish core retaining two folded wings, plus eight modular scaled-feather wings.

Bones:
- root: ground anchor
- pelvis -> chest -> neck -> head (rigid beak/skull protection)
- pelvis -> tail_1 -> tail_2 -> tail_3
- 5 pairs of wing mounts: wing_{0..4}_{l,r}_attach (non-deform)
- VFX mounts: beak_attach, tail_attach, chest_attach (non-deform)

Usage:
  Blender --background --factory-startup --python-exit-code 1 --python pipeline/blender/rig_xixiyu.py -- \
      <body_norm.glb> <body_rig.glb> [--preview <file.png>]
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

FPS = 30

# 5 paired flank mount offsets (x_abs, y, z, parent_bone) along the streamlined torso.
# Head faces -Y in Blender; +X is anatomical left (_l), -X is anatomical right (_r).
WING_MOUNTS = [
    (0, 0.065, -0.32, 0.550, 'chest'),
    (1, 0.105, -0.12, 0.565, 'chest'),
    (2, 0.112, -0.10, 0.462, 'pelvis'),  # reserved: native folded pair
    (3, 0.090,  0.015, 0.550, 'pelvis'),
    (4, 0.055,  0.16, 0.490, 'pelvis'),
]


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('input')
    p.add_argument('output')
    p.add_argument('--preview')
    return p.parse_args(argv)


def load_body(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if len(meshes) != 1:
        raise RuntimeError(f'Expected 1 mesh in {path}, found {len(meshes)}')
    obj = meshes[0]
    for o in list(bpy.context.scene.objects):
        if o is not obj:
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def build_armature():
    arm_data = bpy.data.armatures.new('xixiyu_rig')
    arm = bpy.data.objects.new('xixiyu_rig', arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm_data.edit_bones

    def bone(name, head, tail, parent=None, deform=True):
        b = eb.new(name)
        b.head = Vector(head)
        b.tail = Vector(tail)
        b.roll = 0
        b.use_deform = deform
        if parent:
            b.parent = eb[parent]
            b.use_connect = (eb[parent].tail - b.head).length < 1e-4
        return b

    bone('root', (0, 0, 0), (0, 0, 0.15), deform=False)
    bone('pelvis', (0, 0.05, 0.440), (0, -0.14, 0.452), 'root')
    bone('chest', (0, -0.14, 0.452), (0, -0.36, 0.470), 'pelvis')
    bone('neck', (0, -0.36, 0.470), (0, -0.49, 0.510), 'chest')
    bone('head', (0, -0.49, 0.510), (0, -0.73, 0.483), 'neck')

    bone('tail_1', (0, 0.05, 0.440), (0, 0.26, 0.428), 'pelvis')
    bone('tail_2', (0, 0.26, 0.428), (0, 0.50, 0.422), 'tail_1')
    bone('tail_3', (0, 0.50, 0.422), (0, 0.74, 0.422), 'tail_2')

    for idx, ax, ay, az, parent in WING_MOUNTS:
        for side, sign in (('l', 1.0), ('r', -1.0)):
            p = Vector((sign * ax, ay, az))
            bone(f'wing_{idx}_{side}_attach', p, p + Vector((sign * 0.05, 0, 0)), parent, deform=False)

    bone('beak_attach', (0, -0.725, 0.483), (0, -0.785, 0.483), 'head', deform=False)
    bone('tail_attach', (0, 0.725, 0.425), (0, 0.785, 0.425), 'tail_3', deform=False)
    bone('chest_attach', (0, -0.22, 0.46), (0, -0.22, 0.52), 'chest', deform=False)

    bpy.ops.object.mode_set(mode='OBJECT')
    return arm


def skin(obj, arm):
    deform = [b for b in arm.data.bones if b.use_deform]
    segs = [(b.name, arm.matrix_world @ b.head_local, arm.matrix_world @ b.tail_local) for b in deform]
    obj.vertex_groups.clear()
    groups = {name: obj.vertex_groups.new(name=name) for name, _, _ in segs}
    mw = obj.matrix_world

    for v in obj.data.vertices:
        p = mw @ v.co
        # Keep the magpie skull, eyes and beak rigid to prevent ocular distortion.
        if p.y <= -0.485:
            groups['head'].add([v.index], 1.0, 'REPLACE')
            continue

        scored = []
        for name, a, b in segs:
            if name in ('tail_1', 'tail_2', 'tail_3') and p.y < 0.05:
                continue
            if name in ('chest', 'neck', 'head') and p.y > 0.10:
                continue
            ab = b - a
            t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-8)))
            d = (a + ab * t - p).length
            scored.append((d, name))
        scored.sort()
        nearest = scored[:3]
        ws = [1.0 / max(d, 1e-4) ** 6.0 for d, _ in nearest]
        total = sum(ws)
        for (_, name), w in zip(nearest, ws):
            if w / total > 0.01:
                groups[name].add([v.index], w / total, 'REPLACE')

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
    bpy.ops.object.vertex_group_smooth(group_select_mode='ALL', factor=0.45, repeat=4)
    bpy.ops.object.vertex_group_limit_total(group_select_mode='ALL', limit=4)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode='ALL', lock_active=False)
    bpy.ops.object.mode_set(mode='OBJECT')

    # Re-pin rigid skull/beak vertices after smoothing.
    for v in obj.data.vertices:
        if (mw @ v.co).y <= -0.50:
            for g in groups.values():
                g.remove([v.index])
            groups['head'].add([v.index], 1.0, 'REPLACE')

    mod = obj.modifiers.new('rig', 'ARMATURE')
    mod.object = arm
    obj.parent = arm


def world_rot(pb, axis, angle):
    rest = pb.bone.matrix_local.to_3x3()
    return Quaternion(rest.inverted() @ Vector(axis), angle)


def key_pose(arm, frame, pose):
    for name, q in pose.items():
        pb = arm.pose.bones[name]
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = q
        pb.keyframe_insert('rotation_quaternion', frame=frame)


def key_loc(arm, frame, name, delta_world):
    pb = arm.pose.bones[name]
    pb.location = pb.bone.matrix_local.to_3x3().inverted() @ Vector(delta_world)
    pb.keyframe_insert('location', frame=frame)


def new_action(arm, name):
    arm.animation_data_create()
    action = bpy.data.actions.new(name)
    arm.animation_data.action = action
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = Quaternion()
        pb.location = Vector()
    return action


def action_fcurves(action):
    if hasattr(action, 'layers') and action.layers:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    yield from bag.fcurves
    else:
        yield from action.fcurves


def finish_action(arm, action, loop=True):
    for fc in action_fcurves(action):
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'
        if loop:
            mod = fc.modifiers.new('CYCLES')
            mod.mode_before = mod.mode_after = 'REPEAT'
    track = arm.animation_data.nla_tracks.new()
    track.name = action.name
    track.strips.new(action.name, int(action.frame_range[0]), action)
    track.mute = True
    arm.animation_data.action = None


def smooth01(a, b, x):
    t = max(0.0, min(1.0, (x - a) / max(b - a, 1e-6)))
    return t * t * (3.0 - 2.0 * t)


X, Y, Z = (1, 0, 0), (0, 1, 0), (0, 0, 1)


def anim_idle(arm):
    """4.0s gentle aquatic-avian hover, slight head glance and soft sculling tail."""
    action = new_action(arm, 'idle')
    n = round(4.0 * FPS)
    for f in range(0, n + 1, 2):
        t = (f / n) * math.tau
        bob = 0.020 * math.sin(t * 2.0)
        key_loc(arm, f, 'pelvis', (0.0, 0.0, bob))
        key_pose(arm, f, {
            'pelvis': world_rot(arm.pose.bones['pelvis'], X, 0.025 * math.cos(t * 2.0))
                      @ world_rot(arm.pose.bones['pelvis'], Z, 0.03 * math.sin(t)),
            'chest': world_rot(arm.pose.bones['chest'], X, -0.02 * math.cos(t * 2.0))
                     @ world_rot(arm.pose.bones['chest'], Z, -0.02 * math.sin(t)),
            'neck': world_rot(arm.pose.bones['neck'], Z, 0.06 * math.sin(t + 0.4))
                    @ world_rot(arm.pose.bones['neck'], X, 0.03 * math.sin(t * 2.0)),
            'head': world_rot(arm.pose.bones['head'], Z, 0.04 * math.sin(t + 0.7))
                    @ world_rot(arm.pose.bones['head'], Y, 0.04 * math.sin(t)),
            'tail_1': world_rot(arm.pose.bones['tail_1'], Z, 0.09 * math.sin(t - 0.5))
                      @ world_rot(arm.pose.bones['tail_1'], X, 0.03 * math.sin(t * 2.0 - 0.4)),
            'tail_2': world_rot(arm.pose.bones['tail_2'], Z, 0.13 * math.sin(t - 1.1))
                      @ world_rot(arm.pose.bones['tail_2'], X, 0.04 * math.sin(t * 2.0 - 0.9)),
            'tail_3': world_rot(arm.pose.bones['tail_3'], Z, 0.16 * math.sin(t - 1.7))
                      @ world_rot(arm.pose.bones['tail_3'], X, 0.04 * math.sin(t * 2.0 - 1.4)),
        })
    finish_action(arm, action, loop=True)


def anim_walk(arm):
    """2.4s swift gliding/swimming undulation with active lateral tail propulsion."""
    action = new_action(arm, 'walk')
    n = round(2.4 * FPS)
    for f in range(0, n + 1, 2):
        t = (f / n) * math.tau
        bob = 0.032 * math.sin(t * 2.0)
        surge = -0.022 * math.cos(t * 2.0)
        key_loc(arm, f, 'pelvis', (0.012 * math.sin(t), surge, bob))
        key_pose(arm, f, {
            'pelvis': world_rot(arm.pose.bones['pelvis'], Z, 0.07 * math.sin(t))
                      @ world_rot(arm.pose.bones['pelvis'], X, 0.04 * math.sin(t * 2.0)),
            'chest': world_rot(arm.pose.bones['chest'], Z, -0.06 * math.sin(t - 0.3))
                     @ world_rot(arm.pose.bones['chest'], X, -0.05 * math.sin(t * 2.0)),
            'neck': world_rot(arm.pose.bones['neck'], Z, -0.04 * math.sin(t - 0.6))
                    @ world_rot(arm.pose.bones['neck'], X, 0.03 * math.cos(t * 2.0)),
            'head': world_rot(arm.pose.bones['head'], Z, 0.03 * math.sin(t))
                    @ world_rot(arm.pose.bones['head'], Y, 0.05 * math.sin(t)),
            'tail_1': world_rot(arm.pose.bones['tail_1'], Z, 0.16 * math.sin(t - 0.6))
                      @ world_rot(arm.pose.bones['tail_1'], X, 0.04 * math.cos(t * 2.0)),
            'tail_2': world_rot(arm.pose.bones['tail_2'], Z, 0.22 * math.sin(t - 1.3))
                      @ world_rot(arm.pose.bones['tail_2'], X, 0.05 * math.cos(t * 2.0 - 0.5)),
            'tail_3': world_rot(arm.pose.bones['tail_3'], Z, 0.26 * math.sin(t - 2.0))
                      @ world_rot(arm.pose.bones['tail_3'], X, 0.05 * math.cos(t * 2.0 - 1.0)),
        })
    finish_action(arm, action, loop=True)


def anim_special(arm):
    """4.5s fire-warding ascent («可以禦火»): rises, flares crest/tail, sweeps back to idle."""
    seconds = 4.5
    action = new_action(arm, 'special')
    n = round(seconds * FPS)
    for f in range(0, n + 1, 2):
        sec = f / FPS
        rise = smooth01(0.15, 0.95, sec) * (1.0 - smooth01(3.2, 4.35, sec))
        hover_bob = 0.025 * math.sin(sec * 4.5) * rise
        sweep_wave = math.sin(sec * 5.0)
        key_loc(arm, f, 'pelvis', (0.0, 0.04 * rise, 0.14 * rise + hover_bob))
        key_pose(arm, f, {
            'pelvis': world_rot(arm.pose.bones['pelvis'], X, -0.14 * rise + 0.04 * sweep_wave * rise)
                      @ world_rot(arm.pose.bones['pelvis'], Z, 0.06 * math.sin(sec * 2.8) * rise),
            'chest': world_rot(arm.pose.bones['chest'], X, -0.10 * rise),
            'neck': world_rot(arm.pose.bones['neck'], X, -0.06 * rise)
                    @ world_rot(arm.pose.bones['neck'], Z, 0.10 * math.sin(sec * 3.5) * rise),
            'head': world_rot(arm.pose.bones['head'], X, 0.22 * rise)
                    @ world_rot(arm.pose.bones['head'], Z, -0.08 * math.sin(sec * 3.5) * rise),
            'tail_1': world_rot(arm.pose.bones['tail_1'], X, 0.14 * rise + 0.06 * sweep_wave * rise)
                      @ world_rot(arm.pose.bones['tail_1'], Z, 0.16 * math.sin(sec * 4.5 - 0.5) * rise),
            'tail_2': world_rot(arm.pose.bones['tail_2'], X, 0.10 * rise)
                      @ world_rot(arm.pose.bones['tail_2'], Z, 0.22 * math.sin(sec * 4.5 - 1.1) * rise),
            'tail_3': world_rot(arm.pose.bones['tail_3'], X, 0.08 * rise)
                      @ world_rot(arm.pose.bones['tail_3'], Z, 0.25 * math.sin(sec * 4.5 - 1.7) * rise),
        })
    finish_action(arm, action, loop=False)


def render_preview(arm, out_path):
    # Shared runner passes a file path and publishes that exact idle preview.
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    stem, extension = os.path.splitext(out_path)
    extension = extension or '.png'
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = scene.render.resolution_y = 640
    scene.view_settings.view_transform = 'Standard'
    world = bpy.data.worlds.new('w')
    world.use_nodes = True
    bg = world.node_tree.nodes['Background']
    bg.inputs[0].default_value = (0.90, 0.89, 0.86, 1)
    scene.world = world
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
    sun.data.energy = 2.0
    sun.rotation_euler = (math.radians(35), 0, math.radians(25))
    scene.collection.objects.link(sun)

    center = Vector((0, 0, 0.45))
    d = 3.2
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
    cam.data.type = 'ORTHO'
    cam.data.ortho_scale = 1.8
    scene.collection.objects.link(cam)
    loc = center + Vector((d * 0.65, -d * 0.72, d * 0.35))
    fwd = (center - loc).normalized()
    right = fwd.cross(Vector((0, 0, 1))).normalized()
    up = right.cross(fwd).normalized()
    cam.matrix_world = Matrix.Translation(loc) @ Matrix((right, up, -fwd)).transposed().to_4x4()
    scene.camera = cam

    for track in arm.animation_data.nla_tracks:
        track.mute = False
        act = track.strips[0].action
        frame = int((act.frame_range[0] + act.frame_range[1]) * 0.4)
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        scene.render.filepath = out_path if track.name == 'idle' else f'{stem}-{track.name}{extension}'
        bpy.ops.render.render(write_still=True)
        track.mute = True


def main():
    args = parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    obj = load_body(args.input)
    arm = build_armature()
    skin(obj, arm)
    bpy.context.scene.render.fps = FPS
    anim_idle(arm)
    anim_walk(arm)
    anim_special(arm)
    if args.preview:
        render_preview(arm, args.preview)
    bpy.ops.export_scene.gltf(
        filepath=args.output,
        export_format='GLB',
        export_animations=True,
        export_nla_strips=True,
        export_frame_step=1,
    )
    print('EXPORTED', args.output)


if __name__ == '__main__':
    main()
