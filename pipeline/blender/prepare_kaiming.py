"""Broaden the verified headless tiger master for Kaiming's nine short necks.

Reuse the two-stage Rodin Luwu torso; no new generation is needed. Input is
raw/_build/luwu/body_high_norm.glb, before the separate human head is assembled.
Export with rig_quadruped.py --headless; runtime supplies exactly nine heads.
"""
import argparse
import sys
from pathlib import Path

import bpy

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('input')
p.add_argument('output')
p.add_argument('views')
p.add_argument('--view', choices=['34', 'side', 'front', 'back'])
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
obj = load(a.input)
# Positive offline scales preserve winding; Blender applies their normal matrix.
obj.scale = (1.8, 1.1, 1.1)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
obj.name = 'kaiming_torso'
print('KAIMING_DIMENSIONS', tuple(round(v, 6) for v in obj.dimensions))
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
Path(a.views).mkdir(parents=True, exist_ok=True)
render_views(obj, setup_render(1024), a.views, only_view=a.view)
