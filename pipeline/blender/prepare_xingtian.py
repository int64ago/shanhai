"""Normalize accepted native High by node transform; append independent fitted tools.

Usage: Blender --background --disable-autoexec --python prepare_xingtian.py --
       <native-high.glb> <out.glb> [--length 1] [--audit-out <report.json>]
The original source BIN, POSITION/NORMAL/UV/indices and PBR records are retained.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector
import xingtian_glb as glb

SOURCE_SHA = '7b8f311778d006197a22113b397193a651d66fb3a2de9801d1da2ede32622cc8'
# Measured on the actual accepted v7 High, in height-normalized Blender space.
# The 0.00015 radial clearance covers the subsequent mesh quantization error.
GRIPS = {
    -1: {'center': [-.4235339440598085, -.11207, .48946128860086735],
         'axis': [-.9500188673056612, 0, .31219249152288825], 'radius': .00350211215726779},
    1: {'center': [.4240070727238656, -.112788, .4873161380408577],
        'axis': [.9191023971657748, 0, .3940187603707805], 'radius': .007788171248246784},
}


def material(name, rgb, roughness, metallic=0, grain=False):
    mat = bpy.data.materials.new(name); mat.use_nodes = True
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Roughness'].default_value = roughness
    shader.inputs['Metallic'].default_value = metallic
    size = 512 if grain else 128
    v, u = np.mgrid[0:size, 0:size]/size
    rng = np.random.default_rng(517 if grain else 731)
    noise = rng.uniform(-1, 1, (size, size))
    if grain:
        phase = 2*np.pi*(u*31+.17*np.sin(v*13)+.06*np.sin(v*39+u*9))
        modulation = 1+.065*np.sin(phase)+.022*np.sin(phase*2.1)+noise*.014
    else:
        modulation = 1+.025*np.sin(u*47+np.cos(v*31))+noise*.018
    image = bpy.data.images.new(name+'_designed_color', width=size, height=size, alpha=True)
    pixels = np.ones((size, size, 4), dtype=np.float32)
    pixels[:, :, :3] = np.clip(np.asarray(rgb)[None, None, :]*modulation[:, :, None], 0, 1)
    image.pixels.foreach_set(pixels.reshape(-1)); image.pack()
    texture = mat.node_tree.nodes.new('ShaderNodeTexImage'); texture.image = image
    mat.node_tree.links.new(texture.outputs['Color'], shader.inputs['Base Color'])
    return mat


def cylinder(name, radius, depth, center, mat, parent, direction=(0, 0, 1)):
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=radius, depth=depth, location=center)
    obj = bpy.context.object; obj.name = name; obj.parent = parent
    obj.rotation_euler = Vector(direction).to_track_quat('Z', 'Y').to_euler()
    obj.data.materials.append(mat)
    bevel = obj.modifiers.new('Soft handmade edge', 'BEVEL'); bevel.width = radius*.12; bevel.segments = 2
    bpy.context.view_layer.objects.active = obj; bpy.ops.object.modifier_apply(modifier=bevel.name)
    for poly in obj.data.polygons: poly.use_smooth = True
    return obj


def mesh_object(name, vertices, faces, mat, parent, uv_map):
    mesh = bpy.data.meshes.new(name); mesh.from_pydata(vertices, [], faces); mesh.update()
    obj = bpy.data.objects.new(name, mesh); bpy.context.scene.collection.objects.link(obj)
    obj.parent = parent; mesh.materials.append(mat)
    bm = bmesh.new(); bm.from_mesh(mesh)
    # These are newly authored props; the native body is never imported here.
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces)); bm.to_mesh(mesh); bm.free()
    uv = mesh.uv_layers.new(name='Designed_color')
    for poly in mesh.polygons:
        for loop in poly.loop_indices:
            uv.data[loop].uv = uv_map(mesh.vertices[mesh.loops[loop].vertex_index].co)
    return obj


def build_props(path, length):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    wood = material('designed_warm_wood', (.60, .40, .21), .77, grain=True)
    bronze = material('designed_muted_bronze', (.61, .57, .36), .61, .65)
    leather = material('designed_dark_leather', (.25, .15, .08), .87)
    roots = {}
    for side, name in [(-1, 'shield_grip_origin'), (1, 'axe_grip_origin')]:
        root = bpy.data.objects.new(name, None); bpy.context.scene.collection.objects.link(root); roots[side] = root
    axe = roots[1]; shield = roots[-1]
    cylinder('Axe_wooden_shaft', GRIPS[1]['radius'], .53, (0, 0, .015), wood, axe)
    # No raised grip bindings: they would occupy the measured finger clearance.
    outline = [(-.022, .265), (.033, .263), (.105, .287)]
    for t in np.linspace(0, 1, 17)[1:]:
        point = (1-t)**3*np.array([.105, .287])+3*(1-t)**2*t*np.array([.178, .280])+3*(1-t)*t*t*np.array([.157, .151])+t**3*np.array([.102, .132])
        outline.append(tuple(point))
    outline += [(.033, .182), (-.022, .182)]
    vertices = [(x, sign*(.0025 if x > .10 else .011), z) for sign in [-1, 1] for x, z in outline]
    n = len(outline); faces = [tuple(reversed(range(n))), tuple(range(n, 2*n))]
    faces += [(i, (i+1) % n, (i+1) % n+n, i+n) for i in range(n)]
    blade = mesh_object('Axe_single_bronze_blade', vertices, faces, bronze, axe,
                        lambda p: ((p.x+.025)/.18, (p.z-.13)/.16))
    bpy.ops.object.select_all(action='DESELECT'); blade.select_set(True); bpy.context.view_layer.objects.active = blade
    bevel = blade.modifiers.new('Small blade edge rounding', 'BEVEL'); bevel.width = .0012; bevel.segments = 2
    bpy.ops.object.modifier_apply(modifier=bevel.name)
    seg, rings = 96, 8; vertices = []; faces = []
    for back in [False, True]:
        vertices.append((0, -.055+(.007 if back else 0), 0))
        for r in np.linspace(0, 1, rings+1)[1:]:
            for a in np.arange(seg)*2*np.pi/seg:
                vertices.append((.165*r*np.cos(a), -.035-.020*(1-r*r)+(.007 if back else 0), .215*r*np.sin(a)))
    layer = 1+rings*seg
    for offset in [0, layer]:
        faces += [(offset, offset+1+j, offset+1+(j+1) % seg) for j in range(seg)]
        for k in range(rings-1):
            for j in range(seg):
                a = offset+1+k*seg+j; b = offset+1+k*seg+(j+1) % seg
                c = offset+1+(k+1)*seg+(j+1) % seg; d = offset+1+(k+1)*seg+j
                faces.append((a, b, c, d))
    for j in range(seg):
        a = 1+(rings-1)*seg+j; b = 1+(rings-1)*seg+(j+1) % seg
        faces.append((a, b, b+layer, a+layer))
    board = mesh_object('Shield_convex_wood', vertices, faces, wood, shield,
                        lambda p: ((p.x/.165+1)/2, (p.z/.215+1)/2))
    for poly in board.data.polygons: poly.use_smooth = True
    cylinder('Shield_back_handle', GRIPS[-1]['radius'], .13, (0, 0, 0), wood, shield)
    for z in [-.065, .065]:
        cylinder('Shield_handle_standoff', .010, .047, (0, -.0235, z), leather, shield, (0, 1, 0))
    for side, root in roots.items():
        grip = GRIPS[side]; axis = Vector(grip['axis']); y = Vector((0, 1 if side == -1 else -1, 0))
        root.location = Vector(grip['center'])*length
        root.rotation_mode = 'QUATERNION'; root.rotation_quaternion = Matrix((y.cross(axis), y, axis)).transposed().to_quaternion()
        root.scale = (length,)*3
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB', use_selection=True, export_animations=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source'); parser.add_argument('out')
    parser.add_argument('--length', type=float, default=1.)
    parser.add_argument('--audit-out')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    if not math.isfinite(args.length) or args.length <= 0: raise ValueError('Invalid body length')
    digest = hashlib.sha256(Path(args.source).read_bytes()).hexdigest()
    if digest != SOURCE_SHA: raise ValueError('Source differs from the reviewed native v7 High')
    document, binary = glb.load(args.source); original = copy.deepcopy(document); original_binary = bytes(binary)
    assert not document.get('skins') and not document.get('animations')
    worlds = glb.world_matrices(document); points = []
    for index, node in enumerate(document['nodes']):
        if 'mesh' not in node: continue
        for primitive in document['meshes'][node['mesh']]['primitives']:
            p = glb.array(document, binary, primitive['attributes']['POSITION'])
            points.append((p@worlds[index][:3, :3].T+worlds[index][:3, 3])@glb.C.T)
    body_nodes = [node for node in document['nodes'] if 'mesh' in node]
    assert len(body_nodes) == 1, 'Reviewed v7 source must contain one body mesh'
    body_nodes[0]['name'] = 'xingtian_native_high_body'
    points = np.concatenate(points); lo = points.min(0); hi = points.max(0)
    scale = args.length/(hi[2]-lo[2]); translation = np.array([-(lo[0]+hi[0])/2, -(lo[1]+hi[1])/2, -lo[2]])*scale
    transform = np.eye(4); transform[:3, :3] *= scale; transform[:3, 3] = glb.C.T@translation
    scene = document['scenes'][document.get('scene', 0)]; source_roots = list(scene['nodes'])
    normalization = len(document['nodes'])
    document['nodes'].append({'name': 'xingtian_native_normalization', 'matrix': transform.T.reshape(-1).tolist(), 'children': source_roots})
    scene['nodes'] = [normalization]
    with tempfile.TemporaryDirectory(prefix='xingtian-props-') as work:
        props_path = Path(work)/'props.glb'; build_props(props_path, args.length)
        props, props_binary = glb.load(props_path)
        scene['nodes'] += glb.merge_static(document, binary, props, props_binary)
    assert binary[:len(original_binary)] == original_binary
    for key in ['meshes', 'accessors', 'bufferViews', 'materials', 'textures', 'images', 'samplers']:
        assert document.get(key, [])[:len(original.get(key, []))] == original.get(key, []), key
    report = {'sourceSHA256': digest, 'originalBinPrefixBytes': len(original_binary),
              'originalSourceBinPrefixExact': True, 'originalGeometryPBRRecordsExact': True,
              'normalizationScale': scale, 'normalizationTranslationBlender': translation.tolist(),
              'bodyLength': args.length, 'gripsHeightNormalized': {str(k): v for k, v in GRIPS.items()},
              'localDesignedProps': True, 'nativeGeometryEdited': False, 'nativeTextureEdited': False}
    document.setdefault('extras', {})['xingtianPreparation'] = report
    glb.save(args.out, document, binary)
    if args.audit_out:
        audit_path = Path(args.audit_out)
        if not audit_path.is_absolute(): audit_path = Path(__file__).resolve().parents[2]/audit_path
        audit_path.parent.mkdir(parents=True, exist_ok=True); audit_path.write_text(json.dumps(report, indent=2))
    print('LANDMARKS', json.dumps(report))
    print('EXPORTED', args.out)


if __name__ == '__main__': main()
