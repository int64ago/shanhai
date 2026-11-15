"""Append a headless biped skin, planted-foot clips and rigid tool mounts.

Usage: Blender --background --disable-autoexec --python rig_xingtian.py --
       <prepared.glb> <rigged.glb> [--preview <image.png>] [--audit-out <report.json>]
Source geometry, normals, UVs, indices and PBR bytes are never rewritten.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from mathutils import Matrix
import xingtian_glb as glb

FPS = 30
DURATIONS = {'idle': 4., 'walk': 32., 'special': 4.8}
STEP_SECONDS = 2.
DUTY = .64
PARENTS = {'root': None, 'pelvis': 'root', 'chest': 'pelvis'}
for side in ['l', 'r']:
    for name, parent in [('hip', 'pelvis'), ('knee', 'hip_'+side), ('ankle', 'knee_'+side),
                         ('toe', 'ankle_'+side), ('shoulder', 'chest'), ('elbow', 'shoulder_'+side),
                         ('wrist', 'elbow_'+side), ('palm', 'wrist_'+side)]:
        PARENTS[name+'_'+side] = parent
NAMES = list(PARENTS)


def smooth(a, b, x):
    u = np.clip((np.asarray(x)-a)/(b-a), 0, 1)
    return u*u*(3-2*u)


def rot(axis, angle):
    c, s = math.cos(angle), math.sin(angle)
    if axis == 'x': return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == 'y': return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def align(a, b):
    a = a/np.linalg.norm(a); b = b/np.linalg.norm(b)
    v = np.cross(a, b); c = float(np.dot(a, b))
    if c <= -.999: raise ValueError('Antipodal limb orientation')
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3)+K+K@K/(1+c)


def native(document, binary):
    worlds = glb.world_matrices(document)
    node_index = next(i for i, node in enumerate(document['nodes']) if node.get('name') == 'xingtian_native_high_body')
    mesh = document['meshes'][document['nodes'][node_index]['mesh']]
    world = worlds[node_index]; primitives = []
    length = document['extras']['xingtianPreparation']['bodyLength']
    for primitive in mesh['primitives']:
        a = glb.array(document, binary, primitive['attributes']['POSITION'])
        p = (a@world[:3, :3].T+world[:3, 3])@glb.C.T/length
        f = glb.array(document, binary, primitive['indices']).reshape(-1, 3)
        primitives.append({'p': p, 'f': f, 'spec': primitive})
    points = np.concatenate([p['p'] for p in primitives])
    joints = {'root': np.zeros(3), 'pelvis': np.array([0, .02, .475]), 'chest': np.array([0, .005, .72])}
    for suffix, sign in [('l', 1), ('r', -1)]:
        def center(z, lower, upper):
            band = points[(sign*points[:, 0] > lower)&(sign*points[:, 0] < upper)&(abs(points[:, 2]-z) < .009)]
            if len(band) < 8: raise ValueError(f'Insufficient native joint samples: {suffix} {z}')
            return (band.min(0)+band.max(0))/2
        hip = np.array([sign*.105, .02, .475])
        knee = center(.285, .06, .235); knee[1] -= .022
        ankle = center(.065, .07, .24)
        shoulder = center(.81, .17, .31); shoulder[0] = sign*.225
        elbow = center(.675, .25, .39)
        wrist = center(.56, .34, .46)
        palm = np.array(document['extras']['xingtianPreparation']['gripsHeightNormalized'][str(sign)]['center'])
        foot = points[(sign*points[:, 0] > .05)&(abs(points[:, 0]) < .25)&(points[:, 2] < .11)]
        toe = np.array([ankle[0]+sign*.025, foot[:, 1].min()+.015, .012])
        for name, value in [('hip', hip), ('knee', knee), ('ankle', ankle), ('toe', toe),
                            ('shoulder', shoulder), ('elbow', elbow), ('wrist', wrist), ('palm', palm)]:
            joints[name+'_'+suffix] = value
    return {'node': node_index, 'world': world, 'primitives': primitives, 'joints': joints, 'length': length}


def protected_masks(points, joints):
    masks = {'chest_core': (abs(points[:, 0]) < .18)&(points[:, 2] > .51)}
    for side, sign in [('l', 1), ('r', -1)]:
        same = sign*points[:, 0] > 0
        masks['foot_'+side] = same&(abs(points[:, 0]) < .25)&(points[:, 2] < .112)
        wrist = joints['wrist_'+side]; elbow = joints['elbow_'+side]
        axis = wrist-elbow; axis /= np.linalg.norm(axis)
        masks['hand_'+side] = same&(abs(points[:, 0]) > .33)&(((points-wrist)@axis) >= -.006)
    return masks


def weight_fields(data):
    points = np.concatenate([pr['p'] for pr in data['primitives']]); joints = data['joints']
    index = {name: i for i, name in enumerate(NAMES)}; w = np.zeros((len(points), len(NAMES)))
    z = points[:, 2]; x = abs(points[:, 0]); chest = smooth(.46, .54, z)
    w[:, index['pelvis']] = 1-chest; w[:, index['chest']] = chest
    leg = (z < .51)&(x < .25)
    for suffix, sign in [('l', 1), ('r', -1)]:
        ids = np.flatnonzero(leg&(sign*points[:, 0] > 0)); zz = z[ids]
        pelvis = smooth(.40, .50, zz); foot = 1-smooth(.112, .175, zz); upper = smooth(.24, .35, zz)
        w[ids] = 0
        w[ids, index['pelvis']] = pelvis*(1-chest[ids]); w[ids, index['chest']] = pelvis*chest[ids]
        w[ids, index['hip_'+suffix]] = (1-pelvis)*(1-foot)*upper
        w[ids, index['knee_'+suffix]] = (1-pelvis)*(1-foot)*(1-upper)
        w[ids, index['ankle_'+suffix]] = (1-pelvis)*foot
        ids = np.flatnonzero(~leg&(sign*points[:, 0] > 0)); pp = points[ids]
        arm = smooth(.18, .255, abs(pp[:, 0]))*(1-smooth(.88, .96, pp[:, 2]))
        elbow = joints['elbow_'+suffix]; wrist = joints['wrist_'+suffix]
        axis = wrist-elbow; axis /= np.linalg.norm(axis)
        hand = smooth(-.05, -.006, (pp-wrist)@axis)
        lower = 1-smooth(elbow[2]-.06, elbow[2]+.06, pp[:, 2])
        w[ids] *= 1-arm[:, None]
        w[ids, index['shoulder_'+suffix]] += arm*(1-hand)*(1-lower)
        w[ids, index['elbow_'+suffix]] += arm*(1-hand)*lower
        w[ids, index['wrist_'+suffix]] += arm*hand
    # Virtual weld only for weight diffusion: original topology/UV seams stay fixed.
    unique, inverse = np.unique(np.round(points, 7), axis=0, return_inverse=True)
    pooled = np.zeros((len(unique), len(NAMES))); counts = np.bincount(inverse)
    np.add.at(pooled, inverse, w); pooled /= counts[:, None]
    offsets = np.cumsum([0]+[len(pr['p']) for pr in data['primitives']]); edges = []
    for i, pr in enumerate(data['primitives']):
        face = inverse[pr['f']+offsets[i]]
        edges += [np.sort(face[:, [a, b]], axis=1) for a, b in [(0, 1), (1, 2), (2, 0)]]
    edges = np.unique(np.concatenate(edges), axis=0); edges = edges[edges[:, 0] != edges[:, 1]]; a, b = edges.T
    conduct = 1/np.maximum(np.linalg.norm(unique[a]-unique[b], axis=1), .001)
    degree = np.bincount(a, weights=conduct, minlength=len(unique))+np.bincount(b, weights=conduct, minlength=len(unique))
    fixed_masks = protected_masks(unique, joints)
    fixed = np.logical_or.reduce(list(fixed_masks.values()))|((abs(unique[:, 0]) > .28)&(unique[:, 2] > .6))
    original = pooled.copy()
    for _ in range(80):
        neighbor = np.zeros_like(pooled)
        np.add.at(neighbor, a, pooled[b]*conduct[:, None]); np.add.at(neighbor, b, pooled[a]*conduct[:, None])
        connected = degree > 0
        pooled[connected] = .45*pooled[connected]+.55*(neighbor/np.maximum(degree[:, None], 1e-30))[connected]
        pooled[fixed] = original[fixed]
    full = pooled[inverse]
    arm_indices = [index[n+'_'+s] for s in ['l', 'r'] for n in ['shoulder', 'elbow', 'wrist', 'palm']]
    removed = full[:, arm_indices]*(1-smooth(.18, .255, abs(points[:, 0])))[:, None]
    full[:, arm_indices] -= removed; full[:, index['chest']] += removed.sum(1)
    masks = protected_masks(points, joints)
    for name, mask in masks.items():
        bone = 'chest' if name == 'chest_core' else ('ankle_' if name.startswith('foot') else 'wrist_')+name[-1]
        full[mask] = 0; full[mask, index[bone]] = 1
    order = np.argsort(-full, axis=1)[:, :4]; value = np.take_along_axis(full, order, axis=1); value /= value.sum(1)[:, None]
    assert np.isfinite(value).all() and np.max(abs(value.sum(1)-1)) < 1e-6
    return [(order[offsets[i]:offsets[i+1]].astype('<u2'), value[offsets[i]:offsets[i+1]].astype('<f4')) for i in range(len(data['primitives']))], masks


def travel(t):
    theta = math.tau*t/DURATIONS['walk']; speed = math.tau/DURATIONS['walk']
    xy = rot('z', -3*math.pi/4)@np.array([.22*math.sin(theta), .11*math.sin(2*theta), 0])
    tangent = rot('z', -3*math.pi/4)@np.array([.22*math.cos(theta)*speed, .22*math.cos(2*theta)*speed, 0])
    yaw = math.atan2(tangent[0], -tangent[1])
    return xy, yaw


def foot_target(name, t, side, data, soles):
    joints = data['joints']; ankle = joints['ankle_'+side]
    if name != 'walk': return ankle+np.array([0, 0, soles[side]]), np.eye(3), True
    shift = 0 if side == 'l' else .5
    absolute = t/STEP_SECONDS+shift; cycle = math.floor(absolute); phase = absolute-cycle
    landing = (cycle-shift)*STEP_SECONDS
    def plant(start):
        center, yaw = travel(start+DUTY*STEP_SECONDS/2)
        Q = rot('z', yaw); target = center+Q@ankle; target[2] += soles[side]
        return target, yaw
    first, yaw0 = plant(landing)
    if phase < DUTY: return first, rot('z', yaw0), True
    last, yaw1 = plant(landing+STEP_SECONDS); u = (phase-DUTY)/(1-DUTY); blend = float(smooth(0, 1, u))
    target = first*(1-blend)+last*blend; target[2] += .035*math.sin(math.pi*u)**2
    yaw = yaw0+math.atan2(math.sin(yaw1-yaw0), math.cos(yaw1-yaw0))*blend
    return target, rot('z', yaw), False


def pose(name, t, data, soles):
    j = data['joints']; osc = math.sin(math.tau*t/(STEP_SECONDS if name == 'walk' else DURATIONS[name]))
    display = float(smooth(.25, 1.0, t)*(1-smooth(3.8, 4.65, t))) if name == 'special' else 0
    center, yaw = travel(t) if name == 'walk' else (np.zeros(3), 0.)
    R = rot('z', yaw)
    delta = center+np.array([.002*osc if name == 'walk' else 0, 0,
                             -.018+.001*math.cos(2*math.tau*t/STEP_SECONDS) if name == 'walk' else -.012+.001*osc-.012*display])
    Q = {n: R.copy() for n in NAMES}; P = {n: delta+R@j[n] for n in NAMES}
    Q['chest'] = R@rot('x', .004*osc-.035*display)@rot('z', .008*osc if name == 'walk' else .035*display*osc)
    margins = []; planted = {}
    for side, sign in [('l', 1), ('r', -1)]:
        for n in ['shoulder', 'elbow', 'wrist', 'palm']:
            key = n+'_'+side; parent = PARENTS[key]
            if n == 'shoulder':
                swing = sign*.08*osc if name == 'walk' else .008*osc
                Q[key] = Q['chest']@rot('x', swing-(.28+.05*sign*osc)*display)
            elif n == 'elbow': Q[key] = Q[parent]@rot('x', -.14*display)
            else: Q[key] = Q[parent]
            P[key] = P[parent]+Q[parent]@(j[key]-j[parent])
        hip = delta+R@j['hip_'+side]
        target, footQ, is_planted = foot_target(name, t, side, data, soles); planted[side] = is_planted
        first = j['knee_'+side]-j['hip_'+side]; second = j['ankle_'+side]-j['knee_'+side]
        l1, l2 = np.linalg.norm(first), np.linalg.norm(second); axis = target-hip; distance = np.linalg.norm(axis)
        margin = l1+l2-distance
        if margin < 1e-6 or distance <= abs(l1-l2)+1e-6: raise ValueError(('Unreachable leg, no clamping', name, t, side, margin))
        direction = axis/distance; old = R@(first+second); old /= np.linalg.norm(old)
        pole = R@first-old*np.dot(R@first, old); pole -= direction*np.dot(pole, direction); pole /= np.linalg.norm(pole)
        along = (l1*l1-l2*l2+distance*distance)/(2*distance)
        knee = hip+direction*along+pole*math.sqrt(l1*l1-along*along)
        P['hip_'+side] = hip; P['knee_'+side] = knee; P['ankle_'+side] = target
        Q['hip_'+side] = align(R@first, knee-hip)@R; Q['knee_'+side] = align(R@second, target-knee)@R
        Q['ankle_'+side] = footQ; Q['toe_'+side] = footQ
        P['toe_'+side] = target+footQ@(j['toe_'+side]-j['ankle_'+side]); margins.append(margin)
    local = {n: Q[n] if PARENTS[n] is None else Q[PARENTS[n]].T@Q[n] for n in NAMES}
    return P, Q, local, min(margins), planted


def build(source, target):
    document, binary = glb.load(source); before = copy.deepcopy(document); original_binary = bytes(binary)
    data = native(document, binary); j = data['joints']; length = data['length']; weights, masks = weight_fields(data)
    index = {name: i for i, name in enumerate(NAMES)}; base = len(document['nodes'])
    positions = {n: glb.C.T@j[n]*length for n in NAMES}
    for name in NAMES:
        parent = PARENTS[name]; translation = positions[name] if parent is None else positions[name]-positions[parent]
        node = {'name': 'xingtian_'+name, 'translation': translation.tolist()}
        children = [base+index[n] for n in NAMES if PARENTS[n] == name]
        if children: node['children'] = children
        document['nodes'].append(node)
    for pr, (ids, values) in zip(data['primitives'], weights):
        pr['spec']['attributes']['JOINTS_0'] = glb.append(document, binary, ids, 'VEC4', 5123)
        pr['spec']['attributes']['WEIGHTS_0'] = glb.append(document, binary, values, 'VEC4')
    ibm = []
    for name in NAMES:
        inverse = np.eye(4); inverse[:3, 3] = -positions[name]; ibm.append(inverse@data['world'])
    accessor = glb.append(document, binary, np.array(ibm).transpose(0, 2, 1).reshape(-1, 16), 'MAT4')
    document['skins'] = [{'name': 'headless_biped_rigid_hands', 'inverseBindMatrices': accessor,
                          'joints': list(range(base, base+len(NAMES))), 'skeleton': base}]
    document['nodes'][data['node']]['skin'] = 0
    scene = document['scenes'][document.get('scene', 0)]; scene['nodes'].append(base)
    # Tools remain independent meshes. Rest matrix is relative to the same rigid wrist as the hand.
    for side, root_name in [('l', 'axe_grip_origin'), ('r', 'shield_grip_origin')]:
        tool = next(i for i, node in enumerate(document['nodes']) if node.get('name') == root_name)
        world = glb.matrix(document['nodes'][tool]); inverse = np.eye(4); inverse[:3, 3] = -positions['wrist_'+side]
        document['nodes'][tool] = {'name': root_name, 'matrix': (inverse@world).T.reshape(-1).tolist(),
                                   'children': document['nodes'][tool].get('children', [])}
        document['nodes'][base+index['wrist_'+side]].setdefault('children', []).append(tool)
        scene['nodes'].remove(tool)
    points = np.concatenate([pr['p'] for pr in data['primitives']])
    soles = {s: -float(points[masks['foot_'+s], 2].min()) for s in ['l', 'r']}
    document['animations'] = []; minimum = {}
    for name, duration in DURATIONS.items():
        times = np.linspace(0, duration, round(duration*FPS)+1).astype('<f4')
        time_index = glb.append(document, binary, times[:, None], 'SCALAR')
        qs = {n: [] for n in NAMES}; translations = []; margins = []
        for t in times:
            P, _, local, margin, _ = pose(name, float(t), data, soles); margins.append(margin)
            translations.append(glb.C.T@P['root']*length)
            for n in NAMES:
                q = Matrix(glb.C.T@local[n]@glb.C).to_quaternion(); value = np.array([q.x, q.y, q.z, q.w]); value /= np.linalg.norm(value)
                if qs[n] and np.dot(value, qs[n][-1]) < 0: value = -value
                qs[n].append(value)
        animation = {'name': name, 'samplers': [], 'channels': []}
        def channel(n, path, values, kind):
            output = glb.append(document, binary, np.array(values), kind)
            sampler = len(animation['samplers']); animation['samplers'].append({'input': time_index, 'output': output, 'interpolation': 'LINEAR'})
            animation['channels'].append({'sampler': sampler, 'target': {'node': base+index[n], 'path': path}})
        channel('root', 'translation', translations, 'VEC3')
        for n in NAMES: channel(n, 'rotation', qs[n], 'VEC4')
        document['animations'].append(animation); minimum[name] = min(margins)
    assert binary[:len(original_binary)] == original_binary
    for key in ['materials', 'images', 'textures', 'samplers']:
        assert document.get(key) == before.get(key), key
    for old, new in zip(before['meshes'], document['meshes']):
        for a, b in zip(old['primitives'], new['primitives']):
            assert a.get('indices') == b.get('indices')
            for k, v in a['attributes'].items(): assert b['attributes'][k] == v
    report = {'sourcePreparedSHA256': hashlib.sha256(Path(source).read_bytes()).hexdigest(),
              'sourceBinPrefixExact': True, 'sourceGeometryPBRExact': True,
              'jointCount': len(NAMES), 'jointsHeightNormalizedBlender': {k: v.tolist() for k, v in j.items()},
              'rigidMasks': {k: int(v.sum()) for k, v in masks.items()}, 'soleOffsets': soles,
              'minimumLegReachMargins': minimum, 'walkWorldTravelBakedIntoRoot': True,
              'walkDuration': DURATIONS['walk'], 'stepSeconds': STEP_SECONDS,
              'nativeHandGeometryChanged': False, 'ready': False}
    document['extras']['xingtianRig'] = report
    glb.save(target, document, binary)
    return report


def preview(path, target):
    import bpy
    from mathutils import Vector
    bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=str(path))
    scene = bpy.context.scene; scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = scene.render.resolution_y = 800; scene.render.resolution_percentage = 100
    world = bpy.data.worlds.new('preview'); world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (.5, .5, .5, 1); scene.world = world
    light = bpy.data.objects.new('key', bpy.data.lights.new('key', 'SUN')); light.data.energy = 2
    light.rotation_euler = (.4, -.5, -.4); scene.collection.objects.link(light)
    cam = bpy.data.objects.new('camera', bpy.data.cameras.new('camera')); cam.data.type = 'ORTHO'; cam.data.ortho_scale = 1.45
    cam.location = (1.2, -2, 1.1); cam.rotation_euler = (Vector((0, 0, .5))-cam.location).to_track_quat('-Z', 'Y').to_euler()
    scene.collection.objects.link(cam); scene.camera = cam; scene.render.filepath = str(target); bpy.ops.render.render(write_still=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('source'); parser.add_argument('out')
    parser.add_argument('--preview'); parser.add_argument('--audit-out')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:]); report = build(args.source, args.out)
    if args.audit_out:
        path = Path(args.audit_out); path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(report, indent=2))
    if args.preview: preview(args.out, args.preview)
    print('SKIN', json.dumps(report)); print('EXPORTED', args.out)


if __name__ == '__main__': main()
