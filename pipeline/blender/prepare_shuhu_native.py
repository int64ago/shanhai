"""Unified-recipe preparation for the accepted v13 native High Shuhu.

Only positive uniform normalization is applied. Native 500,000 triangles,
UVs, corner-normal directions and PBR images are retained for the rig stage.
CLI: SOURCE.glb OUTPUT.glb --length 1.7
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Matrix, Vector
from rig_jimeng_native import native_fingerprint

SOURCE_SHA = '0bd5963144eeda704e46e5ca1c8d902a0756ad6039252b2422f88a473ebe3cbe'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('output')
    parser.add_argument('--length', type=float, default=1.7)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    source, output = Path(args.source).resolve(), Path(args.output).resolve()
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected the parent-reviewed v13 native High source')
    if source == output or not 0 < args.length < 10:
        raise ValueError('Require a separate output and positive finite target length')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if len(meshes) != 1:
        raise ValueError('Review a changed native mesh layout before preparation')
    obj = meshes[0]
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    before = native_fingerprint(obj)
    positions = np.array([tuple(v.co) for v in obj.data.vertices])
    normals = np.array([tuple(n.vector) for n in obj.data.corner_normals])
    lo, hi = positions.min(axis=0), positions.max(axis=0)
    scale = args.length / max(hi - lo)
    center = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]))
    # Keep the native custom-normal basis untouched. Normalize at the object
    # transform instead of re-encoding 1.5 million native corner normals.
    obj.matrix_world = Matrix.Scale(scale, 4) @ Matrix.Translation(-center) @ obj.matrix_world
    bpy.context.view_layer.update()
    obj.name = 'shuhu_native_human_horse_wings_snake'
    after = native_fingerprint(obj)
    for key in before:
        if key != 'cornerNormalsSha256' and before[key] != after[key]:
            raise ValueError('Unexpected native surface change: ' + key)
    normal_error = float(np.max(np.abs(np.array([tuple(n.vector) for n in obj.data.corner_normals]) - normals)))
    if normal_error > .0012:
        raise ValueError('Native normal direction changed beyond Blender codec tolerance')
    for node in list(bpy.context.scene.objects):
        if node is not obj:
            bpy.data.objects.remove(node, do_unlink=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    obj['shuhu_native_source_sha256'] = SOURCE_SHA
    obj['shuhu_review_coordinate_scale'] = args.length
    bpy.ops.export_scene.gltf(filepath=str(output), export_format='GLB', use_selection=True,
                             export_animations=False, export_extras=True)
    manifest = {'source': str(source), 'sourceSha256': SOURCE_SHA,
                'targetLength': args.length, 'uniformScale': scale,
                'translationBeforeScale': list(-center), 'geometryEdits': False,
                'triangles': 500000, 'nativeFingerprint': after,
                'normalDirectionMaxRoundoff': normal_error}
    (output.parent / 'shuhu-native-preparation.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print('NATIVE_PREPARED', str(output), '500000 triangles; scale', scale, flush=True)


if __name__ == '__main__':
    main()
