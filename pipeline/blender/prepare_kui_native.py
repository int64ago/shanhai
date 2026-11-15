"""Normalize the parent-accepted native v10 High without editing its surface."""
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

SOURCE_SHA = '31117de85c4577871ffee01facea75abfd851eccc070ebdbed13ede7721de662'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source'); parser.add_argument('output')
    parser.add_argument('--length', type=float, default=1.6)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    source, output = Path(args.source).resolve(), Path(args.output).resolve()
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA:
        raise ValueError('Expected the parent-reviewed v10 High Kui')
    if source == output or not 0 < args.length < 10:
        raise ValueError('Require separate output and finite positive length')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if len(meshes) != 1: raise ValueError('Changed native mesh layout')
    obj = meshes[0]
    before = native_fingerprint(obj)
    points = np.array([tuple(obj.matrix_world @ v.co) for v in obj.data.vertices])
    lo, hi = points.min(axis=0), points.max(axis=0)
    center = Vector(((lo[0]+hi[0])/2, (lo[1]+hi[1])/2, lo[2]))
    scale = args.length / max(hi-lo)
    # The original corner-normal basis stays on the unchanged mesh.
    world = Matrix.Scale(scale,4) @ Matrix.Translation(-center) @ obj.matrix_world
    obj.parent = None; obj.matrix_world = world
    bpy.context.view_layer.update()
    for node in list(bpy.context.scene.objects):
        if node is not obj: bpy.data.objects.remove(node, do_unlink=True)
    obj.name = 'kui_native_hornless_monopod'
    after = native_fingerprint(obj)
    if before != after: raise ValueError('Normalization altered native surface')
    obj['kui_native_source_sha256'] = SOURCE_SHA
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    output.parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(output),export_format='GLB',use_selection=True,
                             export_animations=False,export_extras=True)
    manifest = dict(source=str(source),sourceSha256=SOURCE_SHA,targetLength=args.length,
                    uniformScale=scale,geometryEdits=False,nativeFingerprint=after)
    (output.parent/'kui-native-preparation.json').write_text(json.dumps(manifest,indent=2))
    print('TRIS 50000 native-preserved',flush=True)


if __name__ == '__main__': main()
