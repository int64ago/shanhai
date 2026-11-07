"""Fengxi's heavy four-beat walk and planted tusk display (offline only).

Reuses the project's heat/proxy/distance weighting and analytic leg solver.
Tusks are rigid head geometry; bristles blend with the local back skin.
Usage: blender -b --python pipeline/blender/rig_fengxi.py -- in.glb out.glb
"""
import math
import sys
from pathlib import Path

import bpy
from mathutils.kdtree import KDTree

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_quadruped as rig
from rig_quadruped import FPS, X, Z, finish_action, key_pose, new_action, world_rot
from rig_tongtong import LEGS, bind_hooves, idle, key_legs, stitch_seams

WALK_SECONDS = 2.0
DUTY = 0.68
SPEED = 0.27


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
                offset, lift = span / 2 - span * s, 0.075 * math.sin(q * math.pi) ** 2
            offsets[leg] = (offset, lift)
        key_legs(arm, frame, offsets, lm['height'] * (0.048 + 0.003 * math.cos(t * math.tau * 2)))
        key_pose(arm, frame, {'neck': world_rot(arm.pose.bones['neck'], X, 0.035 + 0.012 * math.sin(t * math.tau * 2))})
    finish_action(arm, action)
    for curve in rig.action_fcurves(action):
        for point in curve.keyframe_points:
            point.interpolation = 'LINEAR'


def alert(arm, lm):
    action = new_action(arm, 'alert')
    n = round(FPS * 4.8)
    for frame in range(0, n + 1, 2):
        t = frame / n
        envelope = math.sin(t * math.pi) ** 2
        key_legs(arm, frame, {}, lm['height'] * (0.035 + 0.022 * envelope))
        key_pose(arm, frame, {
            'neck': world_rot(arm.pose.bones['neck'], X, 0.14 * envelope),
            'head': world_rot(arm.pose.bones['head'], Z, 0.12 * math.sin(t * math.tau) * envelope)
                    @ world_rot(arm.pose.bones['head'], X, -0.08 * envelope),
        })
    finish_action(arm, action)


def bind_features(obj):
    tusk_materials = {i for i, mat in enumerate(obj.data.materials) if mat.name.startswith('Fengxi_Tusks')}
    mane_materials = {i for i, mat in enumerate(obj.data.materials) if mat.name.startswith('Fengxi_Bristles')}
    tusk_vertices = {i for face in obj.data.polygons if face.material_index in tusk_materials for i in face.vertices}
    mane_vertices = {i for face in obj.data.polygons if face.material_index in mane_materials for i in face.vertices}
    body = [v for v in obj.data.vertices if v.index not in tusk_vertices | mane_vertices
            and any(g.weight > 1e-3 for g in v.groups)]
    tree = KDTree(len(body))
    for vertex in body:
        tree.insert(vertex.co, vertex.index)
    tree.balance()
    # Disconnected fine bristles inherit adjacent body skin instead of unreliable
    # heat diffusion. Repair every remaining zero-weight vertex, even below 1%.
    repaired = 0
    for vertex in obj.data.vertices:
        if vertex.index in tusk_vertices:
            continue
        if vertex.index not in mane_vertices and any(g.weight > 1e-3 for g in vertex.groups):
            continue
        _, nearest, _ = tree.find(vertex.co)
        weights = [(g.group, g.weight) for g in obj.data.vertices[nearest].groups]
        for group in obj.vertex_groups:
            group.remove([vertex.index])
        for index, weight in weights:
            obj.vertex_groups[index].add([vertex.index], weight, 'REPLACE')
        repaired += 1
    for group in obj.vertex_groups:
        group.remove(list(tusk_vertices))
    obj.vertex_groups['head'].add(list(tusk_vertices), 1.0, 'REPLACE')
    if rig.unweighted_count(obj):
        raise RuntimeError('Fengxi still has unweighted vertices')
    print('FENGXI rigid tusk vertices', len(tusk_vertices), 'surface weight transfers', repaired, 'unweighted=0')


def main():
    args = rig.parse_args()
    obj = rig.load(args.input)
    bpy.context.scene.render.fps = FPS
    lm = rig.landmarks(obj)
    arm = rig.build_armature(lm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    for leg in LEGS:
        upper, lower = (arm.data.edit_bones[f'{leg}_{part}'] for part in ('upper', 'lower'))
        knee = upper.tail.copy()
        knee.y += (0.11 if leg.startswith('front') else -0.11) * lm['height']
        upper.tail = knee
        lower.head = knee
    bpy.ops.object.mode_set(mode='OBJECT')
    rig.skin(obj, arm)
    bind_hooves(obj, lm)
    bind_features(obj)
    stitch_seams(obj)
    idle(arm, lm)
    walk(arm, lm)
    alert(arm, lm)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB', export_animations=True,
                              export_animation_mode='NLA_TRACKS', export_skins=True, export_def_bones=False)
    obj.data.calc_loop_triangles()
    print('FENGXI EXPORTED', args.output, 'triangles', len(obj.data.loop_triangles), 'bones', len(arm.data.bones))


if __name__ == '__main__':
    main()
