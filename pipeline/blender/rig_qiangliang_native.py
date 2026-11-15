"""Native four-hoof Qiangliang rig; preserves mesh and UV, 3 clips.
Blender --background --factory-startup --disable-autoexec --python-exit-code 1
 --python pipeline/blender/rig_qiangliang_native.py -- INPUT OUTPUT
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Vector
import rig_quadruped as base
from rig_yingzhao import contact

FPS, HEIGHT, RADIUS, SPEED, WALK_SECONDS, DUTY = 30, 1.65, 1., .085, 2.4, .66


def smooth(a, b, value):
    t = max(0., min(1., (value - a) / (b - a)))
    return t * t * (3 - 2 * t)


def distance(p, bone):
    delta = bone.tail_local - bone.head_local
    t = max(0., min(1., (p - bone.head_local).dot(delta) / delta.length_squared))
    return (p - bone.head_local - delta * t).length


def make_rig():
    arm = bpy.data.objects.new('qiangliang_rig', bpy.data.armatures.new('qiangliang_native'))
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(name, a, b, parent=None):
        item = arm.data.edit_bones.new(name)
        item.head, item.tail = Vector(a) * HEIGHT, Vector(b) * HEIGHT
        if parent:
            item.parent = arm.data.edit_bones[parent]
    bone('root', (0, 0, 0), (0, 0, .1))
    bone('hips', (0, .015, .49), (0, .015, .60), 'root')
    bone('chest', (0, .015, .60), (0, .01, .77), 'hips')
    bone('neck', (0, .01, .77), (0, 0, .85), 'chest')
    bone('head', (0, 0, .85), (0, -.025, .97), 'neck')
    bone('mouth_attach', (0, -.152, .865), (0, -.185, .865), 'head')
    for sign, side in [(1, 'l'), (-1, 'r')]:
        hip = (sign * .105, .015, .49)
        knee = (sign * .108, -.018, .275)
        ankle = (sign * .105, -.005, .075)
        bone(f'leg_{side}_upper', hip, knee, 'hips')
        bone(f'leg_{side}_lower', knee, ankle, f'leg_{side}_upper')
        bone(f'leg_{side}_foot', ankle, (sign * .105, -.095, .03), f'leg_{side}_lower')
        bone(f'arm_{side}_upper', (sign * .145, .005, .775), (sign * .238, .005, .635), 'chest')
        bone(f'arm_{side}_lower', (sign * .238, .005, .635), (sign * .307, -.005, .485), f'arm_{side}_upper')
        bone(f'arm_{side}_hand', (sign * .307, -.005, .485), (sign * .332, -.015, .425), f'arm_{side}_lower')
        # The serpent rests against the upper/front face of the hoof and forearm.
        bone(f'hold_{side}_attach', (sign * .305, -.092, .495), (sign * .305, -.132, .495), f'arm_{side}_hand')
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm


def skin(obj, arm):
    groups = {b.name: obj.vertex_groups.new(name=b.name) for b in arm.data.bones}
    masks = {'feet': {'l': [], 'r': []}, 'soles': {'l': [], 'r': []}, 'hands': {'l': [], 'r': []}}
    def inverse(p, names):
        values = {name: 1 / max(.01 * HEIGHT, distance(p, arm.data.bones[name])) ** 4 for name in names}
        total = sum(values.values())
        return {name: value / total for name, value in values.items()}
    for v in obj.data.vertices:
        p = v.co
        x, z = abs(p.x) / HEIGHT, p.z / HEIGHT
        side = 'l' if p.x > 0 else 'r'
        if z < .105:
            weights = {f'leg_{side}_foot': 1.}
            masks['feet'][side].append(v.index)
            if p.z < .003:
                masks['soles'][side].append(v.index)
        elif z < .45 and x < .235:
            weights = inverse(p, [f'leg_{side}_{part}' for part in ['upper', 'lower', 'foot']])
            rigid = 1 - smooth(.105, .18, z)
            weights = {name: value * (1 - rigid) for name, value in weights.items()}
            weights[f'leg_{side}_foot'] += rigid
            pelvis = smooth(.35, .45, z)
            weights = {name: value * (1 - pelvis) for name, value in weights.items()}
            weights['hips'] = pelvis
        elif z > .835 and x < .18:
            weights = {'head': 1.}
        else:
            torso = inverse(p, ['hips', 'chest', 'neck'])
            threshold = .265 - .115 * smooth(.50, .80, z)
            blend = smooth(threshold - .01, threshold + .028, x)
            blend *= 1 - smooth(.80, .85, z)
            if x < .14:
                blend = 0
            if blend:
                if z < .49:
                    limb = {f'arm_{side}_hand': 1.}
                    if blend > .999:
                        masks['hands'][side].append(v.index)
                else:
                    limb = inverse(p, [f'arm_{side}_{part}' for part in ['upper', 'lower', 'hand']])
                weights = {name: value * (1 - blend) for name, value in torso.items()}
                for name, value in limb.items():
                    weights[name] = weights.get(name, 0) + value * blend
            else:
                weights = torso
        weights = dict(sorted(((name, value) for name, value in weights.items() if value > 1e-7),
                              key=lambda item: item[1], reverse=True)[:4])
        total = sum(weights.values())
        for name, value in weights.items():
            groups[name].add([v.index], value / total, 'REPLACE')
    modifier = obj.modifiers.new('native_four_hoof_skin', 'ARMATURE')
    modifier.object = arm
    obj.parent = arm
    assert all(len(masks['soles'][s]) > 10 and len(masks['hands'][s]) > 20 for s in ['l', 'r'])
    return masks


def animate(arm, name, seconds):
    action = base.new_action(arm, name)
    count = round(seconds * FPS)
    for frame in range(count + 1):
        t, phase = frame / FPS, frame / count
        display = smooth(.25, 1.2, t) * (1 - smooth(2.7, 4., t)) if name == 'special' else 0
        delta = Vector((0, 0, -.012 if name == 'walk' else 0))
        pose = {'head': base.world_rot(arm.pose.bones['head'], base.X, -.045 * display + .004 * math.sin(phase * math.tau)),
                'chest': base.world_rot(arm.pose.bones['chest'], base.X, .004 * math.sin(phase * math.tau))}
        for sign, side in [(1, 'l'), (-1, 'r')]:
            swing = sign * .055 * math.sin(phase * math.tau) if name == 'walk' else .007 * math.sin(phase * math.tau)
            upper = arm.pose.bones[f'arm_{side}_upper']
            lower = arm.pose.bones[f'arm_{side}_lower']
            # Left forearm continuously supports its snake; display raises it.
            hold = -.13 if side == 'l' else 0
            pose[upper.name] = base.world_rot(upper, base.X, swing + hold - .20 * display)
            pose[lower.name] = base.world_rot(lower, base.X, hold - .18 * display)
        base.key_loc(arm, frame, 'root', arm.data.bones['root'].matrix_local.to_3x3().inverted() @ delta)
        base.key_pose(arm, frame, pose)
        bpy.context.view_layer.update()
        for side, offset in [('l', 0), ('r', .5)]:
            lateral = backward = lift = yaw = 0
            if name == 'walk':
                p = (phase + offset) % 1
                if p < DUTY:
                    relative = seconds * (p - DUTY / 2)
                else:
                    u = (p - DUTY) / (1 - DUTY)
                    relative = seconds * DUTY * (.5 - u * u * (3 - 2 * u))
                    lift = .055 * math.sin(math.pi * u)
                yaw = -SPEED / RADIUS * relative
                ankle = arm.data.bones[f'leg_{side}_foot'].head_local
                x, y = ankle.x - RADIUS, ankle.y
                lateral = RADIUS + math.cos(yaw) * x - math.sin(yaw) * y - ankle.x
                backward = math.sin(yaw) * x + math.cos(yaw) * y - ankle.y
            contact(arm, f'leg_{side}', frame, delta, lateral, backward, lift, yaw)
    base.finish_action(arm, action)
    for curve in base.action_fcurves(action):
        for key in curve.keyframe_points:
            key.interpolation = 'LINEAR'
    return action


def contact_qa(obj, arm, masks, actions):
    report = {}
    for name, seconds in [('idle', 4.), ('walk', WALK_SECONDS), ('special', 4.)]:
        arm.animation_data.action = actions[name]
        plants, minimum, maximum, drift = {}, 1e9, -1e9, 0.
        for step in range(round(seconds * FPS * 2) + 1):
            t = step / (FPS * 2)
            frame = min(t, seconds) * FPS
            bpy.context.scene.frame_set(int(frame), subframe=frame - int(frame))
            evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            points = np.array([list(v.co) for v in mesh.vertices])
            assert np.isfinite(points).all()
            evaluated.to_mesh_clear()
            for side, offset in [('l', 0), ('r', .5)]:
                sole = points[masks['soles'][side]].copy()
                if name == 'walk':
                    raw = t / seconds + offset
                    if not .025 < raw % 1 < DUTY - .025:
                        continue
                    theta = math.pi / 2 - SPEED / RADIUS * t
                    phi = math.pi - theta
                    rot = np.array([[math.cos(phi), -math.sin(phi), 0], [math.sin(phi), math.cos(phi), 0], [0, 0, 1]])
                    sole = sole @ rot.T + np.array([RADIUS * math.cos(theta), -RADIUS * math.sin(theta), 0])
                    key = (side, math.floor(raw))
                else:
                    key = (side, 0)
                minimum = min(minimum, float(sole[:, 2].min()))
                maximum = max(maximum, float(sole[:, 2].max()))
                if key not in plants:
                    plants[key] = sole.copy()
                drift = max(drift, float(np.linalg.norm(sole - plants[key], axis=1).max()))
        report[name] = dict(minHeight=minimum, maxHeight=maximum, maxStanceDrift=drift,
                            soleVertices={s: len(v) for s, v in masks['soles'].items()})
        assert minimum > -.002 and maximum < .006 and drift < .0015, report[name]
    arm.animation_data.action = None
    return report


def render_preview(path):
    from turnaround import setup_render
    camera = setup_render(768)
    target = Vector((0, 0, HEIGHT * .5))
    camera.location = target + Vector((2.5, -3.5, 1.1))
    camera.rotation_euler = (target - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.ortho_scale = HEIGHT * 1.2
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(path)
    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--preview', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    source, output = args.source.resolve(), args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    obj = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    points = [v.co.copy() for v in obj.data.vertices]
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    origin = Vector(((low.x + high.x) / 2, (low.y + high.y) / 2, low.z))
    scale = HEIGHT / (high.z - low.z)
    for v in obj.data.vertices:
        v.co = (v.co - origin) * scale
    obj.data.update()
    obj.name = 'qiangliang_native_body'
    obj.select_set(False)
    arm = make_rig()
    masks = skin(obj, arm)
    bpy.context.scene.render.fps = FPS
    actions = {name: animate(arm, name, seconds) for name, seconds in [('idle', 4.), ('walk', WALK_SECONDS), ('special', 4.)]}
    support = contact_qa(obj, arm, masks, actions)
    bpy.context.scene.frame_set(0)
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    arm.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(output), export_format='GLB', use_selection=True,
                             export_animations=True, export_animation_mode='NLA_TRACKS',
                             export_skins=True, export_def_bones=False, export_extras=True)
    report = dict(source=str(source), sourceSha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  bones=len(arm.data.bones), clips=list(actions), actualDeformedSoleQA=support,
                  runtime=dict(radius=RADIUS, speed=SPEED, walkSeconds=WALK_SECONDS, duty=DUTY),
                  outputSha256=hashlib.sha256(output.read_bytes()).hexdigest())
    output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print('QIANGliANG_NATIVE_RIG ' + json.dumps(report), flush=True)
    if args.preview:
        render_preview(args.preview.resolve())


if __name__ == '__main__':
    main()
