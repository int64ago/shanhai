"""Offline Fengxi wild-boar adaptation of the verified Lili Extreme-High master.

Input: normalize.py --length 1.6 --max-texture 2048 output. The source body
retains all 49,940 triangles. Shoulder mass, long snout, dark coat, two tusks
and bristle ridge are artistic inferences, not details stated in Hai Nei Jing.
Usage: blender -b --python pipeline/blender/prepare_fengxi.py -- in.glb out.glb concept/fengxi
"""
import argparse
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render, smoothstep


def tusk(side, root):
    """Tapered outward/upward canine, embedded at the mouth corner."""
    points = [Vector((side * (root.x + 0.13 * math.sin(t * math.pi / 2)),
                      root.y - 0.11 * t, root.z + 0.30 * t * t)) for t in [i / 18 for i in range(19)]]
    vertices, faces = [], []
    for i, point in enumerate(points):
        t = i / 18
        radius = 0.044 * (1 - t) ** 0.8 + 0.001
        tangent = (points[min(i + 1, 18)] - points[max(i - 1, 0)]).normalized()
        u = tangent.cross(Vector((0, 1, 0))).normalized()
        v = tangent.cross(u).normalized()
        for j in range(12):
            a = j / 12 * math.tau
            vertices.append(point + radius * (math.cos(a) * u + math.sin(a) * v))
    for i in range(18):
        for j in range(12):
            a, b = i * 12 + j, i * 12 + (j + 1) % 12
            faces.append((a, b, b + 12, a + 12))
    faces.extend([tuple(reversed(range(12))), tuple(18 * 12 + j for j in range(12))])
    mesh = bpy.data.meshes.new(f'Fengxi_Tusk_{side}')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.collection.objects.link(obj)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    return obj


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Roughness'].default_value = 0.8
    return mat


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('input', 'output', 'views'):
        parser.add_argument(arg)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    obj = load(args.input)
    obj.name = 'Fengxi_Boar'
    # High shoulders, leaner rump and a longer low snout; ground points remain z=0.
    for vertex in obj.data.vertices:
        p = vertex.co
        shoulder = math.exp(-((p.y + 0.14) / 0.34) ** 2)
        upper = smoothstep(0.43, 0.85, p.z)
        muzzle = 1 - smoothstep(-0.67, -0.40, p.y)
        rear = smoothstep(0.12, 0.60, p.y)
        p.x *= 1.10 + 0.15 * shoulder - 0.12 * rear
        p.y -= 0.115 * muzzle
        p.z += 0.14 * shoulder * upper - 0.05 * rear * upper
        p *= 1.20
    obj.data.update()
    images = {link.from_node.image for mat in obj.data.materials if mat.use_nodes
              for node in mat.node_tree.nodes if node.type == 'BSDF_PRINCIPLED'
              for link in node.inputs['Base Color'].links if link.from_node.type == 'TEX_IMAGE'}
    for image in images:
        pixels = np.empty(image.size[0] * image.size[1] * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        rgba = pixels.reshape(-1, 4)
        lum = rgba[:, :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        rgba[:, :3] = lum[:, None] * np.array([0.46, 0.37, 0.28], dtype=np.float32)
        image.pixels.foreach_set(rgba.ravel())
        image.update()
        image.pack()
    teeth_mat = material('Fengxi_Tusks_Inferred', (0.72, 0.62, 0.44))
    mane_mat = material('Fengxi_Bristles_Inferred', (0.07, 0.052, 0.037))
    additions = []
    # Locate mouth corners from the actual high mesh rather than a floating mount.
    for side in (-1, 1):
        band = [v.co for v in obj.data.vertices if -0.81 < v.co.y < -0.72 and 0.53 < v.co.z < 0.73 and v.co.x * side > 0]
        root = max(band, key=lambda p: abs(p.x)).copy()
        root.x = abs(root.x) - 0.018
        tooth = tusk(side, root)
        tooth.data.materials.append(teeth_mat)
        additions.append(tooth)
    # Irregular fine bristles, rooted behind the ears; no continuous fin or horn.
    for i in range(15):
        y = -0.22 + i * 0.055
        top = max(v.co.z for v in obj.data.vertices if abs(v.co.y - y) < 0.035 and abs(v.co.x) < 0.07)
        for j in range(3):
            length = 0.055 + 0.025 * (0.5 + 0.5 * math.sin(i * 2.7 + j * 1.8))
            bpy.ops.mesh.primitive_cone_add(vertices=5, radius1=0.009, radius2=0.0005, depth=length,
                                           location=((j - 1) * 0.018, y + j * 0.008, top + 0.012),
                                           rotation=(-0.65, 0.12 * math.sin(i + j), 0))
            tuft = bpy.context.object
            tuft.name = f'Fengxi_Bristle_{i:02d}_{j}'
            tuft.data.materials.append(mane_mat)
            additions.append(tuft)
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    for part in additions:
        part.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.join()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB', use_selection=True, export_animations=False)
    obj.data.calc_loop_triangles()
    print('FENGXI triangles', len(obj.data.loop_triangles), 'two tusks, fifteen bristle tufts; source body unsimplified')
    Path(args.views).mkdir(parents=True, exist_ok=True)
    render_views(obj, setup_render(1024), args.views)


if __name__ == '__main__':
    main()
