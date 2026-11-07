"""Straighten Tianma's generated canine head and make its white muzzle black.

Input: normalized Stage 1 dog; its narrow native tail is removed and capped.
Output: corrected textured reference plus the four Stage 2 concept views.
Measurements are for this 1 m normalized Stage 1 mesh, not a general dog template.
"""
import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render, smoothstep


def blacken_head(obj):
    material = obj.data.materials[0]
    shader = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    image = shader.inputs['Base Color'].links[0].from_node.image
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    rgba = pixels.reshape(height, width, 4)
    mask = np.zeros((height, width), dtype=bool)
    obj.data.calc_loop_triangles()
    uv = obj.data.uv_layers.active.data
    for triangle in obj.data.loop_triangles:
        points = [obj.data.vertices[i].co for i in triangle.vertices]
        if not all(p.y < -0.26 and (p.z > 0.84 or (p.z > 0.79 and p.y < -0.39)) for p in points):
            continue
        coords = np.array([(uv[i].uv.x * (width - 1), uv[i].uv.y * (height - 1)) for i in triangle.loops])
        lo = np.maximum(np.floor(coords.min(axis=0)).astype(int) - 1, 0)
        hi = np.minimum(np.ceil(coords.max(axis=0)).astype(int) + 1, [width - 1, height - 1])
        xx, yy = np.meshgrid(np.arange(lo[0], hi[0] + 1), np.arange(lo[1], hi[1] + 1))
        a, b, c = coords
        denominator = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(denominator) < 1e-8:
            continue
        u = ((b[1] - c[1]) * (xx - c[0]) + (c[0] - b[0]) * (yy - c[1])) / denominator
        v = ((c[1] - a[1]) * (xx - c[0]) + (a[0] - c[0]) * (yy - c[1])) / denominator
        mask[lo[1]:hi[1] + 1, lo[0]:hi[0] + 1] |= (u >= -0.02) & (v >= -0.02) & (u + v <= 1.02)
    # Cover texture filtering at UV seams without painting the white neck.
    for _ in range(3):
        mask = np.logical_or.reduce([np.roll(np.roll(mask, x, axis=1), y, axis=0) for x in (-1, 0, 1) for y in (-1, 0, 1)])
    # Preserve the already black face. Only the generated white muzzle is remapped.
    light = mask & (rgba[:, :, :3].max(axis=2) > 0.18)
    luminance = rgba[:, :, :3].mean(axis=2)
    tone = 0.035 + 0.02 * luminance[light]
    rgba[light, :3] = tone[:, None]
    image.pixels.foreach_set(rgba.ravel())
    image.update()
    image.file_format = 'PNG'
    image.pack()
    print('TIANMA_MUZZLE blackened texture pixels', int(light.sum()))


def remove_tail(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    # glTF splits coincident vertices at UV seams; weld before making a closed cut.
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-3)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    cap = bpy.data.materials.new('tail_cap_white')
    cap.diffuse_color = (0.86, 0.86, 0.86, 1)
    cap.use_nodes = True
    cap.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = cap.diffuse_color
    cap.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 1
    obj.data.materials.append(cap)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0.51, 0.48))
    cutter = bpy.context.object
    cutter.dimensions = (0.145, 0.40, 0.48)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    cutter.data.materials.append(obj.data.materials[0])
    cutter.data.materials.append(cap)
    for face in cutter.data.polygons:
        face.material_index = 1
    bpy.context.view_layer.objects.active = obj
    modifier = obj.modifiers.new('native_tail_cut', 'BOOLEAN')
    modifier.operation = 'DIFFERENCE'
    modifier.solver = 'EXACT'
    modifier.object = cutter
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(cutter, do_unlink=True)
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    print('TIANMA_TAIL closed boolean cut')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('views')
    parser.add_argument('--yaw', type=float, default=-49)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    obj = load(args.input)
    remove_tail(obj)
    blacken_head(obj)
    for vertex in obj.data.vertices:
        p = vertex.co
        weight = smoothstep(0.69, 0.81, p.z) * (1 - smoothstep(-0.25, -0.12, p.y))
        anchor = Vector((0, -0.30, p.z))
        vertex.co = anchor + Matrix.Rotation(math.radians(args.yaw) * weight, 3, 'Z') @ (p - anchor)
        vertex.co.x += 0.055 * weight
    obj.data.update()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB', use_selection=True, export_animations=False)
    Path(args.views).mkdir(parents=True, exist_ok=True)
    render_views(obj, setup_render(1024), args.views)


if __name__ == '__main__':
    main()
