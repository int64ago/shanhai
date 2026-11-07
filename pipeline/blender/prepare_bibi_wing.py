"""Recolour the verified Qiongqi wing master for Bibi without a new Rodin job.

The classic records only 「有翼」, so the geometry is reused as is. Mapping the
base colour's luminance through a warm ramp keeps every feather's shading while
replacing Qiongqi's charcoal with ochre and ivory.

  blender --background --python pipeline/blender/prepare_bibi_wing.py -- \
      raw/_build/bibi/wing_norm.glb raw/_build/bibi/wing_recolor.glb raw/_build/bibi/wing-views
"""
import argparse
import sys
from pathlib import Path

import bpy
import numpy as np

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render

STOPS = np.array([0.0, 0.3, 0.65, 1.0])
RAMP = np.array([
    (0.20, 0.14, 0.10),  # feather gaps stay as ink
    (0.58, 0.40, 0.25),  # ochre shadow
    (0.84, 0.70, 0.52),  # warm body of the feather
    (0.97, 0.93, 0.85),  # ivory edges
])

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('input')
p.add_argument('output')
p.add_argument('views')
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])

obj = load(a.input)
material = obj.data.materials[0]
principled = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
links = principled.inputs['Base Color'].links
if not links or links[0].from_node.type != 'TEX_IMAGE':
    raise RuntimeError('Wing base colour is not an image texture')
image = links[0].from_node.image

pixels = np.empty(image.size[0] * image.size[1] * 4, dtype=np.float32)
image.pixels.foreach_get(pixels)
rgba = pixels.reshape(-1, 4)
lum = rgba[:, :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
low, high = np.percentile(lum, [2, 99])
print('LUM', round(float(low), 3), round(float(high), 3))
tone = np.clip((lum - low) / max(high - low, 1e-4), 0, 1) ** 0.6
for channel in range(3):
    rgba[:, channel] = np.interp(tone, STOPS, RAMP[:, channel])
image.pixels.foreach_set(rgba.ravel())
image.update()
image.file_format = 'PNG'
image.pack()

Path(a.output).parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
print('EXPORTED', a.output)
Path(a.views).mkdir(parents=True, exist_ok=True)
render_views(obj, setup_render(1024), a.views)
