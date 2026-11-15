"""Bounded scalp fairing and local native-fur reprojection for the reviewed Lu High.

No remesh, deletion, API, rigging, or edits to the source/reference files.
All unchanged faces retain their original UVs and original PBR material.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

sys.dont_write_bytecode = True
import bpy
import bmesh
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

ROOT = Path(__file__).resolve().parents[2]
SOURCE_SHA = '390ffe36efa5722c0cec3a89c881d2c54f66711afc60d75b46013a3d60867bd9'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def smooth(a, b, x):
    t = np.clip((x-a)/(b-a), 0, 1)
    return t*t*(3-2*t)


def load(source):
    assert sha(source) == SOURCE_SHA
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source), disable_bone_shape=True)
    objects = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    assert len(objects) == 1
    obj = objects[0]
    mesh = obj.data
    p = np.array([list(obj.matrix_world @ v.co) for v in mesh.vertices])
    source_normals = np.array([list((obj.matrix_world.to_3x3().inverted().transposed() @ n.vector).normalized()) for n in mesh.corner_normals])
    lo, hi = p.min(0), p.max(0)
    scale = 1/float(max(hi-lo))
    offset = np.array([-(lo[0]+hi[0])/2, -(lo[1]+hi[1])/2, -lo[2]])*scale
    p = p*scale+offset
    obj.matrix_world = Matrix.Identity(4)
    mesh.vertices.foreach_set('co', p.astype(np.float32).reshape(-1))
    mesh.update()
    tri = np.array([list(f.vertices) for f in mesh.polygons], dtype=np.int32)
    assert tri.shape == (50000, 3)
    uv = np.array([list(v.uv) for v in mesh.uv_layers.active.data])
    vertex_uv = np.zeros((len(p), 2))
    vertex_uv[tri.reshape(-1)] = uv
    mesh.normals_split_custom_set(source_normals.tolist())
    return obj, p, tri, vertex_uv, source_normals, dict(scale=scale, offset=offset.tolist())


def weights(p):
    x, y, z = p.T
    # Eyes/brows and lateral ears are excluded; the rim has a C1 falloff.
    # Native image-ray picks: eye Z=.542, upper lid=.559, ear=.566;
    # circular repair cap=.584 and central top block=.602.
    scalp = (1-smooth(.062, .078, abs(x)))*smooth(-.42, -.402, y)*(1-smooth(-.285, -.255, y))*smooth(.571, .586, z)
    rump = (1-smooth(.075, .115, abs(x)))*smooth(.17, .205, y)*smooth(.235, .275, z)*(1-smooth(.48, .515, z))
    # Native scale-bearing tail, cross section and entire pointed tip protected.
    tail = (y > .265) | ((y > .245) & (abs(x) < .025) & (z > .385) & (z < .425))
    rump[tail] = 0
    return scalp, rump


def root_geometry_weights(p, material_weights):
    x, y, z = p.T
    return material_weights*smooth(.20,.23,y)*(1-smooth(.245,.267,y))*smooth(.285,.31,z)*(1-smooth(.43,.46,z))*(1-smooth(.045,.075,abs(x)))


def render(source, out, normalized=False, label='candidate'):
    if normalized:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=str(source), disable_bone_shape=True)
    else:
        load(source)
    out.mkdir(parents=True, exist_ok=False)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 32
    scene.cycles.use_denoising = True
    scene.render.resolution_x = scene.render.resolution_y = 768
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'AgX'
    world = bpy.data.worlds.new('bounded_repair_review_world')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (.55, .57, .60, 1)
    world.node_tree.nodes['Background'].inputs[1].default_value = .8
    scene.world = world
    for index, (location, energy) in enumerate([((2,-3,4),240),((-3,1,2),210),((1,3,3),180)]):
        light = bpy.data.objects.new('repair_softbox_'+str(index), bpy.data.lights.new('repair_softbox_'+str(index), 'AREA'))
        scene.collection.objects.link(light)
        light.location = location
        light.rotation_euler = (Vector((0,0,.4))-light.location).to_track_quat('-Z','Y').to_euler()
        light.data.energy, light.data.size = energy, 3
    gray = bpy.data.materials.new('neutral_clay')
    gray.use_nodes = True
    gray.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = (.42,.42,.42,1)
    gray.node_tree.nodes.get('Principled BSDF').inputs['Roughness'].default_value = .8
    specs = [('scalp',(0,-.36,.54),(1,-.4,.5),.25), ('rump',(0,.24,.40),(0,1,.15),.26), ('scalp_front',(0,-.37,.55),(0,-1,.25),.24), ('rump_side',(.04,.24,.40),(1,.3,.1),.29)]
    images = []
    for mode in ('pbr', 'clay'):
        scene.view_layers[0].material_override = gray if mode == 'clay' else None
        for name, target, direction, size in specs:
            target = Vector(target)
            camera = bpy.data.objects.new('repair_camera', bpy.data.cameras.new('repair_camera'))
            scene.collection.objects.link(camera)
            camera.location = target+Vector(direction).normalized()*3
            camera.rotation_euler = (target-camera.location).to_track_quat('-Z','Y').to_euler()
            camera.data.type, camera.data.ortho_scale = 'ORTHO', size
            scene.camera = camera
            filename = f'{label}_{name}_{mode}.png'
            scene.render.filepath = str(out/filename)
            bpy.ops.render.render(write_still=True)
            images.append(filename)
            bpy.data.objects.remove(camera, do_unlink=True)
    (out/'images.json').write_text(json.dumps(dict(source=str(source), sourceSha256=sha(source), images=images, actualExport=normalized, imageEdits=False), indent=2)+'\n')


def bake_local_atlas(obj, material, selected_faces, out):
    mesh = obj.data
    face_ids = mesh.attributes.new('_RepairSourceFace', 'INT', 'FACE')
    face_ids.data.foreach_set('value', np.arange(len(mesh.polygons),dtype=np.int32))
    vertex_ids = mesh.attributes.new('_RepairSourceVertex', 'INT', 'POINT')
    vertex_ids.data.foreach_set('value', np.arange(len(mesh.vertices),dtype=np.int32))
    patch_mesh = mesh.copy()
    bm = bmesh.new()
    bm.from_mesh(patch_mesh)
    face_layer = bm.faces.layers.int['_RepairSourceFace']
    chosen = set(selected_faces)
    bmesh.ops.delete(bm,geom=[f for f in bm.faces if f[face_layer] not in chosen],context='FACES')
    bm.to_mesh(patch_mesh)
    bm.free()
    patch_mesh.materials.clear()
    patch_mesh.materials.append(material)
    for face in patch_mesh.polygons:
        face.material_index = 0
    patch = bpy.data.objects.new('bounded_fur_bake_proxy',patch_mesh)
    bpy.context.collection.objects.link(patch)
    atlas = patch_mesh.uv_layers.new(name='LocalRepairAtlas')
    bpy.ops.object.select_all(action='DESELECT')
    patch.select_set(True)
    bpy.context.view_layer.objects.active = patch
    patch_mesh.uv_layers.active = atlas
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66),island_margin=.012)
    bpy.ops.object.mode_set(mode='OBJECT')
    atlas = patch_mesh.uv_layers['LocalRepairAtlas']
    image = bpy.data.images.new('lu_high_local_fur_atlas',width=2048,height=2048,alpha=False)
    target = material.node_tree.nodes.new('ShaderNodeTexImage')
    target.image = image
    material.node_tree.nodes.active = target
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 1
    scene.render.bake.margin = 12
    bpy.ops.object.bake(type='EMIT')
    image.filepath_raw = str(out/'local-fur-atlas.png')
    image.file_format = 'PNG'
    image.save()
    image.pack()
    final_uv = mesh.uv_layers.new(name='LocalRepairAtlas')
    source_faces = patch_mesh.attributes['_RepairSourceFace'].data
    source_vertices = patch_mesh.attributes['_RepairSourceVertex'].data
    for face in patch_mesh.polygons:
        original = mesh.polygons[source_faces[face.index].value]
        ids = [source_vertices[patch_mesh.loops[k].vertex_index].value for k in face.loop_indices]
        original_ids = [mesh.loops[k].vertex_index for k in original.loop_indices]
        shift = next(k for k in range(3) if original_ids[k:]+original_ids[:k] == ids)
        for k, loop_index in enumerate(face.loop_indices):
            final_uv.data[original.loop_indices[(k+shift)%3]].uv = atlas.data[loop_index].uv
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    bsdf.inputs['Roughness'].default_value = .78
    tex = nodes.new('ShaderNodeTexImage')
    tex.image = image
    uvnode = nodes.new('ShaderNodeUVMap')
    uvnode.uv_map = 'LocalRepairAtlas'
    links.new(uvnode.outputs['UV'],tex.inputs['Vector'])
    links.new(tex.outputs['Color'],bsdf.inputs['Base Color'])
    links.new(bsdf.outputs['BSDF'],output.inputs['Surface'])
    mesh.uv_layers.active_index = 0
    mesh.uv_layers[0].active_render = True
    mesh.attributes.remove(face_ids)
    mesh.attributes.remove(vertex_ids)
    bpy.data.objects.remove(patch,do_unlink=True)
    bpy.data.meshes.remove(patch_mesh)


def repair(source, out):
    out.mkdir(parents=True, exist_ok=False)
    obj, p, tri, vertex_uv, source_normals, normalization = load(source)
    mesh = obj.data
    original_uv = np.array([list(v.uv) for v in mesh.uv_layers.active.data])
    scalp, rump = weights(p)
    root_geometry = root_geometry_weights(p,rump)
    geometry_weights = np.maximum(scalp,root_geometry)
    unique, inv = np.unique(p, axis=0, return_inverse=True)
    u_scalp, u_rump = weights(unique)
    u_root = root_geometry_weights(unique,u_rump)
    edges = np.sort(np.vstack([inv[tri[:,[0,1]]],inv[tri[:,[1,2]]],inv[tri[:,[2,0]]]]), axis=1)
    edges = np.unique(edges[edges[:,0] != edges[:,1]], axis=0)
    degree = np.bincount(edges.reshape(-1), minlength=len(unique))
    degree = np.maximum(degree, 1)
    q = unique.copy()
    for step in range(140):
        total = np.zeros_like(q)
        np.add.at(total, edges[:,0], q[edges[:,1]])
        np.add.at(total, edges[:,1], q[edges[:,0]])
        amount = .5*u_scalp+(.35*u_root if step<80 else 0)
        q += amount[:,None]*(total/degree[:,None]-q)
        displacement = q-unique
        distance = np.linalg.norm(displacement, axis=1)
        limit = np.where(u_scalp>0,.022,.0038)
        q = unique+displacement*np.minimum(1, limit/np.maximum(distance, 1e-10))[:,None]
    candidate = q[inv]
    changed = np.linalg.norm(candidate-p, axis=1) > 1e-10
    assert np.all(geometry_weights[changed] > 0)
    assert np.array_equal(candidate[geometry_weights == 0], p[geometry_weights == 0])
    assert not np.any(changed[(abs(p[:,0]) > .1) | (p[:,2] < .20) | (p[:,1] > .267)])
    mesh.vertices.foreach_set('co', candidate.astype(np.float32).reshape(-1))
    mesh.update()
    # Recompute only the permitted scalp directions on an exact-position graph.
    face_normals = np.cross(candidate[tri[:,1]]-candidate[tri[:,0]], candidate[tri[:,2]]-candidate[tri[:,0]])
    u_normal = np.zeros_like(unique)
    for k in range(3):
        np.add.at(u_normal, inv[tri[:,k]], face_normals)
    u_normal /= np.maximum(np.linalg.norm(u_normal, axis=1), 1e-12)[:,None]
    normal_mix = smooth(0, .15, geometry_weights[tri.reshape(-1)])[:,None]
    normals = source_normals*(1-normal_mix)+u_normal[inv[tri.reshape(-1)]]*normal_mix
    normals /= np.maximum(np.linalg.norm(normals, axis=1), 1e-12)[:,None]
    for face in mesh.polygons:
        face.use_smooth = True
    mesh.normals_split_custom_set(normals.tolist())
    # The actual High's clean lateral torso is the only fur color donor.
    donor_domain = (p[:,0] < -.04) & (p[:,1] > -.10) & (p[:,1] < .17) & (p[:,2] > .30) & (p[:,2] < .54)
    donor_ids = np.flatnonzero(np.all(donor_domain[tri], axis=1))
    donor = BVHTree.FromPolygons([Vector(v) for v in p], tri[donor_ids].tolist(), all_triangles=True)
    projection = mesh.uv_layers.new(name='LocalFurProjection')
    blend = mesh.color_attributes.new(name='LocalFurMix', type='FLOAT_COLOR', domain='CORNER')
    # Explicit UV node on donor samples; original active/render UV stays intact.
    mesh.uv_layers.active_index = 0
    mesh.uv_layers[0].active_render = True
    def project(point, region):
        if region == 'scalp':
            sy, sz = .04+.65*point.x, .43+.45*(point.y+.35)
        else:
            sy, sz = .05+.65*point.x, .43+.45*(point.z-.39)
        hit, normal, index, distance = donor.ray_cast(Vector((-.5,sy,sz)), Vector((1,0,0)))
        if hit is None:
            hit, normal, index, distance = donor.find_nearest(Vector((-.1,sy,sz)))
        assert hit is not None
        ids = tri[donor_ids[index]]
        return barycentric_transform(hit, *[Vector(p[k]) for k in ids], *[Vector((vertex_uv[k,0],vertex_uv[k,1],0)) for k in ids]).xy
    original = mesh.materials[0]
    image = next(n.image for n in original.node_tree.nodes if n.type == 'TEX_IMAGE' and 'diffuse' in n.image.name)
    local = bpy.data.materials.new('lu_high_bounded_native_fur')
    local.use_nodes = True
    nodes, links = local.node_tree.nodes, local.node_tree.links
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    emit = nodes.new('ShaderNodeEmission')
    def native_texture(layer):
        tex = nodes.new('ShaderNodeTexImage')
        tex.image = image
        uvnode = nodes.new('ShaderNodeUVMap')
        uvnode.uv_map = layer
        links.new(uvnode.outputs['UV'],tex.inputs['Vector'])
        return tex.outputs['Color']
    attr = nodes.new('ShaderNodeVertexColor')
    attr.layer_name = 'LocalFurMix'
    mix = nodes.new('ShaderNodeMixRGB')
    links.new(attr.outputs['Color'],mix.inputs[0])
    links.new(native_texture(mesh.uv_layers[0].name),mix.inputs[1])
    links.new(native_texture('LocalFurProjection'),mix.inputs[2])
    links.new(mix.outputs['Color'],emit.inputs['Color'])
    links.new(emit.outputs['Emission'],output.inputs['Surface'])
    mesh.materials.append(local)
    local_faces = []
    for face in mesh.polygons:
        ids = tri[face.index]
        scalp_weight = smooth(0, .20, scalp[ids])
        rump_weight = smooth(0, .20, rump[ids])
        amount = np.maximum(scalp_weight, rump_weight)
        if not np.any(amount > 0):
            continue
        region = 'scalp' if np.max(scalp_weight) > 0 else 'rump'
        values = [project(Vector(p[k]), region) for k in ids]
        if max((u-v).length for u in values for v in values) > .035:
            values = [project(Vector(p[ids].mean(0)), region)]*3
        for loop_index, value, weight in zip(face.loop_indices, values, amount):
            projection.data[loop_index].uv = value
            blend.data[loop_index].color = (weight,weight,weight,1)
        face.material_index = 1
        local_faces.append(face.index)
    bake_local_atlas(obj,local,local_faces,out)
    assert np.array_equal(original_uv, np.array([list(v.uv) for v in mesh.uv_layers[0].data]))
    assert np.array_equal(tri, np.array([list(f.vertices) for f in mesh.polygons]))
    target = out/'lu_fish_high_local_repair.glb'
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(filepath=str(target), export_format='GLB', use_selection=True, export_animations=False, export_normals=True, export_texcoords=True, export_materials='EXPORT', export_yup=True, export_attributes=False)
    np.savez_compressed(out/'repair-audit-input.npz', sourcePositions=p, candidatePositions=candidate, triangles=tri, sourceUv=vertex_uv, scalpWeights=scalp, rumpWeights=rump, geometryWeights=geometry_weights, rootGeometryWeights=root_geometry, localFaces=np.array(local_faces))
    manifest = dict(status='PENDING_BEFORE_AFTER_CLAY_PBR_READ', source=str(source), sourceSha256=sha(source), candidate=str(target), candidateSha256=sha(target), normalization=normalization, sourceTriangles=len(tri), sourceVertices=len(p), topologyChanged=False, originalUvChanged=False, originalPbrMaterialPreserved=True, scalpMovedVertices=int((changed & (scalp>0)).sum()), scalpMaximumDisplacement=float(np.linalg.norm(candidate-p,axis=1)[scalp>0].max()), rumpGeometryChanged=True, rumpMovedVertices=int((changed & (root_geometry>0)).sum()), rumpMaximumDisplacement=float(np.linalg.norm(candidate-p,axis=1)[root_geometry>0].max()), localFurAtlas='local-fur-atlas.png', localMaterialFaces=len(local_faces), geometryRoi='scalp: absX<.078, -.42<Y<-.255, Z>.571, image-ray calibrated above lids/ears; rump fine-ridge only: absX<.075, .20<Y<.267, .285<Z<.46 and tail excluded, displacement<=.0038 normalized units', materialRoi='same scalp plus absX<.115, .17<Y<=.265, .235<Z<.515; central scale-bearing tail root excluded', wholeBeastAccepted=False, riggingStarted=False, apiCalls=0)
    (out/'repair-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('BOUNDED_HIGH_REPAIR '+json.dumps(manifest), flush=True)


def audit(source, candidate, out):
    from collections import Counter
    from mathutils.kdtree import KDTree
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from audit_lu_fish_v8_reference import read, array, cyclic, A
    assert sha(source) == SOURCE_SHA
    record = np.load(candidate.parent/'repair-audit-input.npz', allow_pickle=False)
    p, planned, tri, uv = [record[k] for k in ('sourcePositions','candidatePositions','triangles','sourceUv')]
    geometry = record['geometryWeights'] if 'geometryWeights' in record.files else record['scalpWeights']
    local_faces = set(map(int, record['localFaces']))
    _, canonical = np.unique(np.column_stack([p,uv]), axis=0, return_inverse=True)
    kd = KDTree(len(planned))
    for i, point in enumerate(planned):
        kd.insert(Vector(point), i)
    kd.balance()
    source_json, source_bin = read(source)
    data, binary = read(candidate)
    actual, actual_material_zero = Counter(), Counter()
    maximum = maximum_protected = maximum_uv = 0.
    unmatched = 0
    actual_triangles = 0
    for primitive in data['meshes'][0]['primitives']:
        q = array(data,binary,primitive['attributes']['POSITION']).astype(float)@A.T
        tex = array(data,binary,primitive['attributes']['TEXCOORD_0']).astype(float)
        tex[:,1] = 1-tex[:,1]  # Imported Blender UV convention used by audit-input.
        faces = array(data,binary,primitive['indices']).reshape(-1,3)
        mapping = np.full(len(q), -1, dtype=np.int64)
        for i, point in enumerate(q):
            valid = [(j,d) for _,j,d in kd.find_range(Vector(point),1e-6) if np.max(abs(uv[j]-tex[i]))<2e-6]
            if not valid:
                unmatched += 1
                continue
            j, distance = min(valid, key=lambda item:item[1])
            mapping[i] = canonical[j]
            maximum = max(maximum,float(distance))
            maximum_uv = max(maximum_uv,float(np.max(abs(uv[j]-tex[i]))))
            if geometry[j] == 0:
                maximum_protected = max(maximum_protected,float(np.linalg.norm(point-p[j])))
        for face in faces:
            ids = mapping[face]
            if np.all(ids>=0):
                actual[cyclic(ids)] += 1
                if primitive.get('material') == 0:
                    actual_material_zero[cyclic(ids)] += 1
        actual_triangles += len(faces)
    expected = Counter(cyclic(canonical[face]) for face in tri)
    protected_material = Counter(cyclic(canonical[face]) for i,face in enumerate(tri) if i not in local_faces)
    def pbr_signature(d,b):
        mat = d['materials'][0]
        pbr = mat.get('pbrMetallicRoughness',{})
        result = dict(baseColorFactor=pbr.get('baseColorFactor',[1,1,1,1]),metallicFactor=pbr.get('metallicFactor',1),roughnessFactor=pbr.get('roughnessFactor',1),alphaMode=mat.get('alphaMode','OPAQUE'),doubleSided=mat.get('doubleSided',False),emissiveFactor=mat.get('emissiveFactor',[0,0,0]))
        for label, info in [('baseColor',pbr.get('baseColorTexture')),('metallicRoughness',pbr.get('metallicRoughnessTexture')),('normal',mat.get('normalTexture')),('occlusion',mat.get('occlusionTexture'))]:
            if info is None:
                result[label] = None
                continue
            image = d['images'][d['textures'][info['index']]['source']]
            view = d['bufferViews'][image['bufferView']]
            start = view.get('byteOffset',0)
            result[label] = dict(imageSha256=hashlib.sha256(b[start:start+view['byteLength']]).hexdigest(),texCoord=info.get('texCoord',0),scale=info.get('scale',1),strength=info.get('strength',1))
        return result
    original_pbr, actual_pbr = pbr_signature(source_json,source_bin), pbr_signature(data,binary)
    result = dict(candidate=str(candidate),candidateSha256=sha(candidate),sourceSha256=sha(source),expectedTriangles=len(tri),actualTriangles=actual_triangles,unmatchedExportVertices=unmatched,missingOrChangedPlannedOrientedTriangles=sum((expected-actual).values()),unexpectedOrientedTriangles=sum((actual-expected).values()),protectedPbrFaceCount=sum(protected_material.values()),missingOrMaterialChangedProtectedTriangles=sum((protected_material-actual_material_zero).values()),maximumPlannedPositionError=maximum,maximumOutsideGeometryRoiPositionError=maximum_protected,maximumOriginalUvError=maximum_uv,originalPbrSignaturePreserved=original_pbr==actual_pbr,originalPbrSignature=original_pbr,exportedOriginalPbrSignature=actual_pbr,onlyApprovedRoiGeometryMoved=bool(np.array_equal(p[geometry==0],planned[geometry==0])),limits='Oriented topology/UV, planned local geometry and original-material audit. Not a visual or self-intersection certificate.')
    result['pass'] = all([unmatched==0,expected==actual,not (protected_material-actual_material_zero),original_pbr==actual_pbr,result['onlyApprovedRoiGeometryMoved'],maximum_protected<1e-6,maximum_uv<2e-6])
    (out/'actual-export-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print('ACTUAL_LOCAL_REPAIR_AUDIT '+json.dumps(result),flush=True)
    assert result['pass'], 'Actual exported repair failed the preservation audit'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--phase', choices=['repair','before','after','audit'], default='repair')
    parser.add_argument('--candidate')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    source, out = Path(args.source).resolve(), Path(args.output_dir).resolve()
    assert source.is_relative_to(ROOT/'raw') and out.is_relative_to(ROOT/'raw/_build')
    if args.phase == 'repair':
        repair(source,out)
    elif args.phase == 'audit':
        candidate = Path(args.candidate).resolve()
        assert candidate.is_relative_to(ROOT/'raw')
        audit(source,candidate,out)
    else:
        render(source,out,normalized=args.phase=='after',label=args.phase)


if __name__ == '__main__':
    main()
