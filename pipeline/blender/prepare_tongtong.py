"""Offline Tongtong adaptation of the verified Lili Extreme-High pig master.

Run normalize.py --length 1.6 first. Retains the ~50K triangle pig anatomy,
cloven hooves and native single tail; no pearl is added to the exterior.
Usage: blender -b --python pipeline/blender/prepare_tongtong.py -- in.glb out.glb concept/tongtong
"""
import argparse
import sys
from pathlib import Path

import bpy
import numpy as np

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render, smoothstep


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('views')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    obj = load(args.input)
    obj.name = 'Tongtong_Pig'
    # A broad, low domestic-pig silhouette distinguishes it from Lili's lean
    # ochre piglet and Dangkang's tall tusks. All edits are baked offline.
    for vertex in obj.data.vertices:
        p = vertex.co
        torso = smoothstep(-0.52, -0.18, p.y) * (1 - smoothstep(0.57, 0.76, p.y))
        muzzle = 1 - smoothstep(-0.70, -0.47, p.y)
        ear = smoothstep(0.77, 0.94, p.z) * (1 - smoothstep(-0.30, -0.05, p.y))
        p.x *= 1.10 + 0.13 * torso + 0.10 * muzzle
        p.y = p.y * 0.96 + 0.05 * muzzle
        p.z *= 0.94
        p.z -= 0.055 * ear
    obj.data.update()
    # Muted stone-grey hide, with the original bristles, nostrils, eyes and
    # hoof detail preserved. Palette is explicitly an artistic inference.
    # Access the base-color pixels directly; packed GLB images load lazily and
    # report has_data=False until their pixel buffer has first been requested.
    base_images = {
        link.from_node.image for mat in obj.data.materials if mat.use_nodes
        for node in mat.node_tree.nodes if node.type == 'BSDF_PRINCIPLED'
        for link in node.inputs['Base Color'].links if link.from_node.type == 'TEX_IMAGE'
    }
    for image in base_images:
        pixels = np.empty(image.size[0] * image.size[1] * 4, dtype=np.float32)
        image.pixels.foreach_get(pixels)
        rgba = pixels.reshape(-1, 4)
        luminance = rgba[:, :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        rgba[:, :3] = luminance[:, None] * np.array([0.69, 0.78, 0.81], dtype=np.float32)
        image.pixels.foreach_set(rgba.ravel())
        image.update()
        image.pack()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB', use_selection=True, export_animations=False)
    Path(args.views).mkdir(parents=True, exist_ok=True)
    render_views(obj, setup_render(1024), args.views)


if __name__ == '__main__':
    main()
