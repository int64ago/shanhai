"""Zhubieyu's two new generated masters: horizontal lung mantle and natural foot.
No substitute beast geometry. Affine corrections preserve authored normals and UV.
Run medium before HIGH turnarounds, then high before assembly.
"""
import argparse
import math
import os
import sys
import bpy
from mathutils import Matrix, Vector

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import turnaround


def render_views(obj, cam, directory):
    points = [v.co for v in obj.data.vertices]
    lo = Vector(tuple(min(v[i] for v in points) for i in range(3)))
    hi = Vector(tuple(max(v[i] for v in points) for i in range(3)))
    center = (lo + hi) / 2
    extent = max(hi - lo)
    for name, direction in [('34', (0.62, -0.72, 0.55)), ('side', (1, 0, 0)), ('front', (0, -1, 0)), ('back', (0, 1, 0))]:
        shot = cam.copy()
        shot.data = cam.data.copy()
        shot.data.ortho_scale = extent * 1.48
        bpy.context.scene.collection.objects.link(shot)
        location = center + Vector(direction) * extent * 3
        shot.matrix_world = Matrix.LocRotScale(location, (center - location).to_track_quat('-Z', 'Y'), Vector((1, 1, 1)))
        bpy.context.scene.camera = shot
        bpy.context.view_layer.update()
        bpy.context.scene.render.filepath = os.path.join(directory, 'view_' + name + '.png')
        bpy.ops.render.render(write_still=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--part', choices=['body', 'leg'], required=True)
    p.add_argument('--input', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--concept')
    p.add_argument('--high', action='store_true')
    a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    obj = turnaround.load(a.input)
    # Medium body arrives upright; HIGH is reconstructed from corrected views.
    if not a.high:
        if a.part == 'body':
            obj.data.transform(Matrix.Diagonal((0.85, 1.15, 0.85, 1)) @ Matrix.Rotation(math.pi / 2, 4, 'X'))
        else:
            obj.data.transform(Matrix.Diagonal((0.66, 0.66, 0.70, 1)) @ Matrix.Rotation(math.pi / 2, 4, 'Z'))
    points = [v.co for v in obj.data.vertices]
    lo = Vector(tuple(min(v[i] for v in points) for i in range(3)))
    hi = Vector(tuple(max(v[i] for v in points) for i in range(3)))
    obj.data.transform(Matrix.Translation(Vector((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z))))
    obj.name = 'zhubieyu_' + a.part
    obj.data.calc_loop_triangles()
    print('ZHUBIEYU', a.part, 'HIGH' if a.high else 'MEDIUM', 'TRIANGLES', len(obj.data.loop_triangles), 'EXTENT', tuple(hi - lo))
    os.makedirs(os.path.dirname(a.output), exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', export_animations=False)
    if a.concept:
        os.makedirs(a.concept, exist_ok=True)
        cam = turnaround.setup_render(1024)
        render_views(obj, cam, a.concept)


if __name__ == '__main__':
    main()
