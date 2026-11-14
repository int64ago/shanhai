"""Jiaochong-only native two-human-head candidate recipe. PREPARATION, NOT ACCEPTANCE.

Run only after the parent has reviewed and accepted the actual High source:
  blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
    --python pipeline/blender/rig_jiaochong_native.py -- SOURCE.glb NEW_OUTPUT_DIR \
    --calibration REVIEWED.json --accepted-source-sha256 SHA256
An optional --inspect produces normalized measurements/views, never a rig. Neither
mode publishes anything. Output must be new, outside public/src/content.

No anatomical coordinates are guessed here. Calibration is JSON, not executable:
  schemaVersion: 1, beast: "jiaochong", sourceSha256: <full hash>,
  sourceAnatomyAccepted: true, anatomyMasksReviewed: true,
  coordinates: "normalized Blender X/right Y/back Z/up, height=1.8m",
  landmarks: {
    body: {pelvis: [x,y,z], spine: [x,y,z], chest: [x,y,z]},
    heads: {l: {neckRoot: [...], headRoot: [...], headTip: [...]}, r: ...},
    limbs: {l: {hip: [...], knee: [...], ankle: [...], footTip: [...],
                 shoulder: [...], elbow: [...], wrist: [...], handTip: [...]}, r: ...}
  },
  masks: {head_l: SPEC, head_r: SPEC, neck_l: SPEC, neck_r: SPEC,
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
cores; unclassified torso blends only between shared hips and chest. Neck masks
cover the separate short necks below their rigid full head masks. Diagnostic
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
MASK_NAMES = {f'{part}_{side}' for part in ('head', 'neck', 'arm', 'hand', 'leg', 'foot', 'sole') for side in SIDES} | {'chest', 'pelvis'}
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
            'animation': 'walk.timeScale=1; elapsedWalkSeconds matches mixer walk time continuously across repeats; root scale=1; reset elapsed time on restart',
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
    assert normal_error < 6e-4, ('Imported normal direction exceeds Blender custom-normal codec tolerance', normal_error)
    actual = np.array([list(v.co) for v in obj.data.vertices])
    assert np.max(np.abs(actual-expected)) < 3e-7
    obj.name = 'jiaochong_native_two_human_heads'
    return obj, {'uniformScale': float(scale), 'decodedOrigin': origin.tolist(),
                 'decodedPositionsSha256': array_sha(original),
                 'normalizedPositionsSha256': array_sha(actual),
                 'decodedNativeFingerprint': before, 'nativeFingerprint': after,
                 'maxNormalizationNormalRoundoff': normal_error, 'geometryEdits': False,
                 'normalization': 'positive uniform scale plus translation only'}, actual


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
        assert min(sole_z) < .003 and max(sole_z) < .004, ('Native soles need review; no geometry alignment allowed', side)
    # Only the explicit nested hand/arm, foot/leg/sole relationships may overlap.
    exclusive = ['head_l', 'head_r', 'neck_l', 'neck_r', 'arm_l', 'arm_r', 'leg_l', 'leg_r', 'chest', 'pelvis']
    for index, name in enumerate(exclusive):
        for other in exclusive[index+1:]:
            assert not sets[name] & sets[other], ('Anatomical mask collision', name, other)
    return masks


def make_rig(calibration):
    marks = calibration['landmarks']
    arm = bpy.data.objects.new('jiaochong_rig', bpy.data.armatures.new('jiaochong_native_anatomy'))
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
    for side in SIDES:
        head, limb = marks['heads'][side], marks['limbs'][side]
        neck_length = (Vector(head['headRoot'])-Vector(head['neckRoot'])).length
        assert .005 < neck_length < HEIGHT*.15, ('Calibrate short separate neck', side)
        bone(f'neck_{side}', head['neckRoot'], head['headRoot'], 'chest')
        bone(f'head_{side}', head['headRoot'], head['headTip'], f'neck_{side}')
        bone(f'leg_{side}_upper', limb['hip'], limb['knee'], 'hips')
        bone(f'leg_{side}_lower', limb['knee'], limb['ankle'], f'leg_{side}_upper')
        bone(f'leg_{side}_foot', limb['ankle'], limb['footTip'], f'leg_{side}_lower')
        bone(f'arm_{side}_upper', limb['shoulder'], limb['elbow'], 'chest')
        bone(f'arm_{side}_lower', limb['elbow'], limb['wrist'], f'arm_{side}_upper')
        bone(f'arm_{side}_hand', limb['wrist'], limb['handTip'], f'arm_{side}_lower')
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(arm.data.bones) == 19
    return arm


def bind(obj, arm, masks):
    groups = {bone.name: obj.vertex_groups.new(name=bone.name) for bone in arm.data.bones}
    sets = {name: set(ids) for name, ids in masks.items()}
    regions, weights = [], []
    rigid = {'chest': 'chest', 'pelvis': 'hips'}
    for side in SIDES:
        rigid.update({f'head_{side}': f'head_{side}', f'hand_{side}': f'arm_{side}_hand', f'foot_{side}': f'leg_{side}_foot'})
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
                elif vertex.index in sets[f'neck_{side}']:
                    region = f'neck_{side}'
                    names = ['chest', f'neck_{side}', f'head_{side}']
            values = {name: 1/max(.012, segment_distance(vertex.co, arm.data.bones[name]))**4 for name in names}
            total = sum(values.values())
            w = {name: value/total for name, value in values.items()}
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
        delta = Vector((0, 0, -.012 if name == 'walk' else 0))
        for pb in arm.pose.bones:
            pb.rotation_mode = 'QUATERNION'
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.location = (0, 0, 0)
            pb.scale = (1, 1, 1)
        pose = {'chest': base.world_rot(arm.pose.bones['chest'], base.X, .004*breath)}
        for side, sign, shift in [('l', 1, .2), ('r', -1, 1.1)]:
            # Complete rigid skulls turn independently over their separate short necks.
            neck, head = arm.pose.bones[f'neck_{side}'], arm.pose.bones[f'head_{side}']
            pose[neck.name] = base.world_rot(neck, base.Z, sign*.025*display)
            pose[head.name] = base.world_rot(head, base.Z, .008*math.sin(math.tau*phase+shift)+sign*.10*display*math.sin(math.tau*phase+shift))
            upper, lower, hand = [arm.pose.bones[f'arm_{side}_{part}'] for part in ('upper', 'lower', 'hand')]
            swing = sign*.065*breath if name == 'walk' else .006*breath
            pose[upper.name] = base.world_rot(upper, base.X, swing-.04*display) @ base.world_rot(upper, base.Y, -sign*.12*display)
            pose[lower.name] = base.world_rot(lower, base.X, -.045*display)
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


def numerical_qa(obj, arm, masks, actions, rest):
    report = {}
    protected = [f'{part}_{side}' for part in ('head', 'hand', 'foot') for side in SIDES]
    for track in arm.animation_data.nla_tracks:
        track.mute = True
    for name, seconds in DURATIONS.items():
        arm.animation_data.action = actions[name]
        plants, sole_heights = {}, []
        drift = orientation = rigidity = 0.
        samples = round(seconds*120)*(2 if name == 'walk' else 1)
        for step in range(samples+1):
            absolute = step/120
            local = absolute % seconds if name == 'walk' else absolute
            points = evaluated_points(obj, arm, local)
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
                    'maxSoleHeight': max(sole_heights), 'maxFullFootWorldStanceDrift': drift,
                    'maxFullFootOrientationDrift': orientation, 'maxProtectedShapeDrift': rigidity,
                    'allVertexLoopSeam': seam, 'maxAllVertexWrapVelocityJump': velocity_jump,
                    'wrapVelocityDt': dt, 'plantIntervals': len(plants),
                    'selection': 'reviewed connected rest anatomy before weights; evaluated native mesh'}
        report[name] = evidence
        assert min(sole_heights) > -.001 and max(sole_heights) < .005, evidence
        assert drift < .001 and orientation < .001 and rigidity < .0001, evidence
        assert seam < .0001 and velocity_jump < .01, evidence
    arm.animation_data.action = None
    return report


def render_diagnostics(obj, regions, masks, output, points):
    """Temporary diagnostic materials only; restore original PBR in finally."""
    output.mkdir()
    helpers = runpy.run_path(str(TRUSTED/'turnaround.py'), run_name='trusted_render_helpers')
    camera = helpers['setup_render'](1000)
    materials, indices = list(obj.data.materials), [p.material_index for p in obj.data.polygons]
    labels = ['body', 'chest', 'pelvis', 'head_l', 'head_r', 'neck_l', 'neck_r', 'arm_l', 'arm_r', 'hand_l', 'hand_r', 'leg_l', 'leg_r', 'foot_l', 'foot_r']
    colors = [( .10,.18,.38,1), (.15,.28,.58,1), (.22,.15,.44,1), (.15,.8,.22,1), (.55,.85,.15,1), (.4,.6,.25,1), (.7,.6,.25,1), (.05,.6,.8,1), (.05,.4,.6,1), (.65,.1,.7,1), (.9,.2,.6,1), (.9,.25,.05,1), (.6,.15,.05,1), (.95,.75,.05,1), (.8,.55,.05,1)]
    obj.data.materials.clear()
    try:
        for label, color in zip(labels, colors):
            material = bpy.data.materials.new('jiaochong_diagnostic_'+label)
            material.use_nodes = True
            shader = material.node_tree.nodes.get('Principled BSDF')
            shader.inputs['Base Color'].default_value = color
            shader.inputs['Emission Color'].default_value = color
            shader.inputs['Emission Strength'].default_value = .5
            obj.data.materials.append(material)
        for polygon in obj.data.polygons:
            names = [regions[i] for i in polygon.vertices]
            polygon.material_index = labels.index(max(names, key=names.count))
        center = (points.min(axis=0)+points.max(axis=0))/2
        size = max(float(np.ptp(points[:, 0])), HEIGHT)*1.15
        for tag, direction in [('front', (0,-1,0)), ('back', (0,1,0)), ('side', (1,0,0)), ('34', (.65,-.8,.15))]:
            render_view(camera, output, 'regions-'+tag, center, direction, size)
        for region in [f'{part}_{side}' for part in ('head', 'neck', 'hand', 'foot') for side in SIDES]:
            selected = points[masks[region]]
            target = (selected.min(axis=0)+selected.max(axis=0))/2
            crop = max(float(np.ptp(selected, axis=0).max())*1.45, .12)
            for tag, direction in [('front', (0,-1,.1)), ('back', (0,1,.1)), ('side', (1,0,.1))]:
                render_view(camera, output, region+'-'+tag, target, direction, crop)
    finally:
        obj.data.materials.clear()
        for material in materials:
            obj.data.materials.append(material)
        for polygon, index in zip(obj.data.polygons, indices):
            polygon.material_index = index


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


def audit_reimport(path, output, original_points, original_masks):
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
    assert len(arm.data.bones) == 19
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
    arm.data.pose_position = 'POSE'
    result = {'maxRestCoordinateError': max_error, 'vertices': len(rest),
              'faces': len(obj.data.polygons), 'numericalQA': numerical_qa(obj, arm, masks, actions, rest)}
    output.mkdir()
    helpers = runpy.run_path(str(TRUSTED/'turnaround.py'), run_name='trusted_render_helpers')
    camera = helpers['setup_render'](1000)
    center = (rest.min(axis=0)+rest.max(axis=0))/2
    size = max(float(np.ptp(rest[:, 0])), HEIGHT)*1.2
    for name, seconds in DURATIONS.items():
        arm.animation_data.action = actions[name]
        for step in (0, 1, 2):
            t = seconds*step/3
            evaluated_points(obj, arm, t)
            tag = f'{name}-{t:.2f}'
            render_view(camera, output, tag+'-34', center, (.65,-.8,.18), size)
            for region, ids in [('feet', masks['foot_l']+masks['foot_r']), ('dual-head-neck', masks['head_l']+masks['head_r']+masks['neck_l']+masks['neck_r'])]:
                region_points = rest[ids]
                target = (region_points.min(axis=0)+region_points.max(axis=0))/2
                crop = max(float(np.ptp(region_points, axis=0).max())*1.35, .2)
                direction = (.2,-1,.15) if region == 'feet' else (.25,-1,.1)
                render_view(camera, output, tag+'-'+region, target, direction, crop)
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
    if not args.inspect:
        assert args.calibration and args.accepted_source_sha256 == source_hash, 'Explicit accepted High hash and calibration required'
        calibration = json.loads(args.calibration.resolve().read_text())
        assert calibration['schemaVersion'] == 1 and calibration['beast'] == 'jiaochong'
        assert calibration['sourceSha256'] == source_hash
        assert calibration['sourceAnatomyAccepted'] is True
        assert args.calibrate or calibration['anatomyMasksReviewed'] is True
        assert calibration['coordinates'] == COORDINATES
    output.mkdir(parents=True)
    obj, preservation, points = load_native(source)
    report = {'beast': 'jiaochong', 'source': str(source), 'sourceSha256': source_hash,
              'recipeSha256': sha(Path(__file__).resolve()), 'preservation': preservation,
              'measurements': measurements(points), 'runtimeContract': runtime_contract(),
              'productionAccepted': False, 'sourceAnatomyAccepted': calibration is not None,
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
    elif args.calibrate:
        masks = connected_masks(obj, calibration, reviewed=False)
        calibration['anatomyMasksReviewed'] = False
        priority = ['head_l', 'head_r', 'hand_l', 'hand_r', 'foot_l', 'foot_r', 'chest', 'pelvis', 'neck_l', 'neck_r', 'arm_l', 'arm_r', 'leg_l', 'leg_r']
        selected = {name: set(ids) for name, ids in masks.items()}
        regions = [next((name for name in priority if i in selected[name]), 'body') for i in range(len(points))]
        render_diagnostics(obj, regions, masks, output/'masks', points)
        (output/'calibrated.json').write_text(json.dumps(calibration, indent=2)+'\n')
        (output/'masks.json').write_text(json.dumps(masks, separators=(',', ':'))+'\n')
        report['masks'] = {name: len(ids) for name, ids in masks.items()}
        report['anatomyMasksReviewed'] = False
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
                                  'completeHeadsRigid': True, 'completeHandsRigid': True, 'completeFeetRigid': True,
                                  'separateNecks': True, 'crossLimbContamination': False}
        (output/'masks.json').write_text(json.dumps({'sourceSha256': source_hash, 'coordinates': COORDINATES,
            'definitions': calibration['masks'], 'blenderVertexMasks': masks, 'regions': regions,
            'glTFCoordinateConversion': '[x,z,-y]; decode inverse-bind/dequantization before reconstructing masks'}, separators=(',', ':'))+'\n')
        (output/'weights.json').write_text(json.dumps(weights, separators=(',', ':'))+'\n')
        # Source geometry, independent of weights and exported vertex order, for
        # verifying complete anatomical regions after runtime compression.
        (output/'rest-reference.json').write_text(json.dumps({
            'sourceSha256': source_hash, 'calibrationSha256': report['calibrationSha256'],
            'coordinates': 'Blender [x,y,z] normalized height1.8',
            'points': np.round(points, 9).tolist(), 'masks': masks,
        }, separators=(',', ':'))+'\n')
        render_diagnostics(obj, regions, masks, output/'masks', points)
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
        report['reimport'] = audit_reimport(output/'rigged.glb', output/'reimport', points, masks)
        assert report['reimport']['faces'] == preservation['nativeFingerprint']['faces']
    assert sha(source) == source_hash, 'Source changed during candidate generation'
    report['images'] = {str(p.relative_to(output)): sha(p) for p in output.rglob('*.png')}
    (output/'audit.json').write_text(json.dumps(report, indent=2)+'\n')
    print('JIAOCHONG_NATIVE_CANDIDATE', json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
