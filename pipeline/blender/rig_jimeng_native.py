"""Jimeng-only native single-dragon-head candidate recipe. PREPARATION, NOT ACCEPTANCE.

Run only after the parent has reviewed and accepted the actual High source:
  blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
    --python pipeline/blender/rig_jimeng_native.py -- SOURCE.glb NEW_OUTPUT_DIR \
    --calibration REVIEWED.json --accepted-source-sha256 SHA256
An optional --inspect produces normalized measurements/views, never a rig. Neither
mode publishes anything. Output must be new, outside public/src/content.

No anatomical coordinates are guessed here. Calibration is JSON, not executable:
  schemaVersion: 1, beast: "jimeng", sourceSha256: <full hash>,
  sourceAnatomyAccepted: true, anatomyMasksReviewed: true,
  coordinates: "normalized Blender X/right Y/back Z/up, height=1.8m",
  landmarks: {
    body: {pelvis: [x,y,z], spine: [x,y,z], chest: [x,y,z]},
    head: {neckRoot: [...], headRoot: [...], headTip: [...]},
    limbs: {l: {hip: [...], knee: [...], ankle: [...], footTip: [...],
                 shoulder: [...], elbow: [...], wrist: [...], handTip: [...]}, r: ...}
  },
  masks: {head: SPEC, neck: SPEC,
          arm_l: SPEC, arm_r: SPEC, hand_l: SPEC, hand_r: SPEC,
          leg_l: SPEC, leg_r: SPEC, foot_l: SPEC, foot_r: SPEC,
          sole_l: SPEC, sole_r: SPEC, chest: SPEC, pelvis: SPEC}

Each source-calibrated SPEC has seeds (native vertex indices), planes (objects
with normal:[x,y,z], offset:number; allow dot(normal,point)<=offset), count (exact
reviewed vertex count), and indicesSha256 (SHA256 of sorted little-endian uint32
indices). Flood only inside those planes, along native edges and virtual seams
rounded to 6 decimal places. Every disconnected native shell needs its own seed.
Hand masks include palms, thumbs, every finger and nail; foot masks include heels,
soles and all toes/nails. Heads include complete faces, ears and skulls. Sole masks
are actual low contact patches, subsets of the complete foot masks. Arms include
hands; legs include feet. Other masks are disjoint. Chest/pelvis are protected
cores; unclassified torso blends only between shared hips and chest. The neck mask
covers the native neck below the single rigid complete dragon head. Diagnostic
colors and exported vertex masks must be visually reviewed after calibration.

Normalization is one positive uniform scale plus translation of decoded native
rest positions. No foot alignment, remesh, pruning, finger/mouth primitives,
normal recomputation, UV edits or PBR replacements. This file intentionally has
no default source hash, ape landmarks, anatomy gates or accepted final model.
"""
import argparse
import hashlib
import json
import math
import runpy
import sys
from pathlib import Path

sys.dont_write_bytecode = True
TRUSTED = Path(__file__).resolve().parent
sys.path.insert(0, str(TRUSTED))
import bpy
import numpy as np
from mathutils import Matrix, Vector
import rig_quadruped as base
from rig_jingwei import set_segment
from rig_zhuyan_native import render_view, segment_distance, smooth

FPS = 30
HEIGHT, RADIUS, SPEED, DUTY = 1.8, 1., .08, .66
DURATIONS = {'idle': 4., 'walk': 2.4, 'special': 4.}
SIDES = ('l', 'r')
MASK_NAMES = {f'{part}_{side}' for part in ('arm', 'hand', 'leg', 'foot', 'sole') for side in SIDES} | {'head', 'neck', 'chest', 'pelvis'}
COORDINATES = 'normalized Blender X/right Y/back Z/up, height=1.8m'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def array_sha(values, dtype='<f4'):
    return hashlib.sha256(np.asarray(values, dtype=dtype).tobytes()).hexdigest()


def runtime_contract():
    return {'restHeight': HEIGHT, 'radius': RADIUS, 'speed': SPEED, 'scale': 1.,
            'idleDuration': 4., 'walkSeconds': 2.4, 'specialDuration': 4.,
            'stanceDuty': DUTY, 'oppositeLegPhase': .5,
            'forward': 'glTF +Z / Blender -Y',
            'worldAngle': 'PI/2 - (0.08/1.0)*elapsedWalkSeconds',
            'worldPosition': '[radius*cos(angle), 0, radius*sin(angle)]',
            'worldYaw': 'PI-angle', 'startPosition': [0., 0., 1.], 'startYaw': math.pi/2,
            'animation': 'walk.timeScale=1; elapsedWalkSeconds matches mixer walk time continuously across repeats; root scale=1; accumulated world walk time MUST NOT reset on clip/action restart',
            'stance': 'inverse circular position AND sole yaw; full foot protected; duty .66; right phase +.5',
            'swing': 'quintic C2 recovery; sin^4 clearance',
            'transitions': 'no-slip guarantee applies to full-weight clips; fades need separate review'}


def native_fingerprint(obj):
    """Decoded topology, UVs, original corner normals and native PBR, not weights."""
    mesh = obj.data
    nodes, images = [], {}
    for mat in mesh.materials:
        assert mat and mat.use_nodes, 'Native node-based PBR materials required'
        entries = []
        for node in mat.node_tree.nodes:
            inputs = []
            for socket in node.inputs:
                if not hasattr(socket, 'default_value'):
                    continue
                value = socket.default_value
                if isinstance(value, (str, bool, int, float)):
                    converted = value
                else:
                    try:
                        converted = list(value)
                    except TypeError:
                        converted = str(value)
                inputs.append([socket.identifier, converted])
            entry = {'name': node.name, 'type': node.bl_idname, 'inputs': inputs}
            if node.type == 'TEX_IMAGE' and node.image:
                image = node.image
                assert image.packed_file, ('Expected self-contained native GLB image', image.name)
                images[image.name] = hashlib.sha256(bytes(image.packed_file.data)).hexdigest()
                entry['image'] = [image.name, image.colorspace_settings.name]
            entries.append(entry)
        links = sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in mat.node_tree.links)
        nodes.append({'name': mat.name, 'nodes': entries, 'links': links})
    # Read Blender's imported normals; never call a normal recomputation operator.
    normals = np.array([list(n.vector) for n in mesh.corner_normals])
    assert np.isfinite(normals).all()
    return {'vertices': len(mesh.vertices), 'faces': len(mesh.polygons),
            'edgesSha256': array_sha([list(e.vertices) for e in mesh.edges], '<u4'),
            'loopsSha256': array_sha([l.vertex_index for l in mesh.loops], '<u4'),
            'polygonSizesSha256': array_sha([p.loop_total for p in mesh.polygons], '<u4'),
            'polygonMaterialsSha256': array_sha([p.material_index for p in mesh.polygons], '<u4'),
            'uvSha256': {uv.name: array_sha([list(v.uv) for v in uv.data]) for uv in mesh.uv_layers},
            'cornerNormalsSha256': array_sha(normals),
            'pbrSha256': hashlib.sha256(json.dumps(nodes, sort_keys=True).encode()).hexdigest(),
            'embeddedImageSha256': images}


def load_native(source):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source), disable_bone_shape=True)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    assert len(meshes) == 1, ('Review unexpected mesh layout before extending recipe', len(meshes))
    obj = meshes[0]
    assert not obj.data.shape_keys, 'Native shape keys require separate preservation review'
    for node in bpy.context.scene.objects:
        if node.animation_data:
            node.animation_data.action = None
            for track in node.animation_data.nla_tracks:
                track.mute = True
        if node.type == 'ARMATURE':
            node.data.pose_position = 'REST'
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    assert obj.matrix_world.to_3x3().determinant() > 0, 'Negative native decode transform requires review'
    for modifier in list(obj.modifiers):
        assert modifier.type == 'ARMATURE', ('Unexpected source modifier', modifier.type)
        obj.modifiers.remove(modifier)
    # Apply the glTF native decoder/rest transform before recording preservation.
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for node in list(bpy.context.scene.objects):
        if node is not obj:
            bpy.data.objects.remove(node, do_unlink=True)
    obj.vertex_groups.clear()
    original = np.array([list(v.co) for v in obj.data.vertices], dtype=np.float64)
    assert len(original) and np.isfinite(original).all()
    lo, hi = original.min(axis=0), original.max(axis=0)
    assert hi[2] > lo[2]
    scale = HEIGHT/(hi[2]-lo[2])
    assert math.isfinite(scale) and scale > 0
    origin = np.array([(lo[0]+hi[0])/2, (lo[1]+hi[1])/2, lo[2]])
    before = native_fingerprint(obj)
    normals = np.array([tuple(n.vector) for n in obj.data.corner_normals])
    expected = (original-origin)*scale
    # Preserve the decoded source directions explicitly. Blender's compressed
    # custom-normal basis can drift on native near-degenerate facets even under
    # positive uniform scale; transfer original vectors, never recompute them.
    transform = Matrix.Diagonal((scale, scale, scale, 1.)) @ Matrix.Translation(-Vector(origin))
    obj.data.transform(transform)
    obj.data.update()
    obj.data.normals_split_custom_set(normals.tolist())
    after = native_fingerprint(obj)
    assert {k: v for k, v in after.items() if k != 'cornerNormalsSha256'} == {k: v for k, v in before.items() if k != 'cornerNormalsSha256'}, 'Native topology/UV/PBR preservation failed'
    normal_error = float(np.max(np.abs(np.array([tuple(n.vector) for n in obj.data.corner_normals])-normals)))
    assert normal_error < .0012, ('Imported normal direction exceeds disclosed Blender custom-normal codec tolerance', normal_error)
    actual = np.array([list(v.co) for v in obj.data.vertices])
    assert np.max(np.abs(actual-expected)) < 3e-7
    obj.name = 'jimeng_native_dragon_head_human_body'
    return obj, {'uniformScale': float(scale), 'decodedOrigin': origin.tolist(),
                 'decodedPositionsSha256': array_sha(original),
                 'normalizedPositionsSha256': array_sha(actual),
                 'decodedNativeFingerprint': before, 'nativeFingerprint': after,
                 'maxNormalizationNormalRoundoff': normal_error, 'geometryEdits': False,
                 'normalization': 'positive uniform scale plus translation only; source faces Blender -Y already'}, actual


def measurements(points):
    slices = []
    for ratio in np.arange(.025, 1., .05):
        band = points[np.abs(points[:, 2]/HEIGHT-ratio) < .015]
        if len(band):
            slices.append({'heightRatio': float(ratio), 'count': len(band), 'min': band.min(axis=0).tolist(), 'max': band.max(axis=0).tolist()})
    return {'bounds': [points.min(axis=0).tolist(), points.max(axis=0).tolist()],
            'height': float(np.ptp(points[:, 2])), 'slices': slices}


def connected_masks(obj, calibration, reviewed=True):
    """Selections are geometry-only, source-locked, and computed before weights."""
    assert set(calibration['masks']) == MASK_NAMES
    graph = [set() for _ in obj.data.vertices]
    coincident = {}
    for edge in obj.data.edges:
        a, b = edge.vertices
        graph[a].add(b)
        graph[b].add(a)
    for vertex in obj.data.vertices:
        key = tuple(round(float(v), 6) for v in vertex.co)
        if key in coincident:
            other = coincident[key]
            graph[vertex.index].add(other)
            graph[other].add(vertex.index)
        else:
            coincident[key] = vertex.index
    masks = {}
    for name, spec in calibration['masks'].items():
        assert spec['planes'] and spec['seeds'], ('Calibrate source gates/seeds', name)
        planes = [(Vector(p['normal']), float(p['offset'])) for p in spec['planes']]
        assert all(n.length > 0 and all(math.isfinite(x) for x in (*n, d)) for n, d in planes)
        def allowed(index):
            point = obj.data.vertices[index].co
            return all(point.dot(n) <= d for n, d in planes)
        seeds = spec['seeds']
        assert all(isinstance(i, int) and 0 <= i < len(graph) and allowed(i) for i in seeds), name
        found, pending = set(seeds), list(seeds)
        while pending:
            for other in graph[pending.pop()]:
                if other not in found and allowed(other):
                    found.add(other)
                    pending.append(other)
        ids = sorted(found)
        assert len(ids) >= 3, ('Empty anatomy mask', name)
        if reviewed:
            assert len(ids) == spec['count'], ('Review mask count', name, len(ids))
            assert array_sha(ids, '<u4') == spec['indicesSha256'], ('Review mask membership', name)
        else:
            spec['count'] = len(ids)
            spec['indicesSha256'] = array_sha(ids, '<u4')
        masks[name] = ids
    sets = {name: set(ids) for name, ids in masks.items()}
    for side in SIDES:
        assert sets[f'hand_{side}'] < sets[f'arm_{side}']
        assert sets[f'sole_{side}'] <= sets[f'foot_{side}'] < sets[f'leg_{side}']
        sole_z = [obj.data.vertices[i].co.z for i in masks[f'sole_{side}']]
        assert min(sole_z) >= -1e-6 and max(sole_z) < .055, ('Native sole patch outside reviewed underside band', side)
    # Only the explicit nested hand/arm, foot/leg/sole relationships may overlap.
    exclusive = ['head', 'neck', 'arm_l', 'arm_r', 'leg_l', 'leg_r', 'chest', 'pelvis']
    for index, name in enumerate(exclusive):
        for other in exclusive[index+1:]:
            assert not sets[name] & sets[other], ('Anatomical mask collision', name, other)
    return masks


def draft_calibration(obj, points, source_hash):
    """Source-specific v6 High gates; a draft still requires image review."""
    assert source_hash == 'ffac63d46490bf6c1177c9ecc8f8744491a4f089d2110e12a50f7a0342765556'
    def plane(normal, offset):
        return {'normal': normal, 'offset': offset}
    definitions = {
        'head': [plane([0,0,-1], -1.43)],
        'neck': [plane([0,0,-1], -1.35), plane([0,0,1],1.42999), plane([1,0,-.22],-.06201), plane([-1,0,-.22],-.09201)],
        'chest': [plane([0,0,-1],-1.10),plane([0,0,1],1.30),plane([1,0,0],.155),plane([-1,0,0],.12)],
        'pelvis': [plane([0,0,-1],-.835),plane([0,0,1],.96),plane([1,0,0],.175),plane([-1,0,0],.135)],
    }
    for side, sign, arm_cut, hand_cut in [('l',1,.062,.515),('r',-1,.092,.515)]:
        half = plane([-sign,0,0], -.020*sign)
        definitions['arm_'+side] = [plane([-sign,0,.22], arm_cut),plane([0,0,-1],-1.035)]
        definitions['hand_'+side] = [plane([-sign,0,0],-hand_cut)]
        definitions['leg_'+side] = [half,plane([0,0,1],.82)]
        definitions['foot_'+side] = [half,plane([0,0,1],.125)]
        definitions['sole_'+side] = [half,plane([0,0,1],.027)]
    graph = [set() for _ in points]
    for edge in obj.data.edges:
        a,b=edge.vertices; graph[a].add(b); graph[b].add(a)
    coincident = {}
    for i,p in enumerate(points):
        k=tuple(round(float(v),6) for v in p)
        if k in coincident:
            j=coincident[k]; graph[i].add(j); graph[j].add(i)
        else: coincident[k]=i
    masks = {}
    for name, planes in definitions.items():
        eligible = set(np.flatnonzero(np.logical_and.reduce([points@np.array(p['normal']) <= p['offset'] for p in planes])).tolist())
        remaining, seeds, component_sizes = eligible.copy(), [], []
        while remaining:
            seed=min(remaining); remaining.remove(seed); pending=[seed]; count=1
            while pending:
                for j in graph[pending.pop()]:
                    if j in remaining: remaining.remove(j); pending.append(j); count+=1
            seeds.append(seed); component_sizes.append(count)
        masks[name]={'planes':planes,'seeds':seeds,'draftComponents':component_sizes}
    return {'schemaVersion':1,'beast':'jimeng','sourceSha256':source_hash,
        'sourceAnatomyAccepted':True,'anatomyMasksReviewed':False,'coordinates':COORDINATES,
        'sourceAcceptance':'Parent personally reviewed native High four views, both palm/back and five-toed feet/soles; accepted for rigging only.',
        'sideConvention':'l is anatomical left, Blender +X (viewer right from front); source is asymmetric and landmarks are independent.',
        'landmarks':{
            'body':{'pelvis':[.020,.070,.865],'spine':[.020,.070,1.055],'chest':[.020,.092,1.325]},
            'head':{'neckRoot':[.020,.115,1.350],'headRoot':[.020,.104,1.460],'headTip':[.020,.060,1.690]},
            'limbs':{
                'l':{'hip':[.126,.078,.868],'knee':[.140,.051,.555],'ankle':[.186,.092,.120], 'footTip':[.244,-.126,.035],
                     'shoulder':[.235,.110,1.285],'elbow':[.374,.071,1.143],'wrist':[.515,-.033,1.165],'handTip':[.696,-.122,1.222]},
                'r':{'hip':[-.087,.079,.865],'knee':[-.094,.048,.550],'ankle':[-.142,.090,.120], 'footTip':[-.198,-.128,.034],
                     'shoulder':[-.205,.108,1.282],'elbow':[-.347,.062,1.145],'wrist':[-.515,-.050,1.187],'handTip':[-.697,-.123,1.246]}}},
        'masks':masks,'nativeSolePolicy':'Complete feet/undersides retain native unequal height, relief and outward toe splay. No foot-specific geometry alignment.'}


def make_rig(calibration):
    marks = calibration['landmarks']
    arm = bpy.data.objects.new('jimeng_rig', bpy.data.armatures.new('jimeng_native_anatomy'))
    bpy.context.scene.collection.objects.link(arm)
    bpy.ops.object.select_all(action='DESELECT')
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(name, start, end, parent=None):
        a, b = Vector(start), Vector(end)
        assert all(math.isfinite(x) for x in (*a, *b)) and (b-a).length > 1e-4, name
        item = arm.data.edit_bones.new(name)
        item.head, item.tail = a, b
        if parent:
            item.parent = arm.data.edit_bones[parent]
    body = marks['body']
    bone('root', (0, 0, 0), (0, 0, .18))
    bone('hips', body['pelvis'], body['spine'], 'root')
    bone('chest', body['spine'], body['chest'], 'hips')
    head = marks['head']
    bone('neck', head['neckRoot'], head['headRoot'], 'chest')
    bone('head', head['headRoot'], head['headTip'], 'neck')
    for side in SIDES:
        limb = marks['limbs'][side]
        bone(f'leg_{side}_upper', limb['hip'], limb['knee'], 'hips')
        bone(f'leg_{side}_lower', limb['knee'], limb['ankle'], f'leg_{side}_upper')
        bone(f'leg_{side}_foot', limb['ankle'], limb['footTip'], f'leg_{side}_lower')
        bone(f'arm_{side}_upper', limb['shoulder'], limb['elbow'], 'chest')
        bone(f'arm_{side}_lower', limb['elbow'], limb['wrist'], f'arm_{side}_upper')
        bone(f'arm_{side}_hand', limb['wrist'], limb['handTip'], f'arm_{side}_lower')
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(arm.data.bones) == 17
    return arm


def bind(obj, arm, masks):
    groups = {bone.name: obj.vertex_groups.new(name=bone.name) for bone in arm.data.bones}
    sets = {name: set(ids) for name, ids in masks.items()}
    regions, weights = [], []
    rigid = {'chest': 'chest', 'pelvis': 'hips', 'head': 'head'}
    for side in SIDES:
        rigid.update({f'hand_{side}': f'arm_{side}_hand', f'foot_{side}': f'leg_{side}_foot'})
    for vertex in obj.data.vertices:
        region = next((name for name in rigid if vertex.index in sets[name]), None)
        if region:
            w = {rigid[region]: 1.}
        else:
            names = ['hips', 'chest']
            region = 'body'
            for side in SIDES:
                if vertex.index in sets[f'arm_{side}']:
                    region = f'arm_{side}'
                    names = ['chest']+[f'arm_{side}_{part}' for part in ('upper', 'lower', 'hand')]
                elif vertex.index in sets[f'leg_{side}']:
                    region = f'leg_{side}'
                    names = ['hips']+[f'leg_{side}_{part}' for part in ('upper', 'lower', 'foot')]
            if vertex.index in sets['neck']:
                region = 'neck'
                names = ['chest', 'neck', 'head']
            values = {name: 1/max(.012, segment_distance(vertex.co, arm.data.bones[name]))**4 for name in names}
            total = sum(values.values())
            w = {name: value/total for name, value in values.items()}
            def blend_to(target, amount):
                nonlocal w
                w={k:v*(1-amount) for k,v in w.items()}
                w[target]=w.get(target,0)+amount
                w={k:v for k,v in w.items() if v>1e-12}
            if region.startswith('leg_'):
                # The native shorts form one joined crotch. Both lateral chains
                # must converge to the same hips transform at the medial seam.
                medial = smooth(.64,.76,vertex.co.z)*(1-smooth(.030,.100,abs(vertex.co.x-.020)))
                proximal = smooth(.64,.80,vertex.co.z)
                blend_to('hips',max(medial,proximal))
                blend_to(region+'_foot',1-smooth(.125,.19,vertex.co.z))
            elif region.startswith('arm_'):
                side=region[-1]; sign=1 if side=='l' else -1
                cut=.062 if side=='l' else .092
                gap=sign*vertex.co.x-.22*vertex.co.z+cut
                blend_to('chest',1-smooth(0,.065,gap))
                blend_to(region+'_hand',smooth(.465,.515,sign*vertex.co.x))
            elif region == 'neck':
                blend_to('chest',1-smooth(1.35,1.385,vertex.co.z))
                blend_to('head',smooth(1.375,1.43,vertex.co.z))
        assert 1 <= len(w) <= 4 and abs(sum(w.values())-1) < 1e-6
        assert all(math.isfinite(v) and v > 0 for v in w.values())
        for name, value in w.items():
            groups[name].add([vertex.index], value, 'REPLACE')
        regions.append(region)
        weights.append(w)
    for region, bone in rigid.items():
        assert all(weights[index] == {bone: 1.} for index in masks[region]), region
    for side in SIDES:
        assert all(not any(name.startswith('arm_') for name in weights[i]) for i in masks[f'leg_{side}'])
        assert all(not any(name.startswith('leg_') for name in weights[i]) for i in masks[f'arm_{side}'])
    modifier = obj.modifiers.new('Native complete heads palms and feet protected', 'ARMATURE')
    modifier.object = arm
    obj.parent = arm
    obj['nativeAnatomyCandidateOnly'] = True
    obj['restHeight'] = HEIGHT
    obj['runtimeContract'] = runtime_contract()
    return regions, weights


def contact(arm, leg, frame, delta, lateral=0., backward=0., lift=0., yaw=0.):
    """Trusted circular contact solve with this source's actual 3D knee pole.

    Preserve lateral native knee bends instead of projecting an upright human
    into the older helper's fixed Y/Z bending plane. Neutral stance is exact.
    """
    upper, lower, foot = [arm.pose.bones[leg+'_'+part] for part in ('upper', 'lower', 'foot')]
    rest_hip, rest_knee = upper.bone.head_local, upper.bone.tail_local
    hip, ankle = rest_hip+delta, foot.bone.head_local
    target = ankle+Vector((lateral, backward, lift))
    axis = target-hip
    distance, l1, l2 = axis.length, upper.bone.length, lower.bone.length
    assert abs(l1-l2)+1e-5 < distance < l1+l2, ('Unreachable native leg target', leg, frame, distance, l1+l2)
    direction = axis.normalized()
    rest_bend = rest_knee-rest_hip
    perpendicular = rest_bend-direction*rest_bend.dot(direction)
    assert perpendicular.length > 1e-5, 'Calibrated native knee pole is singular'
    perpendicular.normalize()
    along = (l1*l1-l2*l2+distance*distance)/(2*distance)
    knee = hip+direction*along+perpendicular*math.sqrt(max(0., l1*l1-along*along))
    if delta.length+lateral*lateral+backward*backward+lift*lift < 1e-10:
        assert (knee-rest_knee).length < 1e-5, 'Neutral knee must preserve native rest anatomy'
    set_segment(upper, hip, knee)
    set_segment(lower, knee, target)
    foot.matrix = Matrix.Translation(target) @ Matrix.Rotation(yaw, 4, 'Z') @ Matrix.Translation(-ankle) @ foot.bone.matrix_local
    bpy.context.view_layer.update()
    for bone in (upper, lower, foot):
        bone.keyframe_insert('rotation_quaternion', frame=frame)
        bone.keyframe_insert('location', frame=frame)


def animate(arm, name, seconds):
    action = base.new_action(arm, name)
    count = round(seconds*FPS)
    previous = {}
    for frame in range(count+1):
        phase = frame/count
        breath = math.sin(math.tau*phase)
        display = math.sin(math.pi*phase)**4 if name == 'special' else 0.
        delta = Vector((0, 0, -.012 if name == 'walk' else -.006*display))
        for pb in arm.pose.bones:
            pb.rotation_mode = 'QUATERNION'
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.location = (0, 0, 0)
            pb.scale = (1, 1, 1)
        chest = arm.pose.bones['chest']
        pose = {'chest': base.world_rot(chest, base.X, (.008+.012*display)*breath) @ base.world_rot(chest, base.Z, .025*display*breath)}
        neck, head = arm.pose.bones['neck'], arm.pose.bones['head']
        pose['neck'] = base.world_rot(neck, base.Z, .035*display*breath)
        pose['head'] = base.world_rot(head, base.Z, .012*breath+.18*display*breath)
        for side, sign, shift in [('l', 1, .2), ('r', -1, 1.1)]:
            upper, lower, hand = [arm.pose.bones[f'arm_{side}_{part}'] for part in ('upper', 'lower', 'hand')]
            swing = sign*.065*breath if name == 'walk' else .006*breath
            pose[upper.name] = base.world_rot(upper, base.X, swing-.11*display) @ base.world_rot(upper, base.Y, -sign*.20*display)
            pose[lower.name] = base.world_rot(lower, base.X, -.14*display)
            pose[hand.name] = base.world_rot(hand, base.X, .005*breath)
        base.key_loc(arm, frame, 'root', arm.data.bones['root'].matrix_local.to_3x3().inverted()@delta)
        base.key_pose(arm, frame, pose)
        bpy.context.view_layer.update()
        for side, offset in [('l', 0.), ('r', .5)]:
            lateral = backward = lift = yaw = 0.
            if name == 'walk':
                p = (phase+offset) % 1.
                if p < DUTY:
                    relative = seconds*(p-DUTY/2)
                else:
                    u = (p-DUTY)/(1-DUTY)
                    # Match stance velocity and acceleration at both swing ends.
                    relative = seconds*(DUTY/2+(1-DUTY)*u-10*u**3+15*u**4-6*u**5)
                    lift = .045*math.sin(math.pi*u)**4
                yaw = -SPEED/RADIUS*relative
                ankle = arm.data.bones[f'leg_{side}_foot'].head_local
                x, y = ankle.x-RADIUS, ankle.y
                lateral = RADIUS+math.cos(yaw)*x-math.sin(yaw)*y-ankle.x
                backward = math.sin(yaw)*x+math.cos(yaw)*y-ankle.y
            contact(arm, f'leg_{side}', frame, delta, lateral, backward, lift, yaw)
        # Every clip keys every transform, including stationary necks/feet/root.
        for pb in arm.pose.bones:
            if pb.name in previous and previous[pb.name].dot(pb.rotation_quaternion) < 0:
                pb.rotation_quaternion.negate()
            previous[pb.name] = pb.rotation_quaternion.copy()
            for channel in ('rotation_quaternion', 'location', 'scale'):
                pb.keyframe_insert(channel, frame=frame)
    base.finish_action(arm, action)
    for curve in base.action_fcurves(action):
        assert len(curve.keyframe_points) == count+1
        for key in curve.keyframe_points:
            key.interpolation = 'LINEAR'
            assert all(math.isfinite(v) for v in key.co)
    return action


def evaluated_points(obj, arm, seconds):
    frame = seconds*FPS
    bpy.context.scene.frame_set(int(frame), subframe=frame-int(frame))
    bpy.context.view_layer.update()
    assert all(pb.matrix.to_3x3().determinant() > 0 for pb in arm.pose.bones)
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        values = np.empty(len(mesh.vertices)*3)
        mesh.vertices.foreach_get('co', values)
        points = values.reshape((-1, 3)).copy()
        world = np.array(obj.matrix_world)
        assert np.linalg.det(world[:3, :3]) > 0
        points = points@world[:3, :3].T+world[:3, 3]
        assert np.isfinite(points).all()
        return points
    finally:
        evaluated.to_mesh_clear()


def attribute_weight_audit(obj, masks):
    points = np.array([list(v.co) for v in obj.data.vertices])
    normals = np.array([tuple(n.vector) for n in obj.data.corner_normals])
    assert np.isfinite(points).all() and np.isfinite(normals).all()
    normal_length_error = float(np.max(np.abs(np.linalg.norm(normals,axis=1)-1)))
    assert normal_length_error < .002
    for uv in obj.data.uv_layers:
        assert np.isfinite(np.array([tuple(v.uv) for v in uv.data])).all()
    protected = {'head':'head'}
    for s in SIDES:
        protected.update({'hand_'+s:'arm_'+s+'_hand','foot_'+s:'leg_'+s+'_foot','sole_'+s:'leg_'+s+'_foot'})
    sums, influences, rigid_error = [], [], 0.
    for v in obj.data.vertices:
        weights = [g.weight for g in v.groups]
        assert weights and all(math.isfinite(w) and w >= 0 for w in weights)
        sums.append(abs(sum(weights)-1)); influences.append(len(weights))
    assert max(sums)<3e-6 and max(influences)<=4
    for region,bone in protected.items():
        group=obj.vertex_groups[bone].index
        for i in masks[region]:
            weight=sum(g.weight for g in obj.data.vertices[i].groups if g.group==group)
            rigid_error=max(rigid_error,abs(1-weight))
    assert rigid_error<1e-6
    return {'finitePositionsNormalsUV':True,'maxNormalLengthError':normal_length_error,
        'unweighted':0,'maxInfluences':max(influences),'maxWeightSumError':max(sums),
        'maxProtectedWeightError':rigid_error,'protectedBoneMapping':protected}


def numerical_qa(obj, arm, masks, actions, rest):
    report = {}
    triangles = np.array([list(p.vertices) for p in obj.data.polygons],dtype=np.int32)
    assert triangles.shape[1]==3
    def areas(p):
        v=p[triangles]; return np.linalg.norm(np.cross(v[:,1]-v[:,0],v[:,2]-v[:,0]),axis=1)/2
    rest_areas=areas(rest)
    nondegenerate=rest_areas>1e-10
    protected = ['head']+[f'{part}_{side}' for part in ('hand', 'foot') for side in SIDES]
    for track in arm.animation_data.nla_tracks:
        track.mute = True
    for name, seconds in DURATIONS.items():
        arm.animation_data.action = actions[name]
        plants, sole_heights = {}, []
        drift = orientation = rigidity = 0.
        min_all_height = math.inf
        min_area_ratio = math.inf
        worst_triangle = None
        min_substantial_area_ratio = math.inf
        max_segment_length_error = 0.
        samples = round(seconds*120)*(2 if name == 'walk' else 1)
        for step in range(samples+1):
            absolute = step/120
            local = absolute % seconds if name == 'walk' else absolute
            points = evaluated_points(obj, arm, local)
            min_all_height = min(min_all_height, float(points[:,2].min()))
            area_values=areas(points)
            ratios=area_values[nondegenerate]/rest_areas[nondegenerate]
            min_substantial_area_ratio=min(min_substantial_area_ratio,float((area_values[rest_areas>1e-7]/rest_areas[rest_areas>1e-7]).min()))
            if float(ratios.min()) < min_area_ratio:
                min_area_ratio=float(ratios.min())
                index=int(np.flatnonzero(nondegenerate)[int(ratios.argmin())]); ids=triangles[index]
                worst_triangle={'time':absolute,'triangle':index,'vertices':ids.tolist(),'restArea':float(rest_areas[index]),'deformedArea':float(area_values[index]),'restPoints':rest[ids].tolist(),'posedPoints':points[ids].tolist(), 'memberships':[[k for k,v in masks.items() if int(i) in v] for i in ids]}
            for pb in arm.pose.bones:
                max_segment_length_error=max(max_segment_length_error,abs((pb.tail-pb.head).length-pb.bone.length))
            for region in protected:
                ids = masks[region]
                # Two fixed references check whole-region rigid distances.
                for anchor in (0, len(ids)//2):
                    error = np.max(np.abs(np.linalg.norm(points[ids]-points[ids[anchor]], axis=1)-np.linalg.norm(rest[ids]-rest[ids[anchor]], axis=1)))
                    rigidity = max(rigidity, float(error))
            for side, offset in [('l', 0.), ('r', .5)]:
                whole = points[masks[f'foot_{side}']].copy()
                sole = points[masks[f'sole_{side}']]
                if name == 'walk':
                    raw = absolute/seconds+offset
                    # Include support boundaries; sample-only swing intervals skip.
                    if raw % 1 >= DUTY:
                        continue
                    theta = math.pi/2-SPEED/RADIUS*absolute
                    phi = math.pi-theta
                    rotation = np.array([[math.cos(phi), -math.sin(phi), 0], [math.sin(phi), math.cos(phi), 0], [0, 0, 1]])
                    whole = whole@rotation.T+np.array([RADIUS*math.cos(theta), -RADIUS*math.sin(theta), 0])
                    key = (side, math.floor(raw))
                else:
                    key = (side, 0)
                sole_heights.extend(sole[:, 2].tolist())
                if key not in plants:
                    plants[key] = whole.copy()
                drift = max(drift, float(np.linalg.norm(whole-plants[key], axis=1).max()))
                orientation = max(orientation, float(np.linalg.norm((whole-whole.mean(axis=0))-(plants[key]-plants[key].mean(axis=0)), axis=1).max()))
        # Use explicit endpoints, not modulo-time samples. These are actual LINEAR
        # interpolation one-sided velocities, so clip-wrap defects cannot hide.
        dt = 1/300
        p0, p1, pm, pe = [evaluated_points(obj, arm, t) for t in (0., dt, seconds-dt, seconds)]
        seam = float(np.linalg.norm(pe-p0, axis=1).max())
        velocity_jump = float(np.linalg.norm((p1-p0)/dt-(pe-pm)/dt, axis=1).max())
        evidence = {'samples': samples+1, 'samplingHz': 120, 'minSoleHeight': min(sole_heights),
                    'minAllVertexHeight': min_all_height, 'maxSoleHeight': max(sole_heights), 'maxFullFootWorldStanceDrift': drift,
                    'maxFullFootOrientationDrift': orientation, 'maxProtectedShapeDrift': rigidity,
                    'allVertexLoopSeam': seam, 'maxAllVertexWrapVelocityJump': velocity_jump,
                    'wrapVelocityDt': dt, 'plantIntervals': len(plants),
                    'minNondegenerateTriangleAreaRatio': min_area_ratio, 'sourceNearDegenerateTrianglesExcluded': int((~nondegenerate).sum()),
                    'maxBoneSegmentLengthError': max_segment_length_error, 'boneSegmentLengthTolerance':3e-5,
                    'minSubstantialTriangleAreaRatio':min_substantial_area_ratio,'worstTriangle':worst_triangle,
                    'selection': 'reviewed connected rest anatomy before weights; evaluated native mesh'}
        report[name] = evidence
        assert min(sole_heights) >= -.001 and min_all_height >= -.001, evidence
        assert drift < .001 and orientation < .001 and rigidity < .0001, evidence
        assert seam < .0001 and velocity_jump < .01, evidence
        assert min_area_ratio > .05 and max_segment_length_error < 3e-5, evidence
    arm.animation_data.action = None
    return report


def render_diagnostics(obj, regions, masks, output, points):
    """Temporary diagnostic materials only; restore original PBR in finally."""
    output.mkdir()
    helpers = runpy.run_path(str(TRUSTED/'turnaround.py'), run_name='trusted_render_helpers')
    camera = helpers['setup_render'](1000)
    materials, indices = list(obj.data.materials), [p.material_index for p in obj.data.polygons]
    labels = ['body', 'chest', 'pelvis', 'head', 'neck', 'arm_l', 'arm_r', 'hand_l', 'hand_r', 'leg_l', 'leg_r', 'foot_l', 'foot_r', 'sole_l', 'sole_r']
    colors = [(.10,.18,.38,1),(.15,.28,.58,1),(.22,.15,.44,1),(.15,.8,.22,1),(.55,.85,.15,1),(.05,.6,.8,1),(.05,.4,.6,1),(.65,.1,.7,1),(.9,.2,.6,1),(.9,.25,.05,1),(.6,.15,.05,1),(.95,.75,.05,1),(.8,.55,.05,1),(.1,.8,.8,1),(.1,.6,.8,1)]
    display_regions = list(regions)
    for side in SIDES:
        for i in masks['sole_'+side]: display_regions[i] = 'sole_'+side
    obj.data.materials.clear()
    try:
        for label, color in zip(labels, colors):
            material = bpy.data.materials.new('jimeng_diagnostic_'+label)
            material.use_nodes = True
            shader = material.node_tree.nodes.get('Principled BSDF')
            shader.inputs['Base Color'].default_value = color
            shader.inputs['Emission Color'].default_value = color
            shader.inputs['Emission Strength'].default_value = .5
            obj.data.materials.append(material)
        for polygon in obj.data.polygons:
            names = [display_regions[i] for i in polygon.vertices]
            polygon.material_index = labels.index(max(names, key=names.count))
        center = (points.min(axis=0)+points.max(axis=0))/2
        size = max(float(np.ptp(points[:, 0])), HEIGHT)*1.15
        for tag, direction in [('front', (0,-1,0)), ('back', (0,1,0)), ('side', (1,0,0)), ('34', (.65,-.8,.15))]:
            render_view(camera, output, 'regions-'+tag, center, direction, size)
        for region in ['head', 'neck']+[f'{part}_{side}' for part in ('hand', 'foot', 'sole') for side in SIDES]:
            selected = points[masks[region]]
            target = (selected.min(axis=0)+selected.max(axis=0))/2
            crop = max(float(np.ptp(selected, axis=0).max())*1.45, .12)
            for tag, direction in [('front', (0,-1,.1)), ('back', (0,1,.1)), ('side', (1,0,.1)), ('underside', (0,-.2,-1))]:
                render_view(camera, output, region+'-'+tag, target, direction, crop)
    finally:
        obj.data.materials.clear()
        for material in materials:
            obj.data.materials.append(material)
        for polygon, index in zip(obj.data.polygons, indices):
            polygon.material_index = index


def render_landmarks(obj, calibration, output, points):
    """Temporary projection markers. Native mesh, UVs and materials stay untouched."""
    output.mkdir()
    helpers = runpy.run_path(str(TRUSTED/'turnaround.py'), run_name='trusted_render_helpers')
    camera = helpers['setup_render'](1000)
    marks = calibration['landmarks']
    groups = [('body', marks['body'], (.8,.3,.02,1)), ('head', marks['head'],(.1,.6,.1,1)),
              ('l', marks['limbs']['l'],(.8,.02,.5,1)), ('r', marks['limbs']['r'],(.02,.3,.8,1))]
    for tag, direction, axis, depth in [('front',(0,-1,0),1,-.31),('side',(1,0,0),0,.91)]:
        helpers_created=[]
        try:
            for group, landmarks, color in groups:
                material=bpy.data.materials.new('projection_'+group); material.diffuse_color=color
                projected={}
                for name, point in landmarks.items():
                    p=Vector(point); p[axis]=depth; projected[name]=p
                    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=.009, location=p)
                    marker=bpy.context.object; marker.name=group+'_'+name; marker.data.materials.append(material); helpers_created.append(marker)
                chains = [['hip','knee','ankle','footTip'],['shoulder','elbow','wrist','handTip']] if group in SIDES else [list(landmarks)]
                for chain in chains:
                    curve=bpy.data.curves.new('projected_chain','CURVE'); curve.dimensions='3D'; curve.bevel_depth=.0025; curve.bevel_resolution=1
                    spline=curve.splines.new('POLY'); spline.points.add(len(chain)-1)
                    for p, name in zip(spline.points,chain): p.co=(*projected[name],1)
                    line=bpy.data.objects.new('projected_chain',curve); bpy.context.scene.collection.objects.link(line); curve.materials.append(material); helpers_created.append(line)
            render_view(camera,output,'landmarks-'+tag,(.02,.05,.9),direction,2.05)
        finally:
            for helper in helpers_created: bpy.data.objects.remove(helper,do_unlink=True)


def render_poses(obj, arm, actions, output, points):
    output.mkdir()
    helpers = runpy.run_path(str(TRUSTED/'turnaround.py'), run_name='trusted_render_helpers')
    camera = helpers['setup_render'](1000)
    center = (points.min(axis=0)+points.max(axis=0))/2
    size = max(float(np.ptp(points[:, 0])), HEIGHT)*1.2
    for name, seconds in DURATIONS.items():
        arm.animation_data.action = actions[name]
        for step in range(6):
            t = seconds*step/6
            evaluated_points(obj, arm, t)
            render_view(camera, output, f'{name}-{t:.2f}', center, (.65,-.8,.18), size)
    arm.animation_data.action = None


def audit_reimport(path, output, original_points, original_masks, surface):
    """Reimport the actual GLB, remap anatomical masks geometrically, rerun QA."""
    from mathutils.kdtree import KDTree
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # glTF seconds become Blender frames at IMPORT time. Set the recipe timebase
    # before importing, otherwise factory 24fps invalidates 30fps motion checks.
    bpy.context.scene.render.fps = FPS
    bpy.context.scene.render.fps_base = 1.
    bpy.ops.import_scene.gltf(filepath=str(path), disable_bone_shape=True)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    arms = [o for o in bpy.context.scene.objects if o.type == 'ARMATURE']
    assert len(meshes) == 1 and len(arms) == 1
    obj, arm = meshes[0], arms[0]
    assert len(arm.data.bones) == 17
    actions = {}
    for track in arm.animation_data.nla_tracks:
        track.mute = True
        for strip in track.strips:
            for name in DURATIONS:
                if track.name == name or strip.action.name == name or strip.action.name.startswith(name+'_'):
                    actions[name] = strip.action
    assert set(actions) == set(DURATIONS), ('Imported clips', list(actions))
    assert all(abs(actions[name].frame_range[1]/FPS-duration) < 1e-5 for name, duration in DURATIONS.items()), 'Reimport must preserve seconds at the configured FPS'
    arm.animation_data.action = None
    arm.data.pose_position = 'REST'
    bpy.context.view_layer.update()
    rest = np.array([list(obj.matrix_world@v.co) for v in obj.data.vertices])
    assert obj.matrix_world.to_3x3().determinant() > 0 and arm.matrix_world.to_3x3().determinant() > 0
    tree = KDTree(len(original_points))
    for index, point in enumerate(original_points):
        tree.insert(point, index)
    tree.balance()
    mapping, max_error = [], 0.
    for point in rest:
        _, source_index, error = tree.find(point)
        mapping.append(source_index)
        max_error = max(max_error, error)
    assert max_error < 1e-5, ('Exported native rest coordinates changed', max_error)
    masks = {name: [] for name in original_masks}
    source_sets = {name: set(ids) for name, ids in original_masks.items()}
    for index, source_index in enumerate(mapping):
        for name, ids in source_sets.items():
            if source_index in ids:
                masks[name].append(index)
    assert all(masks.values()), 'Reimport lost protected source anatomy'
    # Match source corners by rest position plus UV, allowing only float/normal-codec roundoff.
    source_corners = [[] for _ in original_points]
    for i, vertex in enumerate(surface['loopVertices']): source_corners[vertex].append(i)
    candidates = []
    for point in rest:
        corners = [i for _,v,_ in tree.find_range(point, max(1e-6,max_error+1e-7)) for i in source_corners[v]]
        assert corners, ('No referenced source corner near exported rest vertex',point.tolist(),max_error)
        candidates.append(corners)
    uv_values = np.array([tuple(v.uv) for v in obj.data.uv_layers[0].data])
    normal_matrix = np.array(obj.matrix_world.to_3x3().inverted().transposed())
    normal_values = np.array([tuple(n.vector) for n in obj.data.corner_normals])@normal_matrix.T
    normal_values /= np.linalg.norm(normal_values,axis=1)[:,None]
    max_uv_error=max_normal_error=0.
    for i,loop in enumerate(obj.data.loops):
        ids=candidates[loop.vertex_index]
        uv_error=np.linalg.norm(surface['uv'][ids]-uv_values[i],axis=1)
        normal_error=np.max(np.abs(surface['normals'][ids]-normal_values[i]),axis=1)
        best=int(np.argmin(uv_error*1000+normal_error))
        max_uv_error=max(max_uv_error,float(uv_error[best])); max_normal_error=max(max_normal_error,float(normal_error[best]))
    assert max_uv_error<1e-6 and max_normal_error<.002, (max_uv_error,max_normal_error)
    imported_fp=native_fingerprint(obj)
    assert sorted(imported_fp['embeddedImageSha256'].values())==sorted(surface['images'].values()), 'Native encoded PBR images changed'
    assert len(obj.data.materials)==surface['materialCount']
    arm.data.pose_position = 'POSE'
    result = {'maxRestCoordinateError': max_error, 'vertices': len(rest),
              'faces': len(obj.data.polygons), 'maxRestUVError':max_uv_error,'maxRestNormalComponentError':max_normal_error,
              'nativeEncodedPbrImagesPreserved':True,'attributeWeightAudit':attribute_weight_audit(obj,masks),
              'numericalQA': numerical_qa(obj, arm, masks, actions, rest)}
    output.mkdir()
    helpers = runpy.run_path(str(TRUSTED/'turnaround.py'), run_name='trusted_render_helpers')
    camera = helpers['setup_render'](1000)
    center = (rest.min(axis=0)+rest.max(axis=0))/2
    size = max(float(np.ptp(rest[:, 0])), HEIGHT)*1.2
    (output/'qa.json').write_text(json.dumps(result,indent=2)+'\n')
    for name, seconds in DURATIONS.items():
        arm.animation_data.action = actions[name]
        steps = range(6) if name=='walk' else ((0,2,3,4) if name=='special' else (0,2,4))
        for step in steps:
            t = seconds*step/6
            evaluated_points(obj, arm, t)
            tag = f'{name}-{t:.2f}'
            render_view(camera, output, tag+'-34', center, (.65,-.8,.18), size)
            pose_points=evaluated_points(obj,arm,t)
            regions=[('feet',masks['foot_l']+masks['foot_r'],(.2,-1,.4)),
                     ('soles',masks['foot_l']+masks['foot_r'],(0,-.2,-1)),
                     ('head-neck',masks['head']+masks['neck'],(.25,-1,.1))]
            for side in SIDES:
                wrist=Vector(surface['landmarks']['limbs'][side]['wrist'])
                ids=[i for i in masks['arm_'+side] if (Vector(rest[i])-wrist).length<.105]+masks['hand_'+side]
                regions.append(('wrist-'+side,ids,(0,-1,.2)))
                knee=Vector(surface['landmarks']['limbs'][side]['knee'])
                ids=[i for i in masks['leg_'+side] if abs(rest[i,2]-knee.z)<.13]
                regions.append(('knee-'+side,ids,(.5,-1,.15)))
            for region,ids,direction in regions:
                selected=pose_points[ids]
                target=(selected.min(0)+selected.max(0))/2
                crop=max(float(np.ptp(selected,axis=0).max())*1.40,.22)
                render_view(camera,output,tag+'-'+region,target,direction,crop)
    arm.animation_data.action = None
    return result


def audit_export(path):
    """Check actual GLB animation buffers as well as pre-export Blender actions."""
    import struct
    payload = path.read_bytes()
    magic, version, length = struct.unpack_from('<4sII', payload)
    assert magic == b'glTF' and version == 2 and length == len(payload)
    document, binary, offset = None, None, 12
    while offset < length:
        size, kind = struct.unpack_from('<II', payload, offset)
        chunk = payload[offset+8:offset+8+size]
        if kind == 0x4e4f534a:
            document = json.loads(chunk)
        elif kind == 0x004e4942:
            binary = chunk
        offset += 8+size
    assert document and binary is not None
    def accessor(index):
        spec = document['accessors'][index]
        assert spec['componentType'] == 5126 and 'sparse' not in spec
        width = {'SCALAR': 1, 'VEC3': 3, 'VEC4': 4}[spec['type']]
        view = document['bufferViews'][spec['bufferView']]
        start = view.get('byteOffset', 0)+spec.get('byteOffset', 0)
        stride = view.get('byteStride', width*4)
        values = np.ndarray((spec['count'], width), dtype='<f4', buffer=binary,
                            offset=start, strides=(stride, 4)).copy()
        assert np.isfinite(values).all()
        return values
    result = {}
    animations = document.get('animations', [])
    assert len(animations) == 3 and {a['name'] for a in animations} == set(DURATIONS)
    for animation in animations:
        duration = DURATIONS[animation['name']]
        assert animation['channels']
        for channel in animation['channels']:
            sampler = animation['samplers'][channel['sampler']]
            times, values = accessor(sampler['input']).ravel(), accessor(sampler['output'])
            assert len(times) >= 2 and abs(float(times[0])) < 1e-6
            assert abs(float(times[-1])-duration) < 1e-5 and np.all(np.diff(times) > 0)
            interpolation = sampler.get('interpolation', 'LINEAR')
            assert interpolation == 'LINEAR' or (interpolation == 'STEP' and np.max(np.abs(values-values[0])) < 1e-7), ('Dynamic export must be LINEAR; Blender may emit static channels as STEP', animation['name'], channel['target'])
            if channel['target']['path'] == 'scale':
                assert (values > 0).all()
            if channel['target']['path'] == 'rotation':
                assert np.max(np.abs(np.linalg.norm(values, axis=1)-1)) < 1e-4
        result[animation['name']] = {'seconds': duration, 'channels': len(animation['channels']),
                                      'finite': True, 'positiveAnimatedScales': True}
    for node in document.get('nodes', []):
        assert all(math.isfinite(v) and v > 0 for v in node.get('scale', [1, 1, 1]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--inspect', action='store_true')
    modes.add_argument('--calibrate', action='store_true', help='Hash and render source-calibrated draft masks; never rig')
    modes.add_argument('--draft-calibration', action='store_true', help='Generate the source-locked v6 draft, masks and projected landmarks; never rig')
    parser.add_argument('--calibration', type=Path)
    parser.add_argument('--accepted-source-sha256')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    source, output = args.source.resolve(), args.output.resolve()
    assert source.is_file() and source.suffix.lower() == '.glb'
    assert not output.exists(), 'Use a new candidate output directory'
    repo = TRUSTED.parent.parent
    for protected in ('public', 'src', 'content'):
        assert not output.is_relative_to(repo/protected), 'Candidate outputs cannot touch runtime/content'
    source_hash = sha(source)
    calibration = None
    if not args.inspect and not args.draft_calibration:
        assert args.calibration and args.accepted_source_sha256 == source_hash, 'Explicit accepted High hash and calibration required'
        calibration = json.loads(args.calibration.resolve().read_text())
        assert calibration['schemaVersion'] == 1 and calibration['beast'] == 'jimeng'
        assert calibration['sourceSha256'] == source_hash
        assert calibration['sourceAnatomyAccepted'] is True
        assert args.calibrate or calibration['anatomyMasksReviewed'] is True
        assert calibration['coordinates'] == COORDINATES
    output.mkdir(parents=True)
    obj, preservation, points = load_native(source)
    if args.draft_calibration:
        assert args.accepted_source_sha256 == source_hash
        calibration = draft_calibration(obj, points, source_hash)
    report = {'beast': 'jimeng', 'source': str(source), 'sourceSha256': source_hash,
              'recipeSha256': sha(Path(__file__).resolve()), 'preservation': preservation,
              'measurements': measurements(points), 'runtimeContract': runtime_contract(),
              'productionAccepted': False, 'sourceAnatomyAccepted': calibration is not None,
              'preservationTolerances':{'normalizationPositionMeters':3e-7,'normalizationNormalComponent':.0012,'reimportPositionMeters':1e-5,'reimportUV':1e-6,'reimportNormalComponent':.002,'protectedShapeMeters':.0001,'fullFootStanceMeters':.001,'minimumVertexHeightMeters':-.001,'loopPositionMeters':.0001,'loopVelocityMetersPerSecond':.01,'boneSegmentLengthMeters':3e-5},
              'helperSha256': {name: sha(TRUSTED/name) for name in ('rig_quadruped.py', 'rig_jingwei.py', 'rig_zhuyan_native.py', 'turnaround.py')},
              'digitCount': 'requires actual anatomy image review; never inferred from bones or vertex counts'}
    if args.inspect:
        helpers = runpy.run_path(str(TRUSTED/'turnaround.py'), run_name='trusted_render_helpers')
        camera = helpers['setup_render'](1000)
        center = (points.min(axis=0)+points.max(axis=0))/2
        size = max(float(np.ptp(points[:, 0])), HEIGHT)*1.15
        for name, direction in [('front',(0,-1,0)), ('back',(0,1,0)), ('side',(1,0,0)), ('34',(.65,-.8,.18))]:
            render_view(camera, output, 'source-'+name, center, direction, size)
        np.save(output/'native-rest-points.npy', points, allow_pickle=False)
    elif args.calibrate or args.draft_calibration:
        masks = connected_masks(obj, calibration, reviewed=False)
        calibration['anatomyMasksReviewed'] = False
        priority = ['head', 'hand_l', 'hand_r', 'foot_l', 'foot_r', 'chest', 'pelvis', 'neck', 'arm_l', 'arm_r', 'leg_l', 'leg_r']
        selected = {name: set(ids) for name, ids in masks.items()}
        regions = [next((name for name in priority if i in selected[name]), 'body') for i in range(len(points))]
        render_diagnostics(obj, regions, masks, output/'masks', points)
        (output/'calibrated.json').write_text(json.dumps(calibration, indent=2)+'\n')
        (output/'masks.json').write_text(json.dumps(masks, separators=(',', ':'))+'\n')
        report['masks'] = {name: len(ids) for name, ids in masks.items()}
        report['anatomyMasksReviewed'] = False
        render_landmarks(obj, calibration, output/'landmarks', points)
        report['nativeSoles'] = {s: {'footBounds': [points[masks['foot_'+s]].min(0).tolist(), points[masks['foot_'+s]].max(0).tolist()], 'soleBounds': [points[masks['sole_'+s]].min(0).tolist(), points[masks['sole_'+s]].max(0).tolist()]} for s in SIDES}
    else:
        report['calibrationSha256'] = sha(args.calibration.resolve())
        (output/'calibration.json').write_text(args.calibration.resolve().read_text())
        masks = connected_masks(obj, calibration)
        arm = make_rig(calibration)
        regions, weights = bind(obj, arm, masks)
        obj['reviewedSourceSha256'] = source_hash
        report['masks'] = {name: {'count': len(ids), 'indicesSha256': array_sha(ids, '<u4')} for name, ids in masks.items()}
        report['landmarks'] = calibration['landmarks']
        report['weightsAudit'] = {'unweighted': 0, 'maxInfluences': max(map(len, weights)),
                                  'completeHeadRigid': True, 'completeHandsRigid': True, 'completeFeetRigid': True,
                                  'singleNeck': True, 'crossLimbContamination': False}
        (output/'masks.json').write_text(json.dumps({'sourceSha256': source_hash, 'coordinates': COORDINATES,
            'definitions': calibration['masks'], 'blenderVertexMasks': masks, 'regions': regions,
            'glTFCoordinateConversion': '[x,z,-y]; decode inverse-bind/dequantization before reconstructing masks'}, separators=(',', ':'))+'\n')
        (output/'weights.json').write_text(json.dumps(weights, separators=(',', ':'))+'\n')
        # Source geometry, independent of weights and exported vertex order, for
        # verifying complete anatomical regions after runtime compression.
        (output/'rest-reference.json').write_text(json.dumps({
            'schemaVersion':1,'beast':'jimeng','boneCount':17,
            'sourceSha256': source_hash, 'calibrationSha256': report['calibrationSha256'],
            'coordinates': 'Blender [x,y,z] normalized height1.8',
            'boneMapping':{'head':'head','neck':'neck',**{part+'_'+s:('arm_'+s+'_hand' if part=='hand' else 'leg_'+s+'_foot') for part in ('hand','foot','sole') for s in SIDES}},
            'points': np.round(points, 9).tolist(), 'masks': masks,
        }, separators=(',', ':'))+'\n')
        report['attributeWeightAudit'] = attribute_weight_audit(obj,masks)
        report['calibrationReview'] = calibration['reviewEvidence']
        report['nativeSoles'] = {s: {'minHeight':float(points[masks['foot_'+s],2].min()),'maxUndersideHeight':float(points[masks['sole_'+s],2].max()),'ankle':calibration['landmarks']['limbs'][s]['ankle']} for s in SIDES}
        assert native_fingerprint(obj) == preservation['nativeFingerprint']
        bpy.context.scene.render.fps = FPS
        bpy.context.scene.render.fps_base = 1.
        actions = {name: animate(arm, name, duration) for name, duration in DURATIONS.items()}
        report['numericalQA'] = numerical_qa(obj, arm, masks, actions, points)
        (output/'numerical-qa.json').write_text(json.dumps(report['numericalQA'], indent=2)+'\n')
        report['clips'] = {name: {'duration': duration, 'frames': list(actions[name].frame_range), 'allBonesKeyed': True} for name, duration in DURATIONS.items()}
        assert all(list(actions[name].frame_range) == [0., round(duration*FPS)] for name, duration in DURATIONS.items())
        render_poses(obj, arm, actions, output/'poses', points)
        arm.animation_data.action = None
        for pb in arm.pose.bones:
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.location = (0, 0, 0)
            pb.scale = (1, 1, 1)
        bpy.context.view_layer.update()
        assert native_fingerprint(obj) == preservation['nativeFingerprint']
        assert array_sha([list(v.co) for v in obj.data.vertices]) == preservation['normalizedPositionsSha256']
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        arm.select_set(True)
        bpy.ops.export_scene.gltf(filepath=str(output/'rigged.glb'), export_format='GLB', use_selection=True,
            export_animations=True, export_animation_mode='NLA_TRACKS', export_skins=True,
            export_def_bones=False, export_extras=True, export_normals=True)
        report['riggedSha256'] = sha(output/'rigged.glb')
        report['exportedClips'] = audit_export(output/'rigged.glb')
        report['boneCount'] = len(arm.data.bones)
        surface = {'landmarks':calibration['landmarks'],'loopVertices':[l.vertex_index for l in obj.data.loops],
                   'normals':np.array([tuple(n.vector) for n in obj.data.corner_normals]),
                   'uv':np.array([tuple(v.uv) for v in obj.data.uv_layers[0].data]),
                   'images':preservation['nativeFingerprint']['embeddedImageSha256'], 'materialCount':len(obj.data.materials)}
        report['reimport'] = audit_reimport(output/'rigged.glb', output/'reimport', points, masks, surface)
        assert report['reimport']['faces'] == preservation['nativeFingerprint']['faces']
        report['offlineRigQaPassed']=True
        report['riggedBytes']=(output/'rigged.glb').stat().st_size
    assert sha(source) == source_hash, 'Source changed during candidate generation'
    report['images'] = {str(p.relative_to(output)): sha(p) for p in output.rglob('*.png')}
    (output/'audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print('JIMENG_NATIVE_CANDIDATE', json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
