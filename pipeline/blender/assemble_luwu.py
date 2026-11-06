"""Fit the separately generated human head into Luwu's headless tiger torso.

Inputs: normalized .85 m torso and .27 m human-head masters. Rig the result
with rig_quadruped.py --rigid-part human_head_:head to preserve facial shape.
"""
import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('body')
p.add_argument('head')
p.add_argument('output')
p.add_argument('views')
p.add_argument('--head-scale', type=float, default=1.25)
p.add_argument('--head-inset', type=float, default=.08)
p.add_argument('--head-height', type=float, default=.58)
p.add_argument('--pitch', type=float, default=10)
p.add_argument('--view', choices=['34', 'side', 'front', 'back'])
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
bpy.ops.wm.read_factory_settings(use_empty=True)


def load(path, role):
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o not in before and o.type == 'MESH']
    if not meshes:
        raise RuntimeError('Missing mesh: ' + path)
    bpy.ops.object.select_all(action='DESELECT')
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.name = role
    for slot in obj.material_slots:
        if slot.material:
            slot.material = slot.material.copy()
            slot.material.name = role + '_' + slot.material.name
    return obj


body = load(a.body, 'torso')
points = [v.co for v in body.data.vertices]
height = max(v.z for v in points)
front = min(v.y for v in points if v.z > height * .45)
head = load(a.head, 'human_head')
head.data.transform(Matrix.Scale(a.head_scale, 4))
head.data.transform(Matrix.Rotation(math.radians(a.pitch), 4, 'X'))
head.data.transform(Matrix.Translation((0, front + a.head_inset, height * a.head_height)))
print('HEAD_FIT', 'front', front, 'body_height', height, 'head_inset', a.head_inset, 'head_height', a.head_height, 'scale', a.head_scale)
bpy.ops.object.select_all(action='DESELECT')
body.select_set(True)
head.select_set(True)
bpy.context.view_layer.objects.active = body
bpy.ops.object.join()
body.name = 'body'
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import render_views, setup_render
Path(a.views).mkdir(parents=True, exist_ok=True)
render_views(body, setup_render(1024), a.views, only_view=a.view)
