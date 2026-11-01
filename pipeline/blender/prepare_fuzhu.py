"""Replace the draft's forked antlers with four independent horns; render reference views."""
import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input')
    p.add_argument('output')
    p.add_argument('views')
    p.add_argument('--inspect', action='store_true')
    p.add_argument('--view', choices=['34', 'side', 'front', 'back'])
    a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    obj = load(a.input)
    for lo, hi in [(0.64, 0.70), (0.70, 0.74), (0.74, 0.78), (0.78, 0.84)]:
        pts = [v.co for v in obj.data.vertices if lo < v.co.z < hi]
        if pts:
            print('SLICE', lo, hi, 'x', min(v.x for v in pts), max(v.x for v in pts),
                  'y', min(v.y for v in pts), max(v.y for v in pts))
    if not a.inspect:
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
        # Only the antlers occupy this upper region; ears and skull remain intact.
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z > 0.755], context='VERTS')
        holes = [e for e in bm.edges if e.is_boundary and all(v.co.z > 0.73 for v in e.verts)]
        bmesh.ops.holes_fill(bm, edges=holes, sides=0)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
        bm.free()
        ivory = bpy.data.materials.new('Fuzhu ivory')
        ivory.diffuse_color = (0.87, 0.85, 0.64, 1)
        jade = bpy.data.materials.new('Fuzhu pale jade tips')
        jade.diffuse_color = (0.52, 0.73, 0.66, 1)
        for side in [-1, 1]:
            for rear in [False, True]:
                root = Vector((side * (0.058 if rear else 0.045), -0.287 if rear else -0.351, 0.735))
                vertices, faces = [], []
                rings, sides = 15, 10
                for j in range(rings + 1):
                    t = j / rings
                    center = root + Vector((side * (0.095 * t + 0.018 * math.sin(t * math.pi)),
                                             (0.045 if rear else -0.025) * t,
                                             (0.29 if rear else 0.25) * t))
                    r = 0.018 * (1 - t) ** 0.7 + 0.0005
                    for k in range(sides):
                        theta = k * math.tau / sides
                        vertices.append(tuple(center + Vector((r * math.cos(theta), r * math.sin(theta), 0))))
                for j in range(rings):
                    for k in range(sides):
                        n = (k + 1) % sides
                        faces.append((j*sides+k, j*sides+n, (j+1)*sides+n, (j+1)*sides+k))
                faces.extend([tuple(reversed(range(sides))), tuple(rings*sides+k for k in range(sides))])
                mesh = bpy.data.meshes.new('independent horn')
                mesh.from_pydata(vertices, [], faces)
                mesh.update()
                mesh.materials.append(ivory)
                mesh.materials.append(jade)
                horn = bpy.data.objects.new(f'horn_{side}_{rear}', mesh)
                bpy.context.scene.collection.objects.link(horn)
                for polygon in mesh.polygons:
                    polygon.use_smooth = True
                    polygon.material_index = 1 if polygon.center.z > root.z + (0.24 if rear else 0.205) else 0
        bpy.ops.object.select_all(action='DESELECT')
        for o in bpy.context.scene.objects:
            if o.type == 'MESH':
                o.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.join()
        Path(a.output).parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
    Path(a.views).mkdir(parents=True, exist_ok=True)
    render_views(obj, setup_render(1024), a.views, only_view=a.view)


if __name__ == '__main__':
    main()
