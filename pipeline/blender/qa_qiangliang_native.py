"""Render the bounded Qiangliang candidate in original PBR and neutral clay."""
import argparse
from pathlib import Path
import sys

import bpy
from mathutils import Matrix, Vector


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(Path(args.source).resolve()))
    imported = list(bpy.context.scene.objects)
    meshes = [o for o in imported if o.type == 'MESH']
    points = [o.matrix_world @ v.co for o in meshes for v in o.data.vertices]
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    scale = 1 / (high.z - low.z)
    offset = Vector((-(low.x + high.x) * .5 * scale,
                     -(low.y + high.y) * .5 * scale, -low.z * scale))
    root = bpy.data.objects.new('qa_uniform_scale', None)
    bpy.context.scene.collection.objects.link(root)
    root.matrix_world = Matrix.Translation(offset) @ Matrix.Scale(scale, 4)
    for obj in imported:
        if obj.parent is None:
            obj.parent = root
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    scene.render.resolution_x = scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'AgX'
    world = bpy.data.worlds.new('neutral_world')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (.55, .57, .60, 1)
    world.node_tree.nodes['Background'].inputs[1].default_value = .8
    scene.world = world
    for i, (location, energy) in enumerate([((2, -3, 4), 240), ((-3, 1, 2), 210), ((1, 3, 3), 180)]):
        light = bpy.data.objects.new(str(i), bpy.data.lights.new(str(i), 'AREA'))
        scene.collection.objects.link(light)
        light.location = location
        light.rotation_euler = (Vector((0, 0, .4)) - light.location).to_track_quat('-Z', 'Y').to_euler()
        light.data.energy, light.data.size = energy, 3
    camera = bpy.data.objects.new('qa_camera', bpy.data.cameras.new('qa_camera'))
    scene.collection.objects.link(camera)
    camera.data.type = 'ORTHO'
    scene.camera = camera
    specs = [
        ('front', (0, 0, .5), (0, -1, 0), 1.10),
        ('side', (0, 0, .5), (-1, 0, 0), 1.10),
        ('back', (0, 0, .5), (0, 1, 0), 1.10),
        ('wrist_front', (.29, 0, .48), (0, -1, .05), .32),
        ('wrist_back', (.29, 0, .48), (0, 1, .05), .32),
        ('wrist_side', (-.29, 0, .48), (-1, .35, .05), .30),
        ('feet_front', (0, 0, .075), (0, -1, .15), .40),
        ('feet_back', (0, 0, .075), (0, 1, .15), .40),
        ('ankle_side', (.1, 0, .07), (1, .25, .08), .23),
    ]
    clay = bpy.data.materials.new('qa_clay')
    clay.use_nodes = True
    bsdf = clay.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (.42, .42, .42, 1)
    bsdf.inputs['Roughness'].default_value = .8
    original = {o.name: [s.material for s in o.material_slots] for o in meshes}
    for mode in ('pbr', 'clay'):
        for obj in meshes:
            for i, slot in enumerate(obj.material_slots):
                slot.material = clay if mode == 'clay' else original[obj.name][i]
        for name, target, direction, ortho in specs:
            target = Vector(target)
            camera.location = target + Vector(direction).normalized() * 3
            camera.rotation_euler = (target - camera.location).to_track_quat('-Z', 'Y').to_euler()
            camera.data.ortho_scale = ortho
            scene.render.filepath = str(output / (mode + '_' + name + '.png'))
            bpy.context.view_layer.update()
            bpy.ops.render.render(write_still=True)
    print('QIANGliANG_CANDIDATE_QA_COMPLETE ' + str(output), flush=True)


if __name__ == '__main__':
    main()
