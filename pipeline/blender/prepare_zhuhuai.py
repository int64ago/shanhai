"""Remove the preview's stray central chest tuft and render the hornless body references.

The four horns are explicit runtime appendages, so the body reference stays hornless.
Input is the normalized Medium preview, with Blender -Y forward and Z up.
"""
import argparse
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render


def rig_final(args):
    import rig_quadruped as rig

    obj = rig.load(args.input)
    bpy.context.scene.render.fps = rig.FPS
    landmarks = rig.landmarks(obj)
    arm = rig.build_armature(landmarks)
    rig.skin(obj, arm)
    # Direct heat weights tore the final mesh at the shoulder despite only 14
    # unweighted vertices. Rebuild on the watertight proxy before accepting it.
    rig.skin_via_proxy(obj, arm)
    if rig.unweighted_count(obj):
        rig.skin_by_distance(obj, arm)
    rig.normalize_weights(obj)
    print('SKIN final unweighted vertices:', rig.unweighted_count(obj))
    rig.anim_idle(arm, landmarks)
    rig.anim_walk(arm, landmarks)
    rig.anim_alert(arm, landmarks)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.views).mkdir(parents=True, exist_ok=True)
    rig.render_preview(obj, arm, str(Path(args.views) / 'rig.png'), landmarks)
    bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB', export_animations=True,
                              export_animation_mode='NLA_TRACKS', export_skins=True, export_def_bones=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('views')
    parser.add_argument('--rig', action='store_true', help='Rig final body using verified watertight-proxy weights')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    if args.rig:
        rig_final(args)
        return
    obj = load(args.input)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    original_edges = {e for e in bm.edges if e.is_boundary}
    stray = [f for f in bm.faces if abs(f.calc_center_median().x) < 0.043
             and -0.265 < f.calc_center_median().y < -0.165
             and f.calc_center_median().z < 0.206]
    bmesh.ops.delete(bm, geom=stray, context='FACES')
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context='VERTS')
    edges = [e for e in bm.edges if e.is_boundary and e not in original_edges]
    uv = bm.loops.layers.uv.active
    neighbors = [l[uv].uv.copy() for e in edges for f in e.link_faces for l in f.loops]
    # Averaging UVs can land between atlas islands on an unpainted white pixel.
    mean = neighbors[0] if neighbors else Vector((0, 0))
    cap = bmesh.ops.holes_fill(bm, edges=edges, sides=0)
    for face in cap['faces']:
        for loop in face.loops:
            loop[uv].uv = mean
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.views).mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB', use_selection=True, export_animations=False)
    print('CLEANUP removed stray chest tuft faces:', len(stray))
    render_views(obj, setup_render(1024), args.views)


if __name__ == '__main__':
    main()
