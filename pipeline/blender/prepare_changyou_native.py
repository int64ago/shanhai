"""Uniformly normalize the native four-ear High, or render its final rig.

Blender ... --python prepare_changyou_native.py -- raw.glb normalized.glb
Blender ... --python prepare_changyou_native.py -- rigged.glb --views out --render-only
No welding, normal recomputation, island deletion or anatomical edits occur here.
"""
import argparse
import ast
import hashlib
import json
import runpy
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import bpy


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('output', nargs='?')
    parser.add_argument('--views')
    parser.add_argument('--render-only', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    source = Path(args.input).resolve()
    output = Path(args.output).resolve() if args.output else None
    views = Path(args.views).resolve() if args.views else None
    assert source.is_file()
    assert (args.render_only and views and not output) or (not args.render_only and output)
    if output:
        assert not output.exists(), 'Refuse to overwrite a normalized source'
        output.parent.mkdir(parents=True, exist_ok=True)
    if views:
        views.mkdir(parents=True, exist_ok=True)
        assert not list(views.iterdir()), 'Use a new empty view directory'
    helpers = Path(__file__).resolve().parent
    # normalize.py currently invokes main() unconditionally. Load only its
    # checked-in definitions; never execute scripts beside a downloaded GLB.
    normalization_path = helpers / 'normalize.py'
    tree = ast.parse(normalization_path.read_text(), filename=str(normalization_path))
    last = tree.body[-1]
    assert isinstance(last, ast.Expr) and isinstance(last.value, ast.Call)
    assert isinstance(last.value.func, ast.Name) and last.value.func.id == 'main'
    tree.body.pop()
    normalization = {'__name__': 'normalization_helpers'}
    exec(compile(tree, str(normalization_path), 'exec'), normalization)
    rendering = runpy.run_path(str(helpers / 'turnaround.py'), run_name='render_helpers')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # Armature custom-shape Icospheres are importer helpers, not GLB geometry.
    bpy.ops.import_scene.gltf(filepath=str(source), disable_bone_shape=True)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    assert len(meshes) == 1, ('Expected one actual source mesh', len(meshes))
    body = meshes[0]
    before = (len(body.data.vertices), len(body.data.polygons))
    for obj in bpy.context.scene.objects:
        if obj.animation_data:
            for track in obj.animation_data.nla_tracks:
                track.mute = True
            obj.animation_data.action = None
        if obj.type == 'ARMATURE':
            obj.data.pose_position = 'REST'
    if not args.render_only:
        bpy.ops.object.select_all(action='DESELECT')
        body.select_set(True)
        bpy.context.view_layer.objects.active = body
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        for obj in list(bpy.context.scene.objects):
            if obj is not body:
                bpy.data.objects.remove(obj)
        normalization['normalize'](body, 1., 0., trim_tail=False)
        body.name = 'actual_generated_high_no_geometry_cleanup'
        bpy.ops.export_scene.gltf(filepath=str(output), export_format='GLB', use_selection=True)
    assert before == (len(body.data.vertices), len(body.data.polygons))
    if views:
        camera = rendering['setup_render'](1024)
        rendering['render_views'](body, camera, str(views))
    report = {
        'source': str(source), 'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'output': str(output) if output else None, 'renderOnly': args.render_only,
        'vertices': before[0], 'faces': before[1], 'cleanupApplied': False,
        'anatomyEditsApplied': False, 'normalRecomputationApplied': False,
        'images': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in views.glob('*.png')} if views else {},
    }
    report_path = output.with_suffix('.prepare.json') if output else views / 'manifest.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print('NATIVE_CHANGYOU_PREPARED', json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
