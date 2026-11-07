"""Bind Bibi's native tail to the hips so it stops following the hind legs.

Run after rig_quadruped.py and before gltf-transform compression:
  blender --background --python pipeline/blender/fix_bibi_weights.py -- \
      raw/_build/bibi/body_rig.glb raw/_build/bibi/body_weighted.glb

The tail lies next to the thighs, so automatic weights pull its root along with
each stride. The tail is one material with the body, so it is selected by two
lines measured on the normalized Stage 2 side view (feet z=0, nose towards -Y).
"""
import argparse
import sys
from pathlib import Path

import bpy

ROOT_Y, ROOT_Z, ROOT_SLOPE = 0.236, 0.355, 0.113   # rump/tail junction
UNDER_SLOPE = 1.09                                 # tail underside, falling backwards
BLEND = 0.05                                       # fade into the rump weights


def smoothstep(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def tail_factor(p):
    if p.z < ROOT_Z - UNDER_SLOPE * (p.y - ROOT_Y) - 0.01:
        return 0.0  # below the underside: thigh and hock
    return smoothstep(0.0, BLEND, p.y - (ROOT_Y + ROOT_SLOPE * (p.z - ROOT_Z)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = 30
    bpy.ops.import_scene.gltf(filepath=args.input)
    # The glTF importer adds an unweighted Icosphere as a bone display shape;
    # remove it so the re-export cannot carry a stray 2 m sphere.
    meshes = []
    for candidate in [o for o in bpy.context.scene.objects if o.type == 'MESH']:
        if candidate.vertex_groups:
            meshes.append(candidate)
        else:
            bpy.data.objects.remove(candidate)
    if len(meshes) != 1:
        raise RuntimeError(f'Expected one skinned Bibi mesh, found {len(meshes)}')
    obj = meshes[0]
    hips = obj.vertex_groups.get('hips')
    if hips is None:
        raise RuntimeError('Missing hips vertex group')
    full = blended = 0
    for vertex in obj.data.vertices:
        t = tail_factor(obj.matrix_world @ vertex.co)
        if t <= 0:
            continue
        kept = [(g.group, g.weight * (1 - t)) for g in vertex.groups if g.group != hips.index]
        hip_weight = 1 - sum(w for _, w in kept)
        for group, weight in kept:
            obj.vertex_groups[group].add([vertex.index], weight, 'REPLACE')
        hips.add([vertex.index], hip_weight, 'REPLACE')
        full += t >= 1
        blended += t < 1
    print(f'BIBI_WEIGHTS tail -> hips: {full} full, {blended} blended of {len(obj.data.vertices)}')
    if full < 500:
        raise RuntimeError('Tail mask selected too few vertices')
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=args.output,
        export_format='GLB',
        export_animations=True,
        export_animation_mode='ACTIONS',
        export_skins=True,
        export_def_bones=False,
    )
    print('EXPORTED', args.output)


main()
