"""Reuse the verified Dangkang high pig as Bingfeng's black, two-ended body.

Sources: https://zh.wikisource.org/wiki/山海經/海外西經
         https://shanhaijing.5000yan.com/7-14.html
The source gives pig form, a head at each end, and black coloration. Tusks,
four legs, precise proportions and lack of a tail are explicitly inferred.
Input: existing normalized Dangkang HIGH body, +Z up, front towards -Y.
"""
import argparse
import math
from pathlib import Path
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render


def prepare(obj):
    # Charcoal fur keeps the source's dark features and fine skin texture.
    base = obj.data.materials[0]
    base.name = 'bingfeng_body'
    shader = base.node_tree.nodes['Principled BSDF']
    image = shader.inputs['Base Color'].links[0].from_node.image.copy()
    shader.inputs['Base Color'].links[0].from_node.image = image
    pixels = np.empty(image.size[0] * image.size[1] * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    rgba = pixels.reshape(-1, 4)
    luminance = rgba[:, :3] @ np.array([.2126, .7152, .0722])
    # Ink wash receives this atlas in linear space; preserve midtone charcoal
    # above its solid-ink threshold so the black body retains readable volume.
    charcoal = .19 + .22 * luminance
    rgba[:, :3] = charcoal[:, None] * np.array([.96, .98, 1.0])
    image.pixels.foreach_set(pixels)
    image.update()
    image.pack()
    shader.inputs['Roughness'].default_value = .9

    # Delete only the central dangling tail, leaving both lateral hind legs.
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    tail = [v for v in bm.verts if v.co.y > .458 and v.co.z < .44]
    print('BINGFENG removed tail vertices', len(tail))
    bmesh.ops.delete(bm, geom=tail, context='VERTS')
    bm.to_mesh(obj.data)
    bm.free()

    front = base.copy()
    front.name = 'bingfeng_front_fur'
    obj.data.materials.append(front)
    for face in obj.data.polygons:
        if face.center.y < -.17 and face.center.z > .27:
            face.material_index = 1

    # A genuine high-polygon duplicate of the pig's head, rotated rather than
    # negatively scaled. Its open neck extends deep into the rump, never floats.
    rear = obj.copy()
    rear.data = obj.data.copy()
    rear.name = 'bingfeng_rear_head'
    bpy.context.scene.collection.objects.link(rear)
    bm = bmesh.new()
    bm.from_mesh(rear.data)
    remove = [v for v in bm.verts if v.co.y > -.17 or v.co.z < .27]
    bmesh.ops.delete(bm, geom=remove, context='VERTS')
    bm.to_mesh(rear.data)
    bm.free()
    for i, material in enumerate(list(rear.data.materials)):
        copy = material.copy()
        copy.name = 'bingfeng_rear_fur'
        rear.data.materials[i] = copy
    rear.matrix_world = Matrix.Translation(Vector((0, .105, 0))) @ Matrix.Rotation(math.pi, 4, 'Z')
    bpy.ops.object.select_all(action='DESELECT')
    rear.select_set(True)
    bpy.context.view_layer.objects.active = rear
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.join()
    obj.name = 'bingfeng_two_heads'
    obj.data.update()
    print('BINGFENG high mesh vertices', len(obj.data.vertices), 'polygons', len(obj.data.polygons))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('views')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    obj = load(args.input)
    prepare(obj)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB', use_selection=True, export_animations=False)
    Path(args.views).mkdir(parents=True, exist_ok=True)
    camera = setup_render(1024)
    render_views(obj, camera, args.views)
    # Both hind feet and the missing native tail must be visible from the other side.
    points = [v.co for v in obj.data.vertices]
    center = Vector((0, .05, max(p.z for p in points) / 2))
    opposite = camera.copy()
    opposite.data = camera.data.copy()
    bpy.context.scene.collection.objects.link(opposite)
    opposite.location = center + Vector((-3, 0, 0))
    opposite.rotation_euler = (center - opposite.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.camera = opposite
    bpy.context.view_layer.update()
    bpy.context.scene.render.filepath = str(Path(args.views) / 'view_opposite.png')
    bpy.ops.render.render(write_still=True)


if __name__ == '__main__':
    main()
