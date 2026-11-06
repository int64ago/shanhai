"""Keep Taotie's assembled human face and palm-down hands rigid on their bones.

Run after rig_quadruped.py and before gltf-transform compression:
  blender --background --python pipeline/blender/fix_taotie_weights.py -- \
      raw/_build/taotie/body_rig.glb raw/_build/taotie/body_weighted.glb

Voxel weight transfer cannot distinguish the overlapping modular human head
from the shoulders, or the flat human hands from the lower legs. The assembly's
material prefixes identify those parts without relying on geometric cutoffs.
"""
import argparse
import sys
from pathlib import Path

import bpy


PART_BONES = {
    'human_head_': 'head',
    'claw_front_l_': 'front_l_foot',
    'claw_front_r_': 'front_r_foot',
    'claw_back_l_': 'back_l_foot',
    'claw_back_r_': 'back_r_foot',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('output')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = 30
    bpy.ops.import_scene.gltf(filepath=args.input)
    armatures = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    if len(armatures) != 1:
        raise RuntimeError(f'Expected one Taotie armature, found {len(armatures)}')
    armature = armatures[0]
    counts = dict.fromkeys(PART_BONES, 0)
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH':
            continue
        vertices = {prefix: set() for prefix in PART_BONES}
        for polygon in obj.data.polygons:
            if polygon.material_index >= len(obj.material_slots):
                continue
            material = obj.material_slots[polygon.material_index].material
            if material is None:
                continue
            for prefix in PART_BONES:
                if material.name.startswith(prefix):
                    vertices[prefix].update(polygon.vertices)
                    break
        assigned = set()
        for prefix, indices in vertices.items():
            if not indices:
                continue
            if assigned.intersection(indices):
                raise RuntimeError(f'Overlapping modular vertex sets: {prefix}')
            assigned.update(indices)
            bone = PART_BONES[prefix]
            if bone not in armature.data.bones:
                raise RuntimeError(f'Missing bone {bone}')
            # These are separate assembled surfaces. Keep the complete face,
            # fingers, palm and wrist together, including internal overlap.
            indices = sorted(indices)
            for group in obj.vertex_groups:
                group.remove(indices)
            group = obj.vertex_groups.get(bone) or obj.vertex_groups.new(name=bone)
            group.add(indices, 1.0, 'REPLACE')
            counts[prefix] += len(indices)
    missing = [prefix for prefix, count in counts.items() if not count]
    if missing:
        raise RuntimeError(f'Missing Taotie assembly material prefixes: {missing}')
    for prefix, count in counts.items():
        print(f'TAOTIE_WEIGHTS {prefix} -> {PART_BONES[prefix]}: {count} vertices')
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
