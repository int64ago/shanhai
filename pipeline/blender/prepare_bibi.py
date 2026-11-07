"""Inspect/prepare the Bibi fox torso before Stage 2: straighten the yawed head
onto the spine and level the hindquarters. The native tail is kept intact."""
import argparse
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render, smoothstep

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('input')
p.add_argument('output')
p.add_argument('views')
p.add_argument('--yaw', type=float, default=-42.0, help='Head correction in degrees')
p.add_argument('--pivot-y', type=float, default=-0.30, help='Skull/neck junction on the spine')
p.add_argument('--raise', dest='raise_', type=float, default=0.08, help='Rump lift in metres')
p.add_argument('--view', choices=['34', 'side', 'front', 'back'])
a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])

# Measured on the normalized Stage 1 mesh (feet z=0, length 1).
HEAD_Y = (-0.32, -0.18)   # full correction ahead of the skull, none at the withers
HEAD_Z = (0.56, 0.72)     # the chest and throat below the jaw must not twist
FRONT_Y, BACK_Y, HIP_Z = -0.284, 0.19, 0.459

obj = load(a.input)
bm = bmesh.new()
bm.from_mesh(obj.data)
bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)

angle = math.radians(a.yaw)
pivot = Vector((0, a.pivot_y, 0))
for v in bm.verts:
    w = (1 - smoothstep(*HEAD_Y, v.co.y)) * smoothstep(*HEAD_Z, v.co.z)
    if w > 0:
        base = Vector((pivot.x, pivot.y, v.co.z))
        v.co = base + Matrix.Rotation(angle * w, 3, 'Z') @ (v.co - base)

for v in bm.verts:
    # Below the hip stretch proportionally so the feet stay on the ground.
    w = smoothstep(FRONT_Y, BACK_Y, v.co.y) * a.raise_
    if v.co.z < HIP_Z:
        v.co.z *= 1 + w / HIP_Z
    else:
        v.co.z += w

snout = min(bm.verts, key=lambda v: v.co.y).co
print('SNOUT', tuple(round(c, 3) for c in snout))
bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
bm.to_mesh(obj.data)
bm.free()
obj.data.update()

Path(a.output).parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
Path(a.views).mkdir(parents=True, exist_ok=True)
render_views(obj, setup_render(1024), a.views, only_view=a.view)
