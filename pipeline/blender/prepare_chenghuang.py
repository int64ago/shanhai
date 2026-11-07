"""White fox preparation. Body references retain four grounded paws; tail reuses
jiuweihu-tail-max's normalized master, recoloured offline rather than with VFX.

Blender --background --factory-startup --python pipeline/blender/prepare_chenghuang.py --
  body|tail input.glb output.glb views_directory [--view 34|side|front|back|opposite]
"""
import argparse
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, fix_pose, render_views, setup_render
from prepare_lushu import low_components


def remove_native_tail(obj, height, rump_y):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-6)
    uv = bm.loops.layers.uv.active
    rump_face = min(bm.faces, key=lambda f: (f.calc_center_median() - Vector((0, rump_y - 0.02, height + 0.13))).length)
    rump_uv = rump_face.loops[0][uv].uv.copy() if uv else None
    # Measured draft: at z=.50 the tail is a separate branch whose lowest
    # vertex is .165; all four leg branches reach the ground. Hind hocks
    # end at y=.3196, so the upper-rump correction does not clip a leg.
    tails = [g for g in low_components(bm, height)
             if len(g) > 30 and min(v.co.z for v in g) > 0.08
             and max(v.co.y for v in g) > rump_y + 0.08]
    if len(tails) != 1:
        raise RuntimeError(f'Expected one isolated tail branch, got {len(tails)}')
    bmesh.ops.delete(bm, geom=list(tails[0]), context='VERTS')
    for v in bm.verts:
        if v.co.z > height - 0.05 and v.co.y > rump_y:
            v.co.y = rump_y + (v.co.y - rump_y) * 0.04
    boundary = [e for e in bm.edges if e.is_boundary
                and all(v.co.y > rump_y - 0.05 and v.co.z > height - 0.03 for v in e.verts)]
    filled = bmesh.ops.holes_fill(bm, edges=boundary, sides=0)['faces']
    if uv:
        for face in filled:
            face.smooth = True
            for loop in face.loops:
                # Averaging distant UV islands can sample an eye or nose.
                loop[uv].uv = rump_uv
    feet = [g for g in low_components(bm, 0.06) if len(g) > 30]
    assert len(feet) == 4, f'Tail removal must retain four paws: {len(feet)}'
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    print('TRIM_NATIVE_TAIL', len(tails[0]), 'FOUR_PAWS', len(feet))


def white_tail(obj):
    for material in obj.data.materials:
        if not material or not material.use_nodes:
            continue
        shader = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        color = shader.inputs['Base Color']
        if not color.is_linked:
            color.default_value = (0.88, 0.87, 0.84, 1)
            continue
        node = color.links[0].from_node
        if node.type != 'TEX_IMAGE':
            raise RuntimeError('Expected the fox tail base-colour image')
        image = node.image.copy()
        node.image = image
        pixels = np.empty(len(image.pixels), dtype=np.float32)
        image.pixels.foreach_get(pixels)
        rgba = pixels.reshape((-1, 4))
        luminance = rgba[:, :3] @ np.array([0.2126, 0.7152, 0.0722])
        # Preserve the fur texture's value variation in an ivory-white range.
        white = 0.67 + 0.29 * np.sqrt(luminance.clip(0, 1))
        rgba[:, :3] = white[:, None] * np.array([1, 0.992, 0.975])
        image.pixels.foreach_set(pixels)
        image.update()
        image.pack()
        print('WHITE_TAIL', image.name, tuple(image.size))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['body', 'tail'])
    p.add_argument('input')
    p.add_argument('output')
    p.add_argument('views')
    p.add_argument('--view', choices=['34', 'side', 'front', 'back', 'opposite'])
    p.add_argument('--already-level', action='store_true')
    p.add_argument('--trim-native-tail', action='store_true')
    p.add_argument('--tail-height', type=float, default=0.50)
    p.add_argument('--rump-y', type=float, default=0.32)
    a = p.parse_args(sys.argv[sys.argv.index('--') + 1:])
    obj = load(a.input)
    if a.mode == 'tail':
        white_tail(obj)
    elif not a.already_level:
        # Head/ear height is not shoulder height: use torso slices at the paws.
        low = [v.co for v in obj.data.vertices if v.co.z < 0.07]
        mid = (min(v.y for v in low) + max(v.y for v in low)) / 2
        fy = sum(v.y for v in low if v.y < mid) / sum(v.y < mid for v in low)
        by = sum(v.y for v in low if v.y >= mid) / sum(v.y >= mid for v in low)
        def back_top(y):
            return max(v.co.z for v in obj.data.vertices if abs(v.co.y - y) < 0.035)
        dz = max(0, min(0.10, back_top(fy) - back_top(by)))
        print('LEVEL_BACK', fy, by, dz)
        fix_pose(obj, str(dz), keep_tail=True)
        # Compress only tiny deviations at the soles; retain paw anatomy.
        for v in obj.data.vertices:
            if v.co.z < 0.007:
                v.co.z = 0
        obj.data.update()
    if a.trim_native_tail:
        remove_native_tail(obj, a.tail_height, a.rump_y)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output, export_format='GLB', use_selection=True, export_animations=False)
    Path(a.views).mkdir(parents=True, exist_ok=True)
    cam = setup_render(1024)
    if a.view == 'opposite':
        # Mirror the camera by rotation, never the outlined beast geometry.
        pts = [v.co for v in obj.data.vertices]
        lo = Vector([min(v[i] for v in pts) for i in range(3)])
        hi = Vector([max(v[i] for v in pts) for i in range(3)])
        center = (lo + hi) / 2
        cam.data.ortho_scale = max(hi - lo) * 1.15
        cam.location = center + Vector((-max(hi - lo) * 3, 0, 0))
        cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()
        bpy.context.scene.render.filepath = str(Path(a.views) / 'view_opposite.png')
        bpy.ops.render.render(write_still=True)
    else:
        render_views(obj, cam, a.views, only_view=a.view)


if __name__ == '__main__':
    main()
