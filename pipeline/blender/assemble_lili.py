"""Add Lili's four 距 (spurs) to the normalized Stage-2 body.

Each spur has its own material prefix so rig_quadruped.py can bind it rigidly:
  --rigid-part spur_front_l:front_l_lower  (and likewise for the other legs)
They sit on the shank above the ankle, so the lower-leg bone is the one that
keeps their roots on the skin; the foot bone would pivot them off it in the walk.

Usage:
  blender --background --factory-startup --python pipeline/blender/assemble_lili.py -- \
      raw/_build/lili/body_norm.glb raw/_build/lili/body_spurs.glb /tmp/lili-spur-views
"""
import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render

SPUR_Z = 0.1
SPUR_LENGTH = 0.07
SPUR_RADIUS = 0.018
ROOT_EMBED = 0.022
RINGS, SIDES = 14, 12
GRADIENT_SIZE = 64
HIDE = (0.62, 0.36, 0.17)
BONE = (0.87, 0.82, 0.68)
TIP = (0.2, 0.16, 0.12)


def find_leg_backs(obj):
    """Return the rear skin point of each shank at spur height."""
    vs = [v.co for v in obj.data.vertices]
    height = max(v.z for v in vs)
    low = [v for v in vs if v.z < height * 0.12]
    mid_y = (min(v.y for v in low) + max(v.y for v in low)) / 2
    backs = {}
    for fb in ('front', 'back'):
        for side in ('l', 'r'):
            foot = [v for v in low if (v.y < mid_y) == (fb == 'front') and (v.x > 0) == (side == 'l')]
            if not foot:
                raise RuntimeError(f'Missing {fb}_{side} foot')
            center = sum(foot, Vector()) / len(foot)
            shank = [v for v in vs if abs(v.z - SPUR_Z) < 0.012 and (v.y < mid_y) == (fb == 'front') and (v.x > 0) == (side == 'l')
                     and math.hypot(v.x - center.x, v.y - center.y) < 0.12]
            if not shank:
                raise RuntimeError(f'Missing {fb}_{side} shank')
            rear = max(shank, key=lambda v: v.y)
            # The rear ridge, not the slice midpoint: shanks are not centred in their slice.
            ridge = [v for v in shank if v.y > rear.y - 0.012]
            x = sum(v.x for v in ridge) / len(ridge)
            backs[f'{fb}_{side}'] = Vector((x, rear.y, SPUR_Z))
            print('LILI shank', fb, side, tuple(round(c, 3) for c in backs[f'{fb}_{side}']))
    return backs


def gradient_image():
    """Hide at the buried root, pale bone along the spur, ink at the tip (V runs root to tip)."""
    image = bpy.data.images.new('spur_gradient', 4, GRADIENT_SIZE)
    pixels = []
    for row in range(GRADIENT_SIZE):
        t = row / (GRADIENT_SIZE - 1)
        ink = max(0.0, (t - 0.55) / 0.45) ** 1.4
        bone = min(1.0, max(0.0, (t - 0.22) / 0.2))
        color = [HIDE[i] + (BONE[i] - HIDE[i]) * bone for i in range(3)]
        pixels += [*(color[i] + (TIP[i] - color[i]) * ink for i in range(3)), 1.0] * 4
    image.pixels.foreach_set(pixels)
    image.pack()
    return image


def spur_material(name, image):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    texture = nodes.new('ShaderNodeTexImage')
    texture.image = image
    shader = nodes['Principled BSDF']
    material.node_tree.links.new(texture.outputs['Color'], shader.inputs['Base Color'])
    shader.inputs['Roughness'].default_value = 0.6
    return material


def build_spur(name, back, side, material):
    root = back + Vector((0, -ROOT_EMBED, 0))
    vertices, uvs = [], []
    for j in range(RINGS + 1):
        t = j / RINGS
        # Back from the shank, then hooking upward and slightly outward like a cock's spur.
        center = root + Vector((side * 0.012 * t * t, (SPUR_LENGTH + ROOT_EMBED) * t, -0.008 * math.sin(t * math.pi) + 0.026 * t ** 2.4))
        r = SPUR_RADIUS * (1 - t) ** 0.72 + 0.0012
        for k in range(SIDES):
            a = k * math.tau / SIDES
            vertices.append(tuple(center + Vector((r * math.cos(a), 0, r * math.sin(a)))))
            uvs.append((0.5, t))
    faces = []
    for j in range(RINGS):
        for k in range(SIDES):
            n = (k + 1) % SIDES
            faces.append((j * SIDES + k, (j + 1) * SIDES + k, (j + 1) * SIDES + n, j * SIDES + n))
    faces.append(tuple(reversed(range(SIDES))))
    faces.append(tuple(RINGS * SIDES + k for k in range(SIDES)))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    layer = mesh.uv_layers.new(name='UVMap')
    for loop in mesh.loops:
        layer.data[loop.index].uv = uvs[loop.vertex_index]
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('views')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    body = load(args.input)
    image = gradient_image()
    spurs = []
    for name, back in find_leg_backs(body).items():
        side = 1 if name.endswith('_l') else -1
        spurs.append(build_spur(f'spur_{name}', back, side, spur_material(f'spur_{name}', image)))
    bpy.ops.object.select_all(action='DESELECT')
    for obj in [body, *spurs]:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = body
    # The body UV layer name decides the join result; align it so spur UVs survive.
    for spur in spurs:
        spur.data.uv_layers[0].name = body.data.uv_layers.active.name
    bpy.ops.object.join()
    body.name = 'body'
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB', use_selection=True, export_animations=False)
    print('EXPORTED', args.output, 'materials', [m.name for m in body.data.materials])
    Path(args.views).mkdir(parents=True, exist_ok=True)
    render_views(body, setup_render(1024), args.views)


main()
