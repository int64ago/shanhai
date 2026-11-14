"""Render unmodified native PBR evidence; only uniform scale and translation.

Run from the trusted repository, never from a downloaded source directory:
Blender --background --factory-startup --disable-autoexec --python-exit-code 1
  --python pipeline/blender/review_native_source_20261114.py --
  --source /absolute/source.glb --output-dir /absolute/new/output
  --closeup 'name:x,y,z:dx,dy,dz:ortho_scale'

--probe prints normalized coordinate summaries without creating outputs.
Camera names express source Blender axes, not guessed anatomical orientation.
The head direction stays unconfirmed until a human/parent inspects the images.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    with path.open('rb') as stream:
        value = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def surface_digest(meshes):
    """Hash native data, excluding object transforms used for normalization."""
    value = hashlib.sha256()
    for obj in sorted(meshes, key=lambda item: item.name):
        mesh = obj.data
        mesh.calc_loop_triangles()
        records = (
            obj.name,
            [tuple(v.co) for v in mesh.vertices],
            [tuple(p.vertices) for p in mesh.polygons],
            [(loop.vertex_index, loop.edge_index) for loop in mesh.loops],
            [[tuple(item.uv) for item in layer.data] for layer in mesh.uv_layers],
            [tuple(normal.vector) for normal in mesh.corner_normals],
            [p.material_index for p in mesh.polygons],
            [p.use_smooth for p in mesh.polygons],
            [slot.material.name if slot.material else None for slot in obj.material_slots],
        )
        value.update(repr(records).encode())
    return value.hexdigest()


def material_digest(meshes):
    values = []
    materials = {slot.material for obj in meshes for slot in obj.material_slots if slot.material}
    for material in sorted(materials, key=lambda item: item.name):
        nodes = []
        links = []
        if material.use_nodes:
            for node in material.node_tree.nodes:
                defaults = []
                for socket in node.inputs:
                    if hasattr(socket, 'default_value'):
                        item = socket.default_value
                        if isinstance(item, (str, int, float, bool)):
                            defaults.append((socket.identifier, item))
                        else:
                            try:
                                defaults.append((socket.identifier, tuple(item)))
                            except TypeError:
                                defaults.append((socket.identifier, str(item)))
                image = getattr(node, 'image', None)
                nodes.append((node.name, node.bl_idname, defaults,
                              (image.name, tuple(image.size), image.colorspace_settings.name,
                               hashlib.sha256(bytes(image.packed_file.data)).hexdigest()
                               if image.packed_file else image.filepath) if image else None))
            links = [(link.from_node.name, link.from_socket.identifier,
                      link.to_node.name, link.to_socket.identifier)
                     for link in material.node_tree.links]
        values.append((material.name, tuple(material.diffuse_color), material.use_nodes, nodes, links))
    return hashlib.sha256(repr(values).encode()).hexdigest()


def world_points(meshes):
    return [obj.matrix_world @ vertex.co for obj in meshes for vertex in obj.data.vertices]


def bounds(points):
    low = Vector([min(point[axis] for point in points) for axis in range(3)])
    high = Vector([max(point[axis] for point in points) for axis in range(3)])
    return dict(min=list(low), max=list(high), size=list(high - low))


def vector(text):
    result = tuple(float(item) for item in text.split(','))
    if len(result) != 3 or not all(math.isfinite(item) for item in result):
        raise ValueError('Expected three finite comma-separated coordinates')
    return result


def closeup(text):
    name, target, direction, scale = text.split(':')
    if not name or any(char not in 'abcdefghijklmnopqrstuvwxyz0123456789_-' for char in name):
        raise ValueError('Use a safe descriptive lowercase closeup name')
    scale = float(scale)
    direction = vector(direction)
    if not math.isfinite(scale) or scale <= 0 or Vector(direction).length == 0:
        raise ValueError('Closeup requires positive scale and nonzero direction')
    return name, vector(target), direction, scale, 512


def probe(points):
    result = {'normalizedBounds': bounds(points), 'sourceAxesPreserved': True,
              'headDirection': 'UNCONFIRMED_PENDING_PARENT_VISUAL_REVIEW', 'heightSlices': []}
    extent = bounds(points)['size']
    for step in range(10):
        bottom, top = extent[2] * step / 10, extent[2] * (step + 1) / 10
        selected = [point for point in points if bottom <= point.z <= top]
        if selected:
            result['heightSlices'].append(dict(zRange=[bottom, top], vertices=len(selected),
                                               bounds=bounds(selected)))
    print('NATIVE_SOURCE_PROBE ' + json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output-dir')
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--complete-existing', action='store_true',
                        help='Recover this helper\'s rendered images after an interrupted contact-sheet step')
    parser.add_argument('--closeup', action='append', type=closeup, default=[])
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    source = Path(args.source).resolve(strict=True)
    if not source.is_relative_to(ROOT / 'raw') or source.suffix.lower() != '.glb':
        raise ValueError('Source must be a GLB under the worktree raw directory')
    if source.parent == Path(__file__).resolve().parent:
        raise ValueError('Downloaded inputs must be outside the trusted script directory')
    if not args.probe and (not args.output_dir or not args.closeup):
        raise ValueError('Render mode requires a new output directory and explicit closeup coordinates')
    source_before = digest(source)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source), disable_bone_shape=True)
    imported = list(bpy.context.scene.objects)
    meshes = [obj for obj in imported if obj.type == 'MESH']
    if not meshes or any(obj.type == 'ARMATURE' for obj in imported):
        raise ValueError('Expected nonempty native static meshes without armatures')
    if any(obj.modifiers for obj in meshes):
        raise ValueError('Review helper does not evaluate or alter source modifiers')
    points_before = world_points(meshes)
    original_bounds = bounds(points_before)
    extent = Vector(original_bounds['size'])
    scale = 1.0 / max(extent)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError('Invalid source bounds')
    low, high = Vector(original_bounds['min']), Vector(original_bounds['max'])
    offset = Vector((-(low.x + high.x) * .5 * scale,
                     -(low.y + high.y) * .5 * scale, -low.z * scale))
    transform = Matrix.Translation(offset) @ Matrix.Scale(scale, 4)
    surface_before = surface_digest(meshes)
    materials_before = material_digest(meshes)
    original_world = {obj.name: obj.matrix_world.copy() for obj in meshes}
    normalization = bpy.data.objects.new('review_uniform_normalization', None)
    bpy.context.scene.collection.objects.link(normalization)
    normalization.matrix_world = transform
    for obj in imported:
        if obj.parent is None:
            obj.parent = normalization
    bpy.context.view_layer.update()
    for obj in meshes:
        expected = transform @ original_world[obj.name]
        error = max(abs(obj.matrix_world[row][col] - expected[row][col])
                    for row in range(4) for col in range(4))
        if error > 1e-5:
            raise ValueError('Normalization changed more than a uniform world transform')
    points = world_points(meshes)
    normalized_bounds = bounds(points)
    assert abs(max(normalized_bounds['size']) - 1) < 1e-5
    assert abs(normalized_bounds['min'][2]) < 1e-5
    if args.probe:
        probe(points)
        assert surface_digest(meshes) == surface_before
        assert material_digest(meshes) == materials_before
        assert digest(source) == source_before
        return
    output = Path(args.output_dir).resolve()
    if not output.is_relative_to(ROOT / 'raw/_build'):
        raise ValueError('Output must be below worktree raw/_build')
    if args.complete_existing:
        if not output.is_dir() or (output / 'source-manifest.json').exists():
            raise ValueError('Recovery requires an incomplete render directory without a manifest')
    else:
        output.mkdir(parents=True, exist_ok=False)
    bpy.ops.object.select_all(action='DESELECT')
    normalization.select_set(True)
    for obj in imported:
        obj.select_set(True)
    normalized = output / 'normalized.glb'
    bpy.ops.export_scene.gltf(filepath=str(normalized), export_format='GLB',
                             use_selection=True, export_animations=False,
                             export_normals=True, export_texcoords=True,
                             export_materials='EXPORT', export_image_format='AUTO',
                             export_yup=True, export_apply=False)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'AgX'
    world = bpy.data.worlds.new('native_review_neutral_world')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (.55, .57, .60, 1)
    world.node_tree.nodes['Background'].inputs[1].default_value = .8
    scene.world = world
    for index, (location, energy, size) in enumerate([
            ((2, -3, 4), 240, 3), ((-3, 1, 2), 210, 3), ((1, 3, 3), 180, 3)]):
        light = bpy.data.objects.new('review_softbox_' + str(index),
                                     bpy.data.lights.new('review_softbox_' + str(index), 'AREA'))
        scene.collection.objects.link(light)
        light.location = location
        light.rotation_euler = (Vector((0, 0, .4)) - light.location).to_track_quat('-Z', 'Y').to_euler()
        light.data.energy, light.data.size = energy, size
    center = (Vector(normalized_bounds['min']) + Vector(normalized_bounds['max'])) * .5
    specs = [
        ('view_minus_y_front_or_back', center, (0, -1, 0), 1.15, 768),
        ('view_plus_y_front_or_back', center, (0, 1, 0), 1.15, 768),
        ('view_plus_x_side', center, (1, 0, 0), 1.15, 768),
        ('view_minus_x_side', center, (-1, 0, 0), 1.15, 768),
        ('view_34_minus_y', center, (.65, -.75, .3), 1.25, 768),
        ('view_34_plus_y', center, (-.65, .75, .3), 1.25, 768),
    ] + args.closeup
    if len({spec[0] for spec in specs}) != len(specs):
        raise ValueError('View names must be unique')
    images = []
    for name, target, direction, ortho_scale, resolution in specs:
        target = Vector(target)
        location = target + Vector(direction).normalized() * 3
        camera = bpy.data.objects.new(name, bpy.data.cameras.new(name))
        scene.collection.objects.link(camera)
        camera.matrix_world = Matrix.LocRotScale(
            location, (target - location).to_track_quat('-Z', 'Y'), Vector((1, 1, 1)))
        camera.data.type = 'ORTHO'
        camera.data.ortho_scale = ortho_scale
        camera.data.clip_start, camera.data.clip_end = .01, 100
        scene.camera = camera
        scene.render.resolution_x = scene.render.resolution_y = resolution
        bpy.context.view_layer.update()
        image = output / (name + '.png')
        scene.render.filepath = str(image)
        if args.complete_existing:
            # Images here were already emitted by this helper; never decode a source script.
            header = image.read_bytes()[:24]
            if (header[:8] != b'\x89PNG\r\n\x1a\n'
                    or int.from_bytes(header[16:20], 'big') != resolution
                    or int.from_bytes(header[20:24], 'big') != resolution):
                raise ValueError('Recovery image has an unexpected PNG size: ' + str(image))
        else:
            bpy.ops.render.render(write_still=True)
        images.append(dict(path=image.name, sha256=digest(image),
                           resolution=[resolution, resolution], target=list(target),
                           direction=list(direction), cameraLocation=list(location), orthoScale=ortho_scale))
    contact_sheets = []
    magick = shutil.which('magick')
    if magick:
        members = ['view_minus_y_front_or_back.png', 'view_plus_y_front_or_back.png',
                   'view_plus_x_side.png', 'view_34_minus_y.png']
        contact = output / 'contact_four_views.png'
        subprocess.run([magick, '(', str(output / members[0]), str(output / members[1]),
                        '+append', ')', '(', str(output / members[2]), str(output / members[3]),
                        '+append', ')', '-append', str(contact)], check=True, timeout=60)
        contact_sheets.append(dict(path=contact.name, sha256=digest(contact),
                                   resolution=[1536, 1536], membersRowMajor=members))
    surface_after = surface_digest(meshes)
    materials_after = material_digest(meshes)
    assert surface_before == surface_after, 'Native geometry/UV/normals changed'
    assert materials_before == materials_after, 'Original PBR materials changed'
    assert digest(source) == source_before, 'Source file changed'
    counts = []
    for obj in meshes:
        counts.append(dict(name=obj.name, vertices=len(obj.data.vertices),
                           polygons=len(obj.data.polygons), triangles=len(obj.data.loop_triangles),
                           loops=len(obj.data.loops), uvLayers=len(obj.data.uv_layers),
                           materials=len(obj.material_slots)))
    manifest = dict(
        status='RENDER_EVIDENCE_ONLY_PENDING_PARENT_IMAGE_REVIEW',
        source=str(source), sourceSha256Before=source_before, sourceSha256After=digest(source),
        blenderVersion=bpy.app.version_string, sourceCoordinateFrame='Blender glTF-import axes (+Z up)',
        headOrientation='UNCONFIRMED; parent must identify using both +/-Y and +/-X images',
        frontBackLabelsAssigned=False, anatomicalLeftRightAssigned=False,
        closeupTargets='Explicit camera regions; anatomical identification requires parent image inspection',
        sourceBounds=original_bounds, normalizedBounds=normalized_bounds,
        normalization=dict(uniformScale=scale, translation=list(offset), rotationApplied=False,
                           worldMatrix=[list(row) for row in transform]),
        meshCounts=counts, totalVertices=sum(item['vertices'] for item in counts),
        totalTriangles=sum(item['triangles'] for item in counts),
        surfaceUvNormalsSha256Before=surface_before, surfaceUvNormalsSha256After=surface_after,
        materialSha256Before=materials_before, materialSha256After=materials_after,
        geometryEdits='Uniform object-root scale and translation only', topologyEdits=False,
        uvEdits=False, materialEdits=False, normalRecomputation=False,
        normalizedGlb=dict(path=normalized.name, sha256=digest(normalized)),
        renderer=dict(engine='CYCLES', samples=32, denoising=True, viewTransform='AgX',
                      neutralWorld=True, originalPbr=True),
        script=dict(path=str(Path(__file__).resolve()), sha256=digest(Path(__file__).resolve())),
        images=images, contactSheets=contact_sheets, correctionAttempts=0, apiCalls=0, acceptanceDecision=None,
    )
    (output / 'source-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('NATIVE_SOURCE_REVIEW_COMPLETE ' + str(output), flush=True)


if __name__ == '__main__':
    main()
