"""Rebuild the broken Medium ear-snake silhouette as a continuous sculpt reference.

This is an authored correction guide, not a generated High or runtime asset.
Blender --background --factory-startup --disable-autoexec --python-exit-code 1
  --python pipeline/blender/prepare_kuafu_ear_reference.py -- --out-dir <new dir>
"""
import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def material(name, color, roughness=.6):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Base Color'].default_value = (*color, 1)
    shader.inputs['Roughness'].default_value = roughness
    return mat


def curve(name, points, radius, mat):
    data = bpy.data.curves.new(name, 'CURVE')
    data.dimensions = '3D'
    data.resolution_u = 16
    data.bevel_depth = radius
    data.bevel_resolution = 3
    spline = data.splines.new('POLY')
    spline.points.add(len(points) - 1)
    for p, co in zip(spline.points, points):
        p.co = (*co, 1)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    return obj


def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # Snout -> rounded head -> neck -> open hook -> hanging tapered tail.
    controls = [
        ((-.065, 0, .422), .0018), ((-.077, 0, .436), .016),
        ((-.091, 0, .457), .025), ((-.102, 0, .480), .021),
        ((-.107, 0, .510), .0155), ((-.098, 0, .548), .0148),
        ((-.070, 0, .580), .0145), ((-.026, 0, .600), .014),
        ((.022, 0, .602), .0138), ((.068, 0, .582), .0135),
        ((.097, 0, .545), .0132), ((.108, 0, .496), .013),
        ((.105, 0, .425), .0128), ((.095, 0, .340), .012),
        ((.078, 0, .247), .0105), ((.053, 0, .153), .0085),
        ((.020, 0, .072), .005), ((-.014, 0, .028), .001),
        ((-.030, 0, .024), .00015),
    ]
    points, radii = [], []
    # Catmull-Rom sampling keeps the entire hook one smooth continuous tube.
    for i in range(len(controls) - 1):
        p0 = Vector(controls[max(0, i - 1)][0])
        p1 = Vector(controls[i][0])
        p2 = Vector(controls[i + 1][0])
        p3 = Vector(controls[min(len(controls) - 1, i + 2)][0])
        for j in range(10):
            t = j / 10
            p = .5 * ((2*p1) + (-p0+p2)*t + (2*p0-5*p1+4*p2-p3)*t*t + (-p0+3*p1-3*p2+p3)*t*t*t)
            points.append(p)
            blend = t*t*(3-2*t)
            radii.append(controls[i][1] * (1-blend) + controls[i+1][1] * blend)
    points.append(Vector(controls[-1][0]))
    radii.append(controls[-1][1])
    around = 48
    vertices, faces = [], []
    for i, (p, radius) in enumerate(zip(points, radii)):
        tangent = (points[min(i+1, len(points)-1)] - points[max(i-1, 0)]).normalized()
        side = Vector((0, 1, 0))
        normal = tangent.cross(side).normalized()
        for j in range(around):
            angle = j * 2 * math.pi / around
            v = p + radius * (side * math.cos(angle) + normal * math.sin(angle) * .87)
            vertices.append(tuple(v))
    for i in range(len(points)-1):
        for j in range(around):
            k = (j+1) % around
            faces.append((i*around+j, i*around+k, (i+1)*around+k, (i+1)*around+j))
    faces += [tuple(reversed(range(around))), tuple((len(points)-1)*around+j for j in range(around))]
    mesh = bpy.data.meshes.new('continuous_serpent_surface')
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    body = bpy.data.objects.new('authored_continuous_ear_serpent', mesh)
    bpy.context.collection.objects.link(body)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    uv = mesh.uv_layers.new(name='ScaleUV')
    for polygon in mesh.polygons:
        js = [mesh.loops[index].vertex_index % around for index in polygon.loop_indices]
        seam = 0 in js and around-1 in js
        for index in polygon.loop_indices:
            v = mesh.loops[index].vertex_index
            j, i = v % around, v // around
            uv.data[index].uv = ((around if seam and j == 0 else j) / around, i / (len(points)-1))

    gold = material('authored_ochre_scales', (.66, .42, .12))
    nodes, links = gold.node_tree.nodes, gold.node_tree.links
    shader = nodes.get('Principled BSDF')
    uv_node = nodes.new('ShaderNodeTexCoord')
    mapping = nodes.new('ShaderNodeVectorMath')
    mapping.operation = 'MULTIPLY'
    mapping.inputs[1].default_value = (14, 85, 1)
    links.new(uv_node.outputs['UV'], mapping.inputs[0])
    cells = nodes.new('ShaderNodeTexVoronoi')
    cells.voronoi_dimensions = '2D'
    cells.feature = 'DISTANCE_TO_EDGE'
    cells.inputs['Scale'].default_value = 1
    cells.inputs['Randomness'].default_value = .35
    links.new(mapping.outputs['Vector'], cells.inputs['Vector'])
    ramp = nodes.new('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = .015
    ramp.color_ramp.elements[0].color = (.37, .23, .055, 1)
    ramp.color_ramp.elements[1].position = .10
    ramp.color_ramp.elements[1].color = (.82, .60, .23, 1)
    links.new(cells.outputs['Distance'], ramp.inputs[0])
    links.new(ramp.outputs['Color'], shader.inputs['Base Color'])
    bump = nodes.new('ShaderNodeBump')
    bump.inputs['Strength'].default_value = .18
    bump.inputs['Distance'].default_value = .0005
    links.new(cells.outputs['Distance'], bump.inputs['Height'])
    links.new(bump.outputs['Normal'], shader.inputs['Normal'])
    body.data.materials.append(gold)

    dark = material('eyes_and_mouth', (.021, .014, .006), .25)
    # The eyes sit on opposite sides of the complete head, away from the snout.
    for side in (-1, 1):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, radius=1,
            location=(-.088, side*.0232, .449))
        eye = bpy.context.object
        eye.name = f'eye_{side}'
        eye.scale = (.0035, .0015, .003)
        eye.data.materials.append(dark)
        for p in eye.data.polygons:
            p.use_smooth = True
        curve(f'closed_mouth_{side}', [(-.066, side*.006, .423),
            (-.075, side*.014, .432), (-.088, side*.021, .442),
            (-.097, side*.019, .454)], .0005, dark)

    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True
    scene.render.resolution_x = scene.render.resolution_y = 1024
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = 'AgX'
    world = bpy.data.worlds.new('neutral')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (.35, .35, .35, 1)
    world.node_tree.nodes['Background'].inputs[1].default_value = .7
    scene.world = world
    for name, loc, energy, size in [('key', (1, -2, 2), 150, 2), ('fill', (-1, 1, 1), 80, 2)]:
        light = bpy.data.objects.new(name, bpy.data.lights.new(name, 'AREA'))
        scene.collection.objects.link(light)
        light.location = loc
        light.data.energy, light.data.shape, light.data.size = energy, 'DISK', size
        aim(light, (0, 0, .3))
    camera = bpy.data.objects.new('camera', bpy.data.cameras.new('camera'))
    scene.collection.objects.link(camera)
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = .72
    scene.camera = camera
    center = Vector((0, 0, .32))
    directions = {'34': (1, -2, .45), 'side': (1, -.35, 0), 'front': (0, -2, 0), 'back': (0, 2, 0)}
    for name, direction in directions.items():
        camera.location = center + Vector(direction)
        aim(camera, center)
        scene.render.filepath = str(out / f'view_{name}.png')
        bpy.ops.render.render(write_still=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out / 'authored-ear-serpent-reference.blend'))


if __name__ == '__main__':
    main()
