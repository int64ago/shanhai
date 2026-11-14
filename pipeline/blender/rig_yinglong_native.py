"""Offline, source-calibrated native Yinglong rig. No geometry reconstruction.

Run from the trusted worktree, never from a downloaded asset directory:
  blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
    --python pipeline/blender/rig_yinglong_native.py -- SOURCE.glb NEW_OUTPUT \
    --calibration REVIEWED.json --accepted-source-sha256 SHA256
Use --inspect before calibration; --calibrate emits geometry-only mask diagnostics.
Outputs are confined to raw/_build. The accepted source is for rigging only;
this recipe does not approve production anatomy, compression, or runtime release.
"""
import argparse
import hashlib
import json
import math
import runpy
import shutil
import struct
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
TRUSTED = Path(__file__).resolve().parent
ROOT = TRUSTED.parents[1]
sys.path.insert(0, str(TRUSTED))
import bpy
import numpy as np
from mathutils import Matrix, Vector
import rig_quadruped as base
from rig_jiaochong_native import native_fingerprint
from rig_zhuyan_native import render_view

FPS = 60
SPAN = 3.2
ELEVATION = .65
DURATIONS = {'idle': 6., 'walk': 4., 'special': 6.}
COORDINATES = 'Blender X/right Y/back Z/up; wingspan3.2m; native minimumZ baked to0.65m'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def array_sha(values, dtype='<f4'):
    return hashlib.sha256(np.asarray(values, dtype=dtype).tobytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n')


def smooth(x):
    x = np.clip(x, 0., 1.)
    return x*x*x*(10+x*(-15+6*x))


def load_source(source):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source), disable_bone_shape=True)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    assert len(meshes) == 1 and not any(o.type == 'ARMATURE' for o in bpy.context.scene.objects)
    obj = meshes[0]
    assert not obj.modifiers and not obj.data.shape_keys and not obj.vertex_groups
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    assert obj.matrix_world.to_3x3().determinant() > 0
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for other in list(bpy.context.scene.objects):
        if other is not obj:
            bpy.data.objects.remove(other, do_unlink=True)
    before = native_fingerprint(obj)
    original = np.array([tuple(v.co) for v in obj.data.vertices])
    normals = np.array([tuple(n.vector) for n in obj.data.corner_normals])
    assert np.isfinite(original).all() and np.isfinite(normals).all()
    lo, hi = original.min(axis=0), original.max(axis=0)
    scale = SPAN/(hi[0]-lo[0])
    origin = np.array([(lo[0]+hi[0])/2, (lo[1]+hi[1])/2, lo[2]])
    translation = np.array([0., 0., ELEVATION])
    transform = Matrix.Translation(Vector(translation)) @ Matrix.Scale(scale, 4) @ Matrix.Translation(-Vector(origin))
    obj.data.transform(transform)
    obj.data.update()
    obj.data.normals_split_custom_set(normals.tolist())
    after = native_fingerprint(obj)
    assert {k: v for k, v in before.items() if k != 'cornerNormalsSha256'} == {k: v for k, v in after.items() if k != 'cornerNormalsSha256'}
    positions = np.array([tuple(v.co) for v in obj.data.vertices])
    error = float(np.abs(positions-((original-origin)*scale+translation)).max())
    normal_error = float(np.abs(np.array([tuple(n.vector) for n in obj.data.corner_normals])-normals).max())
    assert error < 4e-7 and normal_error < 6e-4, (error, normal_error)
    assert np.max(np.abs(np.array(obj.matrix_world)-np.eye(4))) < 1e-6
    obj.name = 'yinglong_native_whole'
    return obj, positions, {
        'sourceBounds': [lo.tolist(), hi.tolist()], 'positiveUniformScale': scale,
        'decodedOrigin': origin.tolist(), 'permanentElevationBakedTranslation': translation.tolist(),
        'meshObjectScale': list(obj.scale), 'geometryReconstruction': False,
        'sourceFingerprint': before, 'normalizedFingerprint': after,
        'normalizationMaxPositionError': error, 'normalizationMaxNormalComponentError': normal_error,
        'normalTolerance': 'Blender custom-normal octahedral codec: max component error <6e-4; no recomputation',
        'decodedRestPositionsSha256': array_sha(original), 'restPositionsSha256': array_sha(positions),
    }


def adjacency(obj, points):
    """Native edges and exact decoded seam duplicates; never connect nearby surfaces."""
    graph = [set() for _ in points]
    for edge in obj.data.edges:
        a, b = edge.vertices
        graph[a].add(b)
        graph[b].add(a)
    seam = {}
    for i, p in enumerate(points):
        key = tuple(np.round(p, 6))
        if key in seam:
            j = seam[key]
            graph[i].add(j)
            graph[j].add(i)
        else:
            seam[key] = i
    return graph


def components(graph, allowed):
    remaining = set(np.flatnonzero(allowed).tolist())
    result = []
    while remaining:
        seed = min(remaining)
        found, pending = {seed}, [seed]
        remaining.remove(seed)
        while pending:
            for j in graph[pending.pop()]:
                if j in remaining:
                    remaining.remove(j)
                    found.add(j)
                    pending.append(j)
        result.append(sorted(found))
    return sorted(result, key=len, reverse=True)


def describe(points, ids=None):
    p = points if ids is None else points[ids]
    return {'count': len(p), 'min': p.min(axis=0).tolist(), 'max': p.max(axis=0).tolist()}


def inspect(obj, points, out):
    graph = adjacency(obj, points)
    comps = components(graph, np.ones(len(points), dtype=bool))
    report = {'bounds': describe(points), 'components': [dict(seed=c[0], **describe(points, c)) for c in comps]}
    report['xSlices'] = []
    for x in np.arange(0, 1.61, .08):
        ids = np.flatnonzero((np.abs(points[:, 0]) >= x) & (np.abs(points[:, 0]) < x+.08))
        if len(ids):
            report['xSlices'].append(dict(xRange=[float(x), float(x+.08)], **describe(points, ids)))
    report['centralYSlices'] = []
    for y in np.arange(-1.56, 1.57, .08):
        ids = np.flatnonzero((points[:, 1] >= y) & (points[:, 1] < y+.08) & (np.abs(points[:, 0]) < .19))
        if len(ids):
            report['centralYSlices'].append(dict(yRange=[float(y), float(y+.08)], **describe(points, ids)))
    np.savez(out/'native-probe.npz', positions=points, edges=np.array([tuple(e.vertices) for e in obj.data.edges]), triangles=np.array([tuple(p.vertices) for p in obj.data.polygons]), normals=np.array([tuple(n.vector) for n in obj.data.corner_normals]), uv=np.array([tuple(v.uv) for v in obj.data.uv_layers.active.data]))
    dump(out/'probe.json', report)
    print('YINGLONG_PROBE', json.dumps(report), flush=True)


def masks_from_calibration(obj, points, cal, review=True):
    graph = adjacency(obj, points)
    masks = {}
    for name, spec in cal['cuts'].items():
        allowed = np.ones(len(points), dtype=bool)
        for plane in spec['planes']:
            allowed &= points @ np.array(plane['normal']) <= plane['offset']
        comps = components(graph, allowed)
        ids = sorted(i for c in comps for i in c)
        # Seed every disconnected clipped native shell, including tiny native fragments.
        seeds = [c[0] for c in comps]
        if review:
            assert spec['seeds'] == seeds and spec['count'] == len(ids), name
            assert spec['indicesSha256'] == array_sha(ids, '<u4'), name
        else:
            spec.update(seeds=seeds, count=len(ids), indicesSha256=array_sha(ids, '<u4'))
        masks[name] = ids
    wings = set(masks['wing_l']) | set(masks['wing_r'])
    assert not set(masks['wing_l']) & set(masks['wing_r'])
    masks['trunk'] = [i for i in range(len(points)) if i not in wings]
    assert set(masks['head']) <= set(masks['trunk'])
    masks['body'] = [i for i in masks['trunk'] if i not in set(masks['head'])]
    for side in ('l', 'r'):
        ids = masks['wing_'+side]
        masks['wing_root_'+side] = [i for i in ids if abs(points[i, 0]) < .38]
        masks['wing_tip_'+side] = [i for i in ids if abs(points[i, 0]) > 1.26]
        # Native trailing vanes separated from the measured leading spar by a
        # geometry cut. Components are independent of all rig/weight assignments.
        knots = np.array(cal['landmarks']['wings'][side])
        top = np.interp(np.abs(points[:, 0]), np.abs(knots[:, 0]), knots[:, 2])
        allowed = np.zeros(len(points), dtype=bool)
        allowed[ids] = True
        allowed &= points[:, 2] < top-.18
        feather = components(graph, allowed)
        patches = [c for c in feather if len(c) >= 35]
        for n, c in enumerate(patches):
            masks[f'feather_{side}_{n:02}'] = c
    return masks


def camera_setup(size=900):
    helpers = runpy.run_path(str(TRUSTED/'turnaround.py'), run_name='trusted_render_helpers')
    camera = helpers['setup_render'](size)
    bpy.context.scene.render.image_settings.file_format = 'PNG'
    bpy.context.scene.render.film_transparent = False
    return camera


def diagnostic(obj, points, masks, cal, out):
    out.mkdir()
    camera = camera_setup()
    materials = list(obj.data.materials)
    indices = [p.material_index for p in obj.data.polygons]
    region = np.zeros(len(points), dtype=int)
    for i, name in enumerate(('head', 'wing_l', 'wing_r'), 1):
        region[masks[name]] = i
    colors = [(.04,.24,.5,1),(.1,.7,.26,1),(.8,.22,.05,1),(.55,.12,.72,1)]
    obj.data.materials.clear()
    try:
        for n, c in enumerate(colors):
            mat = bpy.data.materials.new('geometry_mask_'+str(n))
            mat.use_nodes = True
            shader = mat.node_tree.nodes.get('Principled BSDF')
            shader.inputs['Base Color'].default_value = c
            shader.inputs['Emission Color'].default_value = c
            shader.inputs['Emission Strength'].default_value = .3
            obj.data.materials.append(mat)
        for poly in obj.data.polygons:
            poly.material_index = int(np.bincount(region[list(poly.vertices)], minlength=4).argmax())
        center = (points.min(axis=0)+points.max(axis=0))/2
        for name, direction in [('front',(0,-1,.10)),('back',(0,1,.15)),('side',(1,0,.12)),('top',(0,0,1)),('34',(.65,-.8,.35))]:
            render_view(camera, out, 'regions-'+name, center, direction, SPAN*1.16)
        for name, direction in [('roots-front',(0,-1,.2)),('roots-back',(0,1,.2)),('roots-top',(0,0,1))]:
            render_view(camera, out, name, cal['landmarks']['core'], direction, 1.25)
    finally:
        obj.data.materials.clear()
        for mat in materials:
            obj.data.materials.append(mat)
        for poly, index in zip(obj.data.polygons, indices):
            poly.material_index = index


def runtime_contract():
    return {'scale': 1., 'outerTranslation': [0., 0., 0.], 'outerLocomotionRequired': False,
            'forward': 'glTF +Z / Blender -Y', 'restWingspan': SPAN,
            'permanentElevation': ELEVATION, 'permanentElevationMethod': 'Baked into native vertex coordinates and matching bone rests; no node scale or animated baseline offset',
            'animatedRootTranslation': 'Small periodic vertical bob only, centered at zero; never subtract permanent elevation',
            'idleDuration': 6., 'walkDuration': 4., 'specialDuration': 6.,
            'walkMeaning': 'Stationary airborne serpentine undulation and restrained wing flaps; no ground gait',
            'specialReturn': 'Endpoints, velocities and accelerations match idle at t=0/6; auto-return to idle phase0',
            'interpolation': '60Hz source keys, periodic C2 cubic splines in actual GLB; quaternion cubics normalized by glTF runtime',
            'crossfade': '.3 seconds acceptable for same native rest rig; full blended Stage review remains parent responsibility'}


def make_rig(cal):
    lm = cal['landmarks']
    arm = bpy.data.objects.new('yinglong_rig', bpy.data.armatures.new('yinglong_native_rest'))
    bpy.context.scene.collection.objects.link(arm)
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(name, a, b, parent=None, deform=True):
        item = arm.data.edit_bones.new(name)
        item.head, item.tail = Vector(a), Vector(b)
        assert (item.tail-item.head).length > 1e-4
        if parent:
            item.parent = arm.data.edit_bones[parent]
        item.use_deform = deform
        return item
    core = np.array(lm['core'])
    bone('root', (0, 0, 0), (0, 0, .15), deform=False)
    bone('core', core, core+[0, .10, 0], 'root')
    bone('breath', core, core+[0, 0, .10], 'core')
    for tag, start in [('frontSpine', 0), ('backSpine', 7)]:
        pts = lm[tag]
        for j in range(len(pts)-1):
            name = f'spine_{j+start:02}'
            parent = 'core' if j == 0 else f'spine_{j+start-1:02}'
            bone(name, pts[j], pts[j+1], parent)
    bone('head', lm['frontSpine'][-1], lm['headTip'], 'spine_06')
    for side in ('l', 'r'):
        knots = lm['wings'][side]
        pts = [knots[i] for i in (0, 2, 3, 4)]
        for j in range(3):
            bone(f'wing_{side}_{j}', pts[j], pts[j+1], 'core' if j == 0 else f'wing_{side}_{j-1}')
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(arm.data.bones) == 34
    return arm


def longitudinal_weights(y, pts, names):
    mids = (np.array(pts[:-1])+np.array(pts[1:]))*.5
    # Parent core is the first center; rigid skull is the final anterior center.
    stations = [pts[0][1]]+[p[1] for p in mids]
    if stations[-1] < stations[0]:
        stations = [-x for x in stations]
        y = -y
    if y <= stations[0]:
        return {'core': 1.}
    if y >= stations[-1]:
        return {names[-1]: 1.}
    k = int(np.searchsorted(stations, y))
    f = float(smooth((y-stations[k-1])/(stations[k]-stations[k-1])))
    labels = ['core']+names
    return {labels[k-1]: 1-f, labels[k]: f}


def wing_weights(x, side):
    # Last feather vanes remain rigid with the final bone; joints bend in the spar.
    if x < .64:
        return {f'wing_{side}_0': 1.}
    if x < .92:
        f = float(smooth((x-.64)/.28))
        return {f'wing_{side}_0': 1-f, f'wing_{side}_1': f}
    if x < 1.08:
        return {f'wing_{side}_1': 1.}
    if x < 1.26:
        f = float(smooth((x-1.08)/.18))
        return {f'wing_{side}_1': 1-f, f'wing_{side}_2': f}
    return {f'wing_{side}_2': 1.}


def bind(obj, arm, points, masks, cal):
    sets = {name: set(masks[name]) for name in ('head', 'wing_l', 'wing_r')}
    lm = cal['landmarks']
    wc = cal['weightingCalibration']
    def ramp(value, limits):
        return float(smooth((value-limits[0])/(limits[1]-limits[0])))
    groups = {b.name: obj.vertex_groups.new(name=b.name) for b in arm.data.bones}
    weights = []
    for i, p in enumerate(points):
        side = next((s for s in ('l', 'r') if i in sets['wing_'+s]), None)
        if side:
            outer = ramp(abs(p[0]),wc['wingRootZGateOverrideX'])
            # C2 collars fade to zero at EVERY reviewed cut, not just its X plane.
            # Beyond the inner collar every native feather is entirely wing-bound.
            gate_y = ramp(p[1],wc['wingRootQuinticY'])
            gate_z = ramp(p[2],wc['wingRootQuinticZ'])
            mix = ramp(abs(p[0]),wc['wingRootQuinticX'])*gate_y*(outer+(1-outer)*gate_z)
            w = {name: value*mix for name, value in wing_weights(abs(p[0]), side).items()}
            w['core'] = 1-mix
        elif i in sets['head']:
            w = {'head': 1.}
        elif p[1] < lm['core'][1]:
            w = longitudinal_weights(p[1], lm['frontSpine'], [f'spine_{j:02}' for j in range(7)])
            # Ease to the rigid skull before the independently calibrated head cut.
            h = float(smooth((-p[1]-.94)/.10))
            w = {name: value*(1-h) for name, value in w.items()}
            w['head'] = h
        else:
            w = longitudinal_weights(p[1], lm['backSpine'], [f'spine_{j:02}' for j in range(7, 24)])
        if not side and i not in sets['head']:
            # Preserve the contiguous broad shoulder volume. Spine motion eases
            # into neck/tail outside the native wing roots, never across a cut.
            front,back = wc['bodyFullCoreY']
            axial = float(smooth((front-p[1])/wc['anteriorSpineEaseM'])) if p[1] < front else float(smooth((p[1]-back)/wc['posteriorSpineEaseM']))
            w = {name: value*axial for name, value in w.items()}
            w['core'] = w.get('core',0.)+1-axial
            breath = .32*float(smooth(1-abs(p[1]-lm['core'][1])/.34))*(1-ramp(abs(p[0]),wc['breathFadeOutAbsX']))
            w = {name: value*(1-breath) for name, value in w.items()}
            w['breath'] = breath
        w = {name: value for name, value in w.items() if value > 1e-8}
        total = sum(w.values())
        w = {name: value/total for name, value in w.items()}
        assert 1 <= len(w) <= 4 and abs(sum(w.values())-1) < 1e-7
        for name, value in w.items():
            groups[name].add([i], value, 'REPLACE')
        weights.append(w)
    for side in ('l', 'r'):
        assert all(all(name == 'core' or name.startswith('wing_'+side+'_') for name in weights[i]) for i in masks['wing_'+side])
        assert all(all(name.startswith('wing_'+side+'_') for name in weights[i]) for i in masks['wing_'+side] if abs(points[i, 0]) >= .38)
        assert all(weights[i] == {f'wing_{side}_2': 1.} for i in masks['wing_tip_'+side])
    assert all(weights[i] == {'head': 1.} for i in masks['head'])
    mod = obj.modifiers.new('Native anatomical spine and ipsilateral wings', 'ARMATURE')
    mod.object = arm
    obj.parent = arm
    obj['runtimeContract'] = runtime_contract()
    obj['candidateOnly'] = True
    return weights


def animate(arm, name, seconds):
    action = base.new_action(arm, name)
    count = round(seconds*FPS)
    previous = {}
    for frame in range(count+1):
        p = frame/count
        phase = math.tau*p
        display = math.sin(math.pi*p)**4 if name == 'special' else 0.
        walk = name == 'walk'
        for pb in arm.pose.bones:
            pb.rotation_mode = 'QUATERNION'
            pb.location = (0, 0, 0)
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.scale = (1, 1, 1)
        root = arm.pose.bones['root']
        root.location = root.bone.matrix_local.to_3x3().inverted() @ Vector((0., 0., (.015 if walk else .009)*math.sin(phase)))
        core = arm.pose.bones['core']
        core.rotation_quaternion = base.world_rot(core, base.Z, .004*math.sin(phase)) @ base.world_rot(core, base.X, .003*math.sin(phase+.3))
        breath = arm.pose.bones['breath']
        breath.scale = (1+.004*math.sin(phase), 1+.006*math.sin(phase), 1+.004*math.sin(phase))
        for j in range(24):
            pb = arm.pose.bones[f'spine_{j:02}']
            if j < 7:
                u = (j+.5)/7
                amp = (.014 if walk else .006)+.008*display
                lag = -1.9*u
                lateral = amp*math.sin(phase+lag)
                vertical = amp*.55*math.sin(phase+lag+.65)
            else:
                u = (j-7+.5)/17
                amp = ((.027 if walk else .011)+.014*display)*(.4+.6*u)
                lag = 4.8*u
                lateral = amp*math.sin(phase-lag)
                vertical = amp*.70*math.sin(phase-lag+1.0)
            pb.rotation_quaternion = base.world_rot(pb, base.Z, lateral) @ base.world_rot(pb, base.X, vertical)
        head = arm.pose.bones['head']
        head.rotation_quaternion = base.world_rot(head, base.Z, .007*math.sin(phase-1.8)) @ base.world_rot(head, base.X, .004*math.sin(phase-1.1))
        for side, sign, shift in [('l', 1., 0.), ('r', -1., .24)]:
            for j in range(3):
                pb = arm.pose.bones[f'wing_{side}_{j}']
                amplitude = ((.045 if walk else .024), (.014 if walk else .007), (.009 if walk else .004))[j]
                amplitude += display*(.036, .013, .008)[j]
                flap = sign*amplitude*math.sin(phase+shift-j*.42)
                feather = sign*(.006 if walk else .003)*math.sin(phase+shift-j*.5+.6)
                pb.rotation_quaternion = base.world_rot(pb, base.Y, -flap) @ base.world_rot(pb, base.Z, feather)
        for pb in arm.pose.bones:
            if pb.name in previous and previous[pb.name].dot(pb.rotation_quaternion) < 0:
                pb.rotation_quaternion.negate()
            previous[pb.name] = pb.rotation_quaternion.copy()
            for channel in ('location', 'rotation_quaternion', 'scale'):
                pb.keyframe_insert(channel, frame=frame)
    base.finish_action(arm, action)
    for curve in base.action_fcurves(action):
        for key in curve.keyframe_points:
            key.interpolation = 'LINEAR'
    return action


def glb_read(path):
    data = path.read_bytes()
    magic, version, length = struct.unpack_from('<4sII', data)
    assert magic == b'glTF' and version == 2 and length == len(data)
    offset, document, binary = 12, None, None
    while offset < length:
        size, kind = struct.unpack_from('<II', data, offset)
        chunk = data[offset+8:offset+8+size]
        if kind == 0x4e4f534a:
            document = json.loads(chunk)
        elif kind == 0x004e4942:
            binary = chunk
        offset += 8+size
    return document, binary


def accessor(doc, binary, index):
    spec = doc['accessors'][index]
    assert 'sparse' not in spec
    types = {5120: 'i1', 5121: 'u1', 5122: '<i2', 5123: '<u2', 5125: '<u4', 5126: '<f4'}
    widths = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4, 'MAT4': 16}
    dtype, width = np.dtype(types[spec['componentType']]), widths[spec['type']]
    view = doc['bufferViews'][spec['bufferView']]
    start = view.get('byteOffset', 0)+spec.get('byteOffset', 0)
    stride = view.get('byteStride', width*dtype.itemsize)
    result = np.ndarray((spec['count'], width), dtype=dtype, buffer=binary, offset=start,
                        strides=(stride, dtype.itemsize)).copy()
    assert np.isfinite(result).all()
    if spec.get('normalized'):
        result = result.astype(float)/np.iinfo(dtype).max
    return result


def write_glb(path, doc, binary):
    binary = bytearray(binary)
    doc['buffers'][0]['byteLength'] = len(binary)
    raw_json = json.dumps(doc, separators=(',', ':')).encode()
    raw_json += b' '*((-len(raw_json)) % 4)
    binary.extend(b'\x00'*((-len(binary)) % 4))
    total = 12+8+len(raw_json)+8+len(binary)
    path.write_bytes(struct.pack('<4sII',b'glTF',2,total)+struct.pack('<II',len(raw_json),0x4e4f534a)+raw_json+struct.pack('<II',len(binary),0x004e4942)+binary)


def restore_native_payload(path, source, points, weights, uv, triangles):
    """Lossless native attribute passthrough, avoiding Blender normal seam splitting.

    Blender is used for the trusted skeleton/animation carrier, not to rewrite
    native attributes. Keep source vertex/index order and raw NORMAL/UV/index
    bytes, adding only normalized POSITION and new JOINTS/WEIGHTS. This does not
    merge, rebuild, or reconstruct geometry. Verify importer/source correspondence
    before using native indices. Packed native PBR images are independently audited.
    """
    doc,data = glb_read(path)
    native,raw = glb_read(source)
    assert len(native['meshes']) == 1 and len(native['meshes'][0]['primitives']) == 1
    src = native['meshes'][0]['primitives'][0]
    assert set(src['attributes']) == {'POSITION','NORMAL','TEXCOORD_0'}
    sp = accessor(native,raw,src['attributes']['POSITION'])
    sn = accessor(native,raw,src['attributes']['NORMAL'])
    su = accessor(native,raw,src['attributes']['TEXCOORD_0'])
    si = accessor(native,raw,src['indices']).ravel()
    assert np.array_equal(si.reshape(-1,3),triangles), 'Native/imported index correspondence changed'
    assert np.max(np.abs(su-(uv*[1,-1]+[0,1]))) < 2e-7
    # Explicitly verify decoded source vertex order under the permitted transform.
    decoded = sp[:,[0,2,1]]*np.array([1.,-1.,1.])
    lo,hi = decoded.min(axis=0),decoded.max(axis=0)
    origin = np.array([(lo[0]+hi[0])/2,(lo[1]+hi[1])/2,lo[2]])
    expected = (decoded-origin)*(SPAN/(hi[0]-lo[0]))+[0,0,ELEVATION]
    assert np.max(np.abs(expected-points)) < 4e-7
    gltf_points = points[:,[0,2,1]]*np.array([1.,1.,-1.])
    meshnode = next(n for n in doc['nodes'] if 'mesh' in n and 'skin' in n)
    skin = doc['skins'][meshnode['skin']]
    joint_names = {doc['nodes'][node]['name']: i for i,node in enumerate(skin['joints'])}
    joints = np.zeros((len(points),4),dtype='<u2')
    w = np.zeros((len(points),4),dtype='<f4')
    for i,values in enumerate(weights):
        for j,(name,value) in enumerate(values.items()):
            joints[i,j],w[i,j] = joint_names[name],value
    binary = bytearray(data)
    def append(values,kind,component):
        values = np.ascontiguousarray(values)
        binary.extend(b'\x00'*((-len(binary))%4))
        start = len(binary)
        binary.extend(values.tobytes())
        view = len(doc['bufferViews'])
        doc['bufferViews'].append({'buffer':0,'byteOffset':start,'byteLength':values.nbytes})
        index = len(doc['accessors'])
        spec = {'bufferView':view,'componentType':component,'count':len(values),'type':kind}
        if kind == 'VEC3' and component == 5126:
            spec.update(min=values.min(axis=0).tolist(),max=values.max(axis=0).tolist())
        doc['accessors'].append(spec)
        return index
    attributes = {'POSITION':append(gltf_points.astype('<f4'),'VEC3',5126),
                  'NORMAL':append(sn.astype('<f4'),'VEC3',5126),
                  'TEXCOORD_0':append(su.astype('<f4'),'VEC2',5126),
                  'JOINTS_0':append(joints,'VEC4',5123),
                  'WEIGHTS_0':append(w,'VEC4',5126)}
    assert native['accessors'][src['indices']]['componentType'] == 5123
    indices = append(si.astype('<u2'),'SCALAR',5123)
    primitives = doc['meshes'][meshnode['mesh']]['primitives']
    assert len(primitives) == 1
    primitives[0]['attributes'],primitives[0]['indices'] = attributes,indices
    write_glb(path,doc,binary)
    return {'nativeVertices':len(points),'nativeTriangles':len(triangles),
            'nativeNormalBytesSha256':array_sha(sn),'nativeUVBytesSha256':array_sha(su),
            'nativeIndexBytesSha256':array_sha(si,'<u2'),
            'normalUVIndexBytesPreservedExactly':True,'newAttributes':['JOINTS_0','WEIGHTS_0'],
            'positionChange':'Only calibrated positive uniform normalization and baked permanent elevation',
            'blenderCornerCodecBypassedForActualGltfNormals':True}


def cubic_export(path):
    """Replace sampled animation outputs with truly periodic C2 cubic splines.

    Solve the uniform periodic cubic system via its circulant eigenvalues.
    Native geometry/material/image buffers are untouched; only new animation
    buffers are appended. glTF CUBICSPLINE tangents have units per second.
    """
    doc, data = glb_read(path)
    binary = bytearray(data)
    result = {}
    for animation in doc['animations']:
        count = 0
        for sampler in animation['samplers']:
            t = accessor(doc, data, sampler['input']).ravel()
            y = accessor(doc, data, sampler['output']).astype(np.float64)
            assert len(y) == len(t) and len(t) > 2
            assert np.max(np.abs(np.diff(t)-1/FPS)) < 2e-6
            assert np.abs(y[-1]-y[0]).max() < 2e-6
            y[-1] = y[0]
            h = float((t[-1]-t[0])/(len(t)-1))
            periodic = y[:-1]
            n = len(periodic)
            rhs = 3*(np.roll(periodic, -1, axis=0)-np.roll(periodic, 1, axis=0))/h
            eigenvalues = 4+2*np.cos(math.tau*np.arange(n//2+1)/n)
            tangent = np.fft.irfft(np.fft.rfft(rhs, axis=0)/eigenvalues[:, None], n=n, axis=0)
            tangent = np.vstack([tangent, tangent[0]])
            output = np.stack([tangent, y, tangent], axis=1).astype('<f4')
            binary.extend(b'\x00'*((-len(binary)) % 4))
            start = len(binary)
            binary.extend(output.tobytes())
            view = len(doc['bufferViews'])
            doc['bufferViews'].append({'buffer': 0, 'byteOffset': start, 'byteLength': output.nbytes})
            index = len(doc['accessors'])
            doc['accessors'].append({'bufferView': view, 'componentType': 5126,
                                     'count': len(t)*3, 'type': 'VEC4' if y.shape[1] == 4 else 'VEC3'})
            sampler['output'], sampler['interpolation'] = index, 'CUBICSPLINE'
            count += 1
        result[animation['name']] = {'seconds': float(t[-1]), 'cubicChannels': count, 'periodicC2': True}
    doc['buffers'][0]['byteLength'] = len(binary)
    raw_json = json.dumps(doc, separators=(',', ':')).encode()
    raw_json += b' '*((-len(raw_json)) % 4)
    binary.extend(b'\x00'*((-len(binary)) % 4))
    total = 12+8+len(raw_json)+8+len(binary)
    path.write_bytes(struct.pack('<4sII', b'glTF', 2, total)+struct.pack('<II', len(raw_json), 0x4e4f534a)+raw_json+struct.pack('<II', len(binary), 0x004e4942)+binary)
    return result


class GlbSkin:
    """Small independent glTF evaluator for the exact exported cubic buffers."""
    def __init__(self, path):
        self.doc, self.binary = glb_read(path)
        doc, binary = self.doc, self.binary
        self.attrs = []
        self.tris = []
        self.mesh_node = next(i for i, n in enumerate(doc['nodes']) if 'mesh' in n and 'skin' in n)
        node = doc['nodes'][self.mesh_node]
        offset = 0
        for prim in doc['meshes'][node['mesh']]['primitives']:
            attrs = {k: accessor(doc, binary, v) for k, v in prim['attributes'].items()}
            assert {'POSITION','NORMAL','TEXCOORD_0','JOINTS_0','WEIGHTS_0'} <= set(attrs)
            self.attrs.append(attrs)
            self.tris.append(accessor(doc, binary, prim['indices']).ravel().astype(int).reshape(-1, 3)+offset)
            offset += len(attrs['POSITION'])
        self.positions = np.concatenate([a['POSITION'] for a in self.attrs]).astype(float)
        self.normals = np.concatenate([a['NORMAL'] for a in self.attrs]).astype(float)
        self.uv = np.concatenate([a['TEXCOORD_0'] for a in self.attrs]).astype(float)
        self.weights = np.concatenate([a['WEIGHTS_0'] for a in self.attrs]).astype(float)
        self.joints = np.concatenate([a['JOINTS_0'] for a in self.attrs]).astype(int)
        self.triangles = np.concatenate(self.tris)
        skin = doc['skins'][node['skin']]
        self.bones = skin['joints']
        self.inverse_bind = accessor(doc, binary, skin['inverseBindMatrices']).reshape(-1, 4, 4).transpose(0, 2, 1)
        self.parent = {child: i for i, n in enumerate(doc['nodes']) for child in n.get('children', [])}
        self.animations = {}
        self.curve_qa = {}
        for animation in doc['animations']:
            curves, qa = [], {'maxValueSeam': 0., 'maxTangentSeam': 0., 'maxSecondDerivativeSeam': 0.}
            for channel in animation['channels']:
                sampler = animation['samplers'][channel['sampler']]
                assert sampler['interpolation'] == 'CUBICSPLINE'
                t = accessor(doc, binary, sampler['input']).ravel().astype(float)
                y = accessor(doc, binary, sampler['output']).reshape(len(t), 3, -1).astype(float)
                assert np.all(np.diff(t) > 0) and abs(t[0]) < 1e-8
                assert abs(t[-1]-DURATIONS[animation['name']]) < 1e-6
                h0, he = t[1]-t[0], t[-1]-t[-2]
                a0 = 6*(y[1, 1]-y[0, 1])/h0**2-(4*y[0, 2]+2*y[1, 0])/h0
                ae = -6*(y[-1, 1]-y[-2, 1])/he**2+(2*y[-2, 2]+4*y[-1, 0])/he
                qa['maxValueSeam'] = max(qa['maxValueSeam'], float(np.abs(y[-1, 1]-y[0, 1]).max()))
                qa['maxTangentSeam'] = max(qa['maxTangentSeam'], float(np.abs(y[-1, 0]-y[0, 2]).max()))
                qa['maxSecondDerivativeSeam'] = max(qa['maxSecondDerivativeSeam'], float(np.abs(a0-ae).max()))
                curves.append((channel['target']['node'], channel['target']['path'], t, y))
            assert qa['maxValueSeam'] < 1e-7 and qa['maxTangentSeam'] < 1e-7 and qa['maxSecondDerivativeSeam'] < .01, qa
            self.animations[animation['name']] = curves
            self.curve_qa[animation['name']] = qa
        assert set(self.animations) == set(DURATIONS)
        assert np.abs(self.weights.sum(axis=1)-1).max() < 2e-6
        assert self.weights.min() >= 0 and self.joints.max() < len(self.bones)
        assert (self.weights.max(axis=1) > 0).all()
        for index in range(len(doc['accessors'])):
            accessor(doc, binary, index)
        self.homogeneous = np.c_[self.positions, np.ones(len(self.positions))]

    def globals(self, clip=None, time=0.):
        doc = self.doc
        tr = [list(n.get('translation', [0.,0.,0.])) for n in doc['nodes']]
        ro = [list(n.get('rotation', [0.,0.,0.,1.])) for n in doc['nodes']]
        sc = [list(n.get('scale', [1.,1.,1.])) for n in doc['nodes']]
        if clip:
            for node, path, times, data in self.animations[clip]:
                k = min(len(times)-2, max(0, int(np.searchsorted(times, time, side='right')-1)))
                h = times[k+1]-times[k]
                u = float(np.clip((time-times[k])/h, 0, 1))
                v = (2*u**3-3*u*u+1)*data[k,1]+(u**3-2*u*u+u)*h*data[k,2]+(-2*u**3+3*u*u)*data[k+1,1]+(u**3-u*u)*h*data[k+1,0]
                if path == 'rotation':
                    assert np.linalg.norm(v) > .9
                    ro[node] = v/np.linalg.norm(v)
                elif path == 'translation':
                    tr[node] = v
                else:
                    assert path == 'scale' and (v > 0).all()
                    sc[node] = v
        world = {}
        def matrix(i):
            if i not in world:
                n = doc['nodes'][i]
                if 'matrix' in n:
                    m = np.array(n['matrix']).reshape(4,4).T
                else:
                    # Float64 throughout: mathutils.to_matrix returns float32,
                    # whose roundoff dominates finite-difference acceleration QA.
                    q = np.array(ro[i], dtype=np.float64)
                    q /= np.linalg.norm(q)
                    x,y,z,w = q
                    m = np.eye(4)
                    m[:3,:3] = [[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                                 [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                                 [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]]
                    m[:3,:3] *= np.array(sc[i])[None,:]
                    m[:3,3] = tr[i]
                world[i] = matrix(self.parent[i])@m if i in self.parent else m
            return world[i]
        return np.array([matrix(i) for i in range(len(doc['nodes']))])

    def points(self, clip=None, time=0.):
        world = self.globals(clip, time)
        skin = world[self.bones]@self.inverse_bind
        values = np.einsum('nvij,nj->nvi', skin[self.joints], self.homogeneous)
        gltf = np.einsum('nvi,nv->ni', values, self.weights)[:,:3]
        result = gltf[:,[0,2,1]]*np.array([1.,-1.,1.])
        assert np.isfinite(result).all()
        return result


def material_semantics(path):
    doc, binary = glb_read(path)
    images = []
    for image in doc['images']:
        view = doc['bufferViews'][image['bufferView']]
        start = view.get('byteOffset', 0)
        images.append(sha_bytes(binary[start:start+view['byteLength']]))
    result = []
    for material in doc['materials']:
        mat = json.loads(json.dumps(material))
        def replace(value):
            if isinstance(value, dict):
                for k, v in list(value.items()):
                    if k.endswith('Texture') and isinstance(v, dict):
                        texture = doc['textures'][v['index']]
                        value[k] = {**v, 'index': images[texture['source']], 'sampler': doc.get('samplers', [{}])[texture.get('sampler', 0)]}
                    else:
                        replace(v)
            elif isinstance(value, list):
                for v in value:
                    replace(v)
        replace(mat)
        mat.pop('extras', None)
        result.append(mat)
    return result


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def per_vertex_attributes(obj):
    n = len(obj.data.vertices)
    normals, uv = np.zeros((n,3)), np.zeros((n,2))
    ids = np.array([l.vertex_index for l in obj.data.loops])
    normals[ids] = np.array([tuple(n.vector) for n in obj.data.corner_normals])
    uv[ids] = np.array([tuple(v.uv) for v in obj.data.uv_layers.active.data])
    return normals, uv


def rest_audit(skin, source, points, normals, uv, triangles, masks):
    from mathutils.kdtree import KDTree
    candidate = skin.points()
    tree = KDTree(len(points))
    for i, p in enumerate(points):
        tree.insert(p, i)
    tree.balance()
    c_uv = skin.uv*np.array([1.,-1.])+np.array([0.,1.])
    c_normals = skin.normals[:,[0,2,1]]*np.array([1.,-1.,1.])
    native, raw = glb_read(source)
    primitive = native['meshes'][0]['primitives'][0]
    raw_normals = accessor(native,raw,primitive['attributes']['NORMAL'])
    raw_uv = accessor(native,raw,primitive['attributes']['TEXCOORD_0'])
    raw_indices = accessor(native,raw,primitive['indices']).ravel()
    assert array_sha(skin.normals) == array_sha(raw_normals), 'Actual glTF native NORMAL bytes changed'
    assert array_sha(skin.uv) == array_sha(raw_uv), 'Actual glTF native UV bytes changed'
    assert np.array_equal(skin.triangles.ravel(), raw_indices), 'Actual native indices changed'
    normals = raw_normals[:,[0,2,1]]*np.array([1.,-1.,1.])
    # Mesh rest transform is explicitly identity in this normalized contract.
    mesh_world = skin.globals()[skin.mesh_node]
    assert np.abs(mesh_world-np.eye(4)).max() < 1e-5
    mapping, position_error, uv_error, normal_error = [], 0., 0., 0.
    for j, p in enumerate(candidate):
        near = tree.find_range(p, 1e-5)
        assert near, ('Missing native rest point', j)
        # UVs distinguish seam copies; normals remain within the documented codec tolerance.
        best = min(near, key=lambda item: float(np.linalg.norm(uv[item[1]]-c_uv[j]))*100+float(np.linalg.norm(normals[item[1]]-c_normals[j]))+item[2])
        _, i, error = best
        mapping.append(i)
        position_error = max(position_error, error)
        uv_error = max(uv_error, float(np.abs(uv[i]-c_uv[j]).max()))
        normal_error = max(normal_error, float(np.abs(normals[i]-c_normals[j]).max()))
    assert position_error < 2e-6 and uv_error < 3e-7 and normal_error < .0012, (position_error, uv_error, normal_error)
    mapping = np.array(mapping)
    imported_masks = {name: np.flatnonzero(np.isin(mapping, ids)).tolist() for name, ids in masks.items()}
    assert all(imported_masks.values())
    def canonical_faces(p, tri):
        # Compare native geometric triangle incidence AND winding, ignoring GLB
        # seam-vertex order. Mapping uses actual native points rather than quantized output.
        keys = [tuple(np.round(v, 5)) for v in p]
        output = []
        for face in tri:
            a,b,c = [keys[i] for i in face]
            output.append(min((a,b,c),(b,c,a),(c,a,b)))
        return sorted(output)
    assert len(skin.triangles) == len(triangles)
    assert canonical_faces(points, triangles) == canonical_faces(points[mapping], skin.triangles), 'Native triangle incidence/winding changed'
    def areas(p, tri):
        a,b,c = p[tri[:,0]],p[tri[:,1]],p[tri[:,2]]
        return np.linalg.norm(np.cross(b-a,c-a), axis=1)*.5
    original_area, candidate_area = areas(points, triangles), areas(candidate, skin.triangles)
    stored = skin.positions[:,[0,2,1]]*np.array([1.,-1.,1.])
    stored_area = areas(stored,skin.triangles)
    assert np.array_equal(stored,points), 'Stored positions changed beyond normalized native coordinates'
    assert np.array_equal(stored_area,original_area), 'Stored native degenerates changed'
    source_material = material_semantics(source)
    candidate_material = material_semantics(Path(skin.path)) if hasattr(skin, 'path') else None
    return imported_masks, {
        'maxRestPositionErrorM': position_error, 'maxUVComponentError': uv_error,
        'maxNormalComponentError': normal_error, 'vertices': len(candidate), 'triangles': len(skin.triangles),
        'triangleIncidenceAndWindingPreservedAtNative1e-5CoordinateKeys': True,
        'nativeDegenerateTrianglesAreaBelow1e-14': int((original_area < 1e-14).sum()),
        'storedNativeDegenerateTrianglesAreaBelow1e-14': int((stored_area < 1e-14).sum()),
        'skinnedRestDegenerateTrianglesAreaBelow1e-14': int((candidate_area < 1e-14).sum()),
        'degenerateDisclosure': 'Stored native positions/indices and all 95 source zero/nearly-zero facets retained exactly. Float32 inverse-bind skin evaluation can move a nearly-zero facet across the arbitrary 1e-14 m2 reporting threshold; this is numerical rest roundoff, not topology repair or geometry editing.',
        'nativeAreaRange': [float(original_area.min()),float(original_area.max())],
        'candidateAreaRange': [float(candidate_area.min()),float(candidate_area.max())],
        'nativePBR': source_material, 'candidatePBR': candidate_material,
        'rawNativeNormalUVIndexBytesPreservedExactly': True,
        'tolerances': {'restPositionM': 2e-6, 'decodedBlenderUVComponent': 3e-7,
                       'rawNormalUVIndexBytes': 'exact SHA256 and index equality; no codec tolerance required',
                       'reason': 'Rest positions use float32 normalization and float32 inverse-bind matrices. Source NORMAL/UV/index payload passes through unchanged; Blender decoded corner-normal codec is bypassed in actual GLB'},
    }


def motion_qa(skin, masks):
    rest = skin.points()
    faces = skin.triangles
    edges = np.unique(np.sort(np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]), axis=1),axis=0)
    lengths = np.linalg.norm(rest[edges[:,0]]-rest[edges[:,1]], axis=1)
    robust = lengths > 1e-4
    mask_sets = {name: set(ids) for name, ids in masks.items()}
    strain_edges = {}
    for region in ('wing_l','wing_r','wing_root_l','wing_root_r'):
        select = np.array([a in mask_sets[region] and b in mask_sets[region] for a,b in edges]) & robust
        strain_edges[region] = np.flatnonzero(select)
    swept_lo, swept_hi = rest.min(axis=0), rest.max(axis=0)
    yaw_lo, yaw_hi = np.full(3,np.inf), np.full(3,-np.inf)
    # Parent Stage yaw +PI/4 around glTF +Y. These bounds aid camera/ground checks.
    c,s = math.cos(math.pi/4),math.sin(math.pi/4)
    yaw = np.array([[c,0,s],[0,1,0],[-s,0,c]])
    report = {}
    protected = ['head','wing_tip_l','wing_tip_r']
    feathers = [name for name in masks if name.startswith('feather_')]
    anchors = {}
    for name in protected+feathers:
        ids = masks[name]
        anchor = ids[len(ids)//2]
        anchors[name] = (np.array(ids), anchor, np.linalg.norm(rest[ids]-rest[anchor],axis=1))
    for clip, duration in DURATIONS.items():
        low, high = np.full(3,np.inf), np.full(3,-np.inf)
        rigidity = {name: 0. for name in protected}
        feather_error = 0.
        max_strain = {name: 0. for name in strain_edges}
        p99_strain = {name: 0. for name in strain_edges}
        area_ratio_low, area_ratio_high = 1.,1.
        movement_lo, movement_hi = np.full_like(rest,np.inf), np.full_like(rest,-np.inf)
        minheight, maxvelocity = math.inf, 0.
        previous = None
        sample_count = round(duration*120)+1
        # Robust area checks include every nondegenerate native triangle; tiny
        # generated facets are disclosed separately, never silently removed.
        a0,b0,c0 = [rest[faces[:,i]] for i in range(3)]
        area0 = np.linalg.norm(np.cross(b0-a0,c0-a0),axis=1)
        area_ok = area0 > 2e-8
        for n in range(sample_count):
            p = skin.points(clip, n/120)
            low,high = np.minimum(low,p.min(axis=0)),np.maximum(high,p.max(axis=0))
            movement_lo,movement_hi = np.minimum(movement_lo,p),np.maximum(movement_hi,p)
            if previous is not None:
                maxvelocity = max(maxvelocity,float(np.linalg.norm(p-previous,axis=1).max())*120)
            previous = p
            for name in protected+feathers:
                ids,anchor,d0 = anchors[name]
                error = float(np.abs(np.linalg.norm(p[ids]-p[anchor],axis=1)-d0).max())
                if name in rigidity:
                    rigidity[name] = max(rigidity[name],error)
                else:
                    feather_error = max(feather_error,error)
            current_lengths = np.linalg.norm(p[edges[:,0]]-p[edges[:,1]],axis=1)
            for region,select in strain_edges.items():
                strains = np.abs(current_lengths[select]/lengths[select]-1)
                max_strain[region] = max(max_strain[region],float(strains.max()))
                p99_strain[region] = max(p99_strain[region],float(np.quantile(strains,.99)))
            if n % 4 == 0:
                a,b,c = [p[faces[:,i]] for i in range(3)]
                ratio = np.linalg.norm(np.cross(b-a,c-a),axis=1)[area_ok]/area0[area_ok]
                area_ratio_low,area_ratio_high = min(area_ratio_low,float(ratio.min())),max(area_ratio_high,float(ratio.max()))
            stage = (p[:,[0,2,1]]*np.array([1.,1.,-1.]))@yaw.T
            yaw_lo,yaw_hi = np.minimum(yaw_lo,stage.min(axis=0)),np.maximum(yaw_hi,stage.max(axis=0))
        swept_lo,swept_hi = np.minimum(swept_lo,low),np.maximum(swept_hi,high)
        dt = .001
        p0,p1,p2,pm2,pm,pe = [skin.points(clip,t) for t in (0,dt,2*dt,duration-2*dt,duration-dt,duration)]
        seam = float(np.linalg.norm(pe-p0,axis=1).max())
        velocity = float(np.linalg.norm((p1-p0)/dt-(pe-pm)/dt,axis=1).max())
        acceleration = float(np.linalg.norm((p2-2*p1+p0)/dt**2-(pe-2*pm+pm2)/dt**2,axis=1).max())
        movement = np.linalg.norm(movement_hi-movement_lo,axis=1)
        entry = {'samples':sample_count,'samplingHz':120,'boundsBlender':[low.tolist(),high.tolist()],
                 'minimumGroundClearanceM':float(low[2]),'maximumSampledVertexSpeedMps':maxvelocity,
                 'protectedShapeDistanceErrorM':rigidity,'maximumFeatherPatchDistanceErrorM':feather_error,
                 'nativeFeatherPatchCount':len(feathers),'maximumNativeEdgeLengthRelativeChange':max_strain,
                 'p99NativeEdgeLengthRelativeChange':p99_strain,'robustTriangleAreaRatioRange':[area_ratio_low,area_ratio_high],
                 'allVertexLoopPositionErrorM':seam,'allVertexWrapVelocityDifferenceMps':velocity,
                 'allVertexWrapAccelerationDifferenceMps2':acceleration,'oneSidedDifferenceDt':dt,
                 'actualCubicBufferContinuity':skin.curve_qa[clip],
                 'maximumTrunkVertexSweepM':float(movement[masks['trunk']].max()),
                 'maximumWingVertexSweepM':float(movement[masks['wing_l']+masks['wing_r']].max())}
        report[clip] = entry
        assert low[2] > .30 and seam < 1e-5 and velocity < .005 and acceleration < .05, entry
        assert max(rigidity.values()) < 1e-4 and feather_error < .025, entry
        assert max(max_strain.values()) < .20 and max(p99_strain.values()) < .08, entry
        assert .65 < area_ratio_low <= area_ratio_high < 1.35, entry
    def derivatives(clip,t):
        dt = .001
        a,b,c = [skin.points(clip,t+u*dt) for u in range(3)]
        return a,(b-a)/dt,(c-2*b+a)/dt**2
    idle,special = derivatives('idle',0.),derivatives('special',0.)
    match = {key:float(np.linalg.norm(a-b,axis=1).max()) for key,a,b in zip(('positionM','velocityMps','accelerationMps2'),idle,special)}
    assert match['positionM'] < 1e-5 and match['velocityMps'] < .001 and match['accelerationMps2'] < .01, match
    report['specialIdleSafeEndpointMatch'] = match
    report['maximumSweptBoundsBlenderSampled'] = [swept_lo.tolist(),swept_hi.tolist()]
    report['maximumSweptBoundsGltfSampled'] = [[swept_lo[0],swept_lo[2],-swept_hi[1]],[swept_hi[0],swept_hi[2],-swept_lo[1]]]
    report['maximumSweptBoundsStageYawPI4Sampled'] = [yaw_lo.tolist(),yaw_hi.tolist()]
    report['conservativeSweptBoundsGltfWith1cmPadding'] = [(np.array(report['maximumSweptBoundsGltfSampled'][0])-.01).tolist(),(np.array(report['maximumSweptBoundsGltfSampled'][1])+.01).tolist()]
    return report


def reimport_and_render(path, out, skin, masks):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = FPS
    bpy.context.scene.render.fps_base = 1.
    bpy.ops.import_scene.gltf(filepath=str(path), disable_bone_shape=True)
    obj = next(o for o in bpy.context.scene.objects if o.type == 'MESH')
    arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    assert len(arm.data.bones) == 34
    actions = {}
    for track in arm.animation_data.nla_tracks:
        track.mute = True
        for strip in track.strips:
            for name in DURATIONS:
                if track.name == name or strip.action.name == name:
                    actions[name] = strip.action
    assert set(actions) == set(DURATIONS)
    rest = np.array([tuple(obj.matrix_world@v.co) for v in obj.data.vertices])
    arm.animation_data.action = None
    camera = camera_setup(900)
    out.mkdir()
    center = np.array([0.,-.05,1.43])
    max_reimport_error = 0.
    image_tags = []
    for clip,duration in DURATIONS.items():
        arm.animation_data.action = actions[clip]
        for n in range(8):
            t = duration*n/8
            frame = t*FPS
            bpy.context.scene.frame_set(int(frame),subframe=frame-int(frame))
            bpy.context.view_layer.update()
            evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            points = np.array([tuple(evaluated.matrix_world@v.co) for v in mesh.vertices])
            evaluated.to_mesh_clear()
            cpu = skin.points(clip,t)
            assert points.shape == cpu.shape
            error = float(np.linalg.norm(points-cpu,axis=1).max())
            max_reimport_error = max(max_reimport_error,error)
            assert error < .0003, ('Reimport deviates from actual GLB skin',clip,t,error)
            tag = f'{clip}-{n:02}-t{t:.3f}'
            render_view(camera,out,tag+'-34',center,(.70,-.9,.35),3.95)
            image_tags.append(tag+'-34')
            if n in (0,2,4,6):
                render_view(camera,out,tag+'-front',center,(0,-1,.02),3.8)
                render_view(camera,out,tag+'-side',center,(1,0,.08),3.8)
            if n in (2,6):
                roots = points[masks['wing_root_l']+masks['wing_root_r']]
                target = (roots.min(axis=0)+roots.max(axis=0))/2
                render_view(camera,out,tag+'-roots-front',target,(0,-1,.25),1.32)
                render_view(camera,out,tag+'-roots-back',target,(0,1,.25),1.32)
                skull = points[masks['head']]
                render_view(camera,out,tag+'-head',(skull.min(axis=0)+skull.max(axis=0))/2,(.65,-1,.3),.72)
                for side in ('l','r'):
                    vane = points[masks['wing_'+side]]
                    target = (vane.min(axis=0)+vane.max(axis=0))/2
                    render_view(camera,out,tag+'-wing-'+side,target,(0,-1,.25),1.95)
    arm.animation_data.action = None
    # Subframe reimport verification catches import timebase / cubic interpolation errors.
    for clip,duration in DURATIONS.items():
        arm.animation_data.action = actions[clip]
        for t in (.173, duration*.317, duration-.023):
            f=t*FPS
            bpy.context.scene.frame_set(int(f),subframe=f-int(f))
            bpy.context.view_layer.update()
            evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh=evaluated.to_mesh()
            points=np.array([tuple(evaluated.matrix_world@v.co) for v in mesh.vertices])
            evaluated.to_mesh_clear()
            error=float(np.linalg.norm(points-skin.points(clip,t),axis=1).max())
            max_reimport_error=max(max_reimport_error,error)
            assert error < .0003, ('Subframe reimport cubic mismatch',clip,t,error)
    arm.animation_data.action=None
    return {'boneCount':34,'clipDurations':DURATIONS,'maximumAllVertexVsExactGltfEvaluatorErrorM':max_reimport_error,
            'renderedActualReimport':True,'keyPoseViews':image_tags}


def production_candidate(obj, points, preservation, cal, args, source, out):
    assert cal['anatomyMasksReviewed'] is True
    bpy.context.scene.render.fps=FPS
    bpy.context.scene.render.fps_base=1.
    masks=masks_from_calibration(obj,points,cal)
    normals,uv=per_vertex_attributes(obj)
    triangles=np.array([tuple(p.vertices) for p in obj.data.polygons])
    arm=make_rig(cal)
    weights=bind(obj,arm,points,masks,cal)
    arm.data.pose_position='REST'
    bpy.context.view_layer.update()
    evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    rest_check=np.array([tuple(evaluated.matrix_world@v.co) for v in evaluated.data.vertices])
    assert np.linalg.norm(rest_check-points,axis=1).max() < 1e-6, 'Native skeleton rest inversion'
    arm.data.pose_position='POSE'
    report={'schemaVersion':1,'beast':'yinglong','candidateOnly':True,'productionAccepted':False,
            'source':str(source),'sourceSha256':sha(source),'script':str(Path(__file__).resolve()),
            'scriptSha256':sha(Path(__file__).resolve()),'calibrationSha256':sha(args.calibration.resolve()),
            'helperSha256':{name:sha(TRUSTED/name) for name in ('rig_quadruped.py','rig_jiaochong_native.py','rig_zhuyan_native.py','turnaround.py')},
            'blenderVersion':bpy.app.version_string,'preservation':preservation,'runtimeContract':runtime_contract(),
            'bones':[{'name':b.name,'parent':b.parent.name if b.parent else None,'headBlender':list(b.head_local),'tailBlender':list(b.tail_local)} for b in arm.data.bones],
            'weights':{'unweighted':0,'maxInfluences':max(map(len,weights)),'fullHeadsRigid':True,'finalWingTipsRigid':True,
                       'wingOnlyBeyondAbsX':.38,'wingRootBlendAbsX':[.18,.38],'crossWingOrSpineWeightContamination':False},
            'maskCounts':{name:len(ids) for name,ids in masks.items()}}
    dump(out/'calibration.json',cal)
    (out/'rest-reference.json').write_text(json.dumps({'schemaVersion':1,'beast':'yinglong',
        'sourceSha256':report['sourceSha256'],'calibrationSha256':report['calibrationSha256'],
        'coordinates':COORDINATES,'gltfConversion':'[x,z,-y]; positions are final native world rest, includes permanent elevation',
        'indexDomain':'points indices are source Blender vertices before weights/export; match decoded world rest positions, not final GLB vertex order',
        'maskMethod':'Native edges plus seam duplicates rounded6 decimals; explicit reviewed half-plane cuts and seeds in calibration.json; masks made before weights',
        'points':np.round(points,9).tolist(),'masks':masks,
        'maskSemantics':{'head':'complete rigid skull/muzzle/eyes','trunk':'all native body/head/tail except calibrated wings','body':'trunk excluding rigid head',
            'wing_l':'native +X wing including broad blend collar, every feather, tips and native fragments','wing_r':'native -X wing including broad blend collar, every feather, tips and native fragments',
            'wing_root_l/r':'ipsilateral wing absX<0.38m; soft broad native collar','wing_tip_l/r':'ipsilateral wing absX>1.26m; rigid distal bone',
            'feather_l/r_NN':'geometry-only connected trailing vane patches below measured leading spar by0.18m; may include touching vanes; not individual feather count'}},separators=(',',':'))+'\n')
    dump(out/'weights-audit.json',report['weights'])
    diagnostic(obj,points,masks,cal,out/'masks')
    assert native_fingerprint(obj)==preservation['normalizedFingerprint']
    actions={name:animate(arm,name,duration) for name,duration in DURATIONS.items()}
    arm.animation_data.action=None
    for pb in arm.pose.bones:
        pb.location=(0,0,0)
        pb.rotation_quaternion=(1,0,0,0)
        pb.scale=(1,1,1)
    bpy.context.view_layer.update()
    assert native_fingerprint(obj)==preservation['normalizedFingerprint']
    assert array_sha([tuple(v.co) for v in obj.data.vertices])==preservation['restPositionsSha256']
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    arm.select_set(True)
    path=out/'rigged.glb'
    bpy.ops.export_scene.gltf(filepath=str(path),export_format='GLB',use_selection=True,
        export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False,
        export_extras=True,export_normals=True,export_texcoords=True,export_materials='EXPORT',
        export_image_format='AUTO',export_apply=False,export_force_sampling=True,export_frame_step=1,
        export_optimize_animation_size=False)
    report['nativeAttributePassthrough']=restore_native_payload(path,source,points,weights,uv,triangles)
    report['clips']=cubic_export(path)
    skin=GlbSkin(path)
    skin.path=str(path)
    exported_masks,report['exportedNativeRestQA']=rest_audit(skin,source,points,normals,uv,triangles,masks)
    assert report['exportedNativeRestQA']['nativePBR']==report['exportedNativeRestQA']['candidatePBR'], 'Native PBR/image bytes changed'
    dump(out/'native-rest-qa.json',report['exportedNativeRestQA'])
    report['motionQA']=motion_qa(skin,exported_masks)
    dump(out/'numerical-qa.json',report['motionQA'])
    report['reimport']=reimport_and_render(path,out/'reimport-poses',skin,exported_masks)
    magick=shutil.which('magick')
    if magick:
        for clip in DURATIONS:
            images=sorted((out/'reimport-poses').glob(clip+'-*-34.png'))
            assert len(images)==8
            subprocess.run([magick,'(',*[str(p) for p in images[:4]],'+append',')','(',*[str(p) for p in images[4:]],'+append',')',
                            '-append','-resize','1800x900',str(out/(clip+'-contact.png'))],check=True,timeout=60)
    report['candidateSha256']=sha(path)
    report['candidateBytes']=path.stat().st_size
    report['qaPassed']=True
    report['reproduceArgv']=[bpy.app.binary_path,'--background','--factory-startup','--disable-autoexec','--python-exit-code','1',
        '--python',str(Path(__file__).resolve()),'--',str(source),str(out.with_name(out.name+'-reproduce')),
        '--calibration',str(args.calibration.resolve()),'--accepted-source-sha256',report['sourceSha256']]
    report['limitations']=['Offline native rig candidate only; parent owns actual Stage/ink shader/crossfade/release acceptance.',
        'Uncompressed native PNG/PBR candidate exceeds runtime 15MB budget; parent must compress without topology edits and rerun Stage QA against rest-reference.json.',
        'Seven trailing connectivity patches can contain touching feather vanes; these are independent geometry protection probes, not a feather count.',
        'Native tiny fragments and 95 zero/nearly-zero facets are intentionally retained; no anatomical or manifold repair.',
        'Swept bounds are sampled at120Hz, with an additional1cm advisory margin; no exact global-extrema claim.',
        'C2 curves are built analytically as periodic cubic splines; reported residual second-derivative seam is Float32 GLB timing/tangent roundoff.']
    report['restReferenceSha256']=sha(out/'rest-reference.json')
    report['images']={str(p.relative_to(out)):sha(p) for p in out.rglob('*.png')}
    dump(out/'audit.json',report)
    print('YINGLONG_NATIVE_CANDIDATE',json.dumps({k:v for k,v in report.items() if k not in ('bones','images','preservation')}),flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--inspect', action='store_true')
    p.add_argument('--calibrate', action='store_true')
    p.add_argument('--calibration', type=Path)
    p.add_argument('--accepted-source-sha256')
    args = p.parse_args(sys.argv[sys.argv.index('--')+1:])
    source, out = args.source.resolve(strict=True), args.output.resolve()
    assert source.is_relative_to(ROOT/'raw') and source.suffix == '.glb'
    assert out.is_relative_to(ROOT/'raw/_build') and not out.exists(), 'Use new empty raw/_build output'
    out.mkdir(parents=True)
    source_hash = sha(source)
    obj, points, preservation = load_source(source)
    if args.inspect:
        inspect(obj, points, out)
        dump(out/'preservation.json', preservation)
    else:
        assert args.calibration and args.accepted_source_sha256 == source_hash
        cal = json.loads(args.calibration.resolve().read_text())
        assert cal['sourceSha256'] == source_hash and cal['acceptedForRiggingOnly'] is True
        assert cal['coordinates'] == COORDINATES
        if args.calibrate:
            masks = masks_from_calibration(obj, points, cal, review=False)
            cal['anatomyMasksReviewed'] = False
            diagnostic(obj, points, masks, cal, out/'masks')
            dump(out/'calibrated.json', cal)
            dump(out/'mask-summary.json', {name: describe(points, ids) for name, ids in masks.items()})
        else:
            production_candidate(obj, points, preservation, cal, args, source, out)
    assert sha(source) == source_hash


if __name__ == '__main__':
    main()
