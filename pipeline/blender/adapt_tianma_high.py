"""Adapt the existing Chenghuang high canine master into Tianma's white dog.

Source is chenghuang-body-max/base_high_pbr.glb (49,988 triangles), normalized
with normalize.py --length 1.0. This is offline high-model reuse, not a new
Rodin submission. Stage 1 Tianma dog views guide the proportions: slimmer
cheeks, broader canine muzzle, longer-looking neck, and a lean white torso.
"""
import argparse
import sys
from pathlib import Path

import bpy
import numpy as np

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render, smoothstep


def black_head(obj):
    shader = next(n for n in obj.data.materials[0].node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    image = shader.inputs['Base Color'].links[0].from_node.image
    width, height = image.size
    pixels = np.empty(width * height * 4, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    rgba = pixels.reshape(height, width, 4)
    mask = np.zeros((height, width), dtype=bool)
    uv = obj.data.uv_layers.active.data
    obj.data.calc_loop_triangles()
    for triangle in obj.data.loop_triangles:
        points = [obj.data.vertices[i].co for i in triangle.vertices]
        if not all((p.z > 0.875 and p.y < 0.025) or (p.z > 0.755 and p.y < -0.25) for p in points):
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
    for _ in range(4):
        mask = np.logical_or.reduce([np.roll(np.roll(mask, x, axis=1), y, axis=0) for x in (-1, 0, 1) for y in (-1, 0, 1)])
    # Retain fur shading and existing dark nose/eyes, with no pale muzzle or ears.
    rgba[mask, :3] *= 0.035
    image.pixels.foreach_set(rgba.ravel())
    image.update()
    image.file_format = 'PNG'
    image.pack()
    print('TIANMA_HIGH black-head pixels', int(mask.sum()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('views')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    obj = load(args.input)
    black_head(obj)
    for vertex in obj.data.vertices:
        p = vertex.co
        head = smoothstep(0.72, 0.89, p.z) * (1 - smoothstep(-0.17, 0.02, p.y))
        muzzle = 1 - smoothstep(-0.40, -0.29, p.y)
        # Reduce the fox's cheek ruff and widen its pointed muzzle into a dog jaw.
        p.x *= (1 - 0.30 * head) * (1 + 0.42 * head * muzzle)
        p.y = p.y * 0.92 - 0.07 - 0.045 * head * muzzle
        p.z = p.z * 0.92 + 0.03 * head
    obj.data.update()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB', use_selection=True, export_animations=False)
    Path(args.views).mkdir(parents=True, exist_ok=True)
    render_views(obj, setup_render(1024), args.views)


if __name__ == '__main__':
    main()
