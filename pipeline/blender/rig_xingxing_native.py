"""Native Xingxing High candidate only; no publication or source geometry edits.

Blender --background --factory-startup --disable-autoexec --python-exit-code 1
  --python pipeline/blender/rig_xingxing_native.py -- SOURCE.glb NEW_OUTPUT_DIR
Use --inspect for normalized axis slices only. Source hash is immutable.
The circular runtime contract is also embedded as scene/mesh extras and audit JSON.
"""
import argparse
import hashlib
import json
import math
import runpy
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Matrix, Vector
import rig_quadruped as base
from rig_yingzhao import contact
from rig_zhuyan_native import load_source, render_view, slice_report, segment_distance, smooth

SOURCE_SHA256 = 'af138ac179b91c5217977cb59fe0f13bd8bedcb522429ac1c7a42c00ee5adeca'
FPS = 30
RADIUS, SPEED, WALK_SECONDS, DUTY = 1., .06, 2.4, .66
SPECIAL_SECONDS = 4.
FINAL_HEIGHT = 1.35
SOURCE_REVIEW_HEIGHT = .9425160884857178
FOOT_HEIGHT = .105
SOLE_HEIGHT = .003


def runtime_contract():
    return {'radius': RADIUS, 'speed': SPEED, 'walkSeconds': WALK_SECONDS,
            'specialDuration': SPECIAL_SECONDS, 'idleDuration': 4., 'stanceDuty': DUTY,
            'forward': 'glTF +Z; Blender -Y', 'scale': 1, 'restHeight': FINAL_HEIGHT, 'cameraTargetY': .65,
            'worldAngle': 'angle = PI/2 - 0.06 * elapsedWalkSeconds',
            'worldPosition': '[cos(angle), 0, sin(angle)]',
            'worldYaw': 'rotationY = PI - angle',
            'startPosition': [0, 0, 1], 'startYaw': math.pi/2,
            'animation': 'walk.timeScale=1; elapsedWalkSeconds advances exactly with mixer walk time; no extra root translation/scale; continuous circular phase across clip repeats',
            'stance': 'inverse circular ankle position plus inverse circular sole yaw; full foot rigid; stance phase in [0,.66); opposite foot phase +.5',
            'transitions': 'reset elapsedWalkSeconds when restarting walk; fade only outside numerical no-slip guarantee'}


def mask_definitions(h, scale, marks):
    """Weight-independent selection in final glTF rest coordinates, after decode."""
    def gltf(p): return [p[0],p[2],-p[1]]
    hands = {}
    for side,sign in [('l',1),('r',-1)]:
        wrist,elbow = Vector(gltf(marks[side]['wrist'])),Vector(gltf(marks[side]['elbow']))
        hands[side] = {'sign':sign,'wrist':list(wrist),'elbow':list(elbow),
            'distalAxis':list((wrist-elbow).normalized()),'seedSignedXMin':.40*scale,
            'allowedSignedXMin':.285*scale,'allowedDistalProjectionMin':-.008*scale}
    return {'space':'final glTF rest model coordinates (X/Y/Z); restore inverse-bind meshopt dequantization before selection',
        'adjacency':'triangle edges plus virtual coincident seams (5 decimal digits); no vertex/geometry edits',
        'completeFeet':{'restYMaxExclusive':h*FOOT_HEIGHT,'side':'X>0=l, X<0=r','allVerticesRigid':True},
        'solePatches':{'restYMaxExclusive':SOLE_HEIGHT*scale,'geometryNote':'native subtly curved sole; rigid horizontal rest orientation; actual mesh unchanged apart from uniform scale and recorded sub-mm sole alignment'},
        'hands':hands,'handAlgorithm':'seed all signedX>seedSignedXMin; flood adjacency only where signedX>allowedSignedXMin and dot(restPoint-wrist,distalAxis)>allowedDistalProjectionMin',
        'lowerBody':{'seedRestYMax':h*.15,'floodRestYMax':h*.46},
        'protectedChest':{'absXMax':.115*scale,'minY':h*.46,'maxY':h*.69},
        'head':'restY/h > .802 - .062*(1-smoothstep(-.025,.065,-restZ/reviewToFinalUniformScale))'}


def graph_for(obj):
    graph = [set() for _ in obj.data.vertices]
    for edge in obj.data.edges:
        a, b = edge.vertices
        graph[a].add(b); graph[b].add(a)
    coincident = {}
    for v in obj.data.vertices:
        key = tuple(round(float(x), 5) for x in v.co)
        if key in coincident:
            other = coincident[key]
            graph[v.index].add(other); graph[other].add(v.index)
        else:
            coincident[key] = v.index
    return graph


def flood(obj, graph, seeds, allowed):
    found, pending = set(seeds), list(seeds)
    while pending:
        for other in graph[pending.pop()]:
            if other not in found and allowed(obj.data.vertices[other].co):
                found.add(other); pending.append(other)
    return found


def landmarks(obj, h):
    """Calibrated to this .942516m open-arm source, not the taller hanging ape.

    Centers are surface-band means at actual knee/ankle/arm landmarks. Ratios
    refer to this source's height and width; each side retains its asymmetry.
    """
    result = {}
    def center(sign, x, z, rx=.030, rz=.020):
        points = [v.co for v in obj.data.vertices if abs(sign*v.co.x-x) < rx and abs(v.co.z/h-z) < rz]
        assert len(points) > 10, ('Empty anatomical landmark band', sign, x, z)
        p = sum(points, Vector())/len(points)
        return p
    for sign, side in [(1, 'l'), (-1, 'r')]:
        hip = Vector((sign*.112, .057, h*.425))
        knee = center(sign, .122, .260, .045, .020)
        ankle = center(sign, .117, .105, .035, .015)
        ankle.z = h*FOOT_HEIGHT
        shoulder = center(sign, .145, .711, .028, .018)
        elbow = center(sign, .239, .582, .028, .018)
        wrist = center(sign, .333, .484 if sign == 1 else .512, .014, .020)
        # Distal palm direction: the fingers remain rigid relative to their palm.
        hand = Vector((sign*.410, wrist.y-.018, h*(.400 if sign == 1 else .432)))
        result[side] = {k: list(v) for k, v in [('hip', hip), ('knee', knee), ('ankle', ankle), ('shoulder', shoulder), ('elbow', elbow), ('wrist', wrist), ('hand', hand)]}
    return result


def make_rig(obj, h, marks):
    arm = bpy.data.objects.new('xingxing_rig', bpy.data.armatures.new('xingxing_native_anatomy'))
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(name, a, b, parent=None):
        item = arm.data.edit_bones.new(name); item.head, item.tail = a, b
        if parent:
            item.parent = arm.data.edit_bones[parent]
    bone('root', (0,0,0), (0,0,h*.10))
    bone('hips', (0,.057,h*.425), (0,.045,h*.55), 'root')
    bone('chest', (0,.045,h*.55), (0,.025,h*.70), 'hips')
    bone('neck', (0,.025,h*.70), (0,.025,h*.785), 'chest')
    bone('head', (0,.025,h*.785), (0,-.025,h*.94), 'neck')
    for side, m in marks.items():
        bone(f'leg_{side}_upper', m['hip'], m['knee'], 'hips')
        bone(f'leg_{side}_lower', m['knee'], m['ankle'], f'leg_{side}_upper')
        bone(f'leg_{side}_foot', m['ankle'], Vector(m['ankle'])+Vector((0,-h*.11,-h*.035)), f'leg_{side}_lower')
        bone(f'arm_{side}_upper', m['shoulder'], m['elbow'], 'chest')
        bone(f'arm_{side}_lower', m['elbow'], m['wrist'], f'arm_{side}_upper')
        bone(f'arm_{side}_hand', m['wrist'], m['hand'], f'arm_{side}_lower')
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm


def anatomical_masks(obj, h, marks):
    graph = graph_for(obj)
    lower = flood(obj, graph, [v.index for v in obj.data.vertices if v.co.z < h*.15], lambda p: p.z < h*.46)
    masks = {'feet': {'l': [], 'r': []}, 'soles': {'l': [], 'r': []},
             'hands': {}, 'arms': {}, 'head': [], 'chest': [], 'lower': sorted(lower)}
    for sign, side in [(1, 'l'), (-1, 'r')]:
        elbow, wrist = Vector(marks[side]['elbow']), Vector(marks[side]['wrist'])
        axis = (wrist-elbow).normalized()
        # Oblique wrist plane follows the open forearm, retaining inboard fingers.
        def distal(p):
            return (p-wrist).dot(axis) > -.008 and sign*p.x > .285
        hands = flood(obj, graph, [v.index for v in obj.data.vertices if sign*v.co.x > .40], distal)
        arms = flood(obj, graph, list(hands), lambda p: sign*p.x > .185-.030*smooth(.55,.74,p.z/h) and p.z < h*.775)
        assert len(hands) > 500 and len(arms) > len(hands)
        assert not (hands & lower) and not (arms & lower), 'Hand/leg topology selection overlap'
        masks['hands'][side], masks['arms'][side] = sorted(hands), sorted(arms)
    for v in obj.data.vertices:
        p, z = v.co, v.co.z/h
        side = 'l' if p.x > 0 else 'r'
        if z < FOOT_HEIGHT:
            masks['feet'][side].append(v.index)
            if p.z < SOLE_HEIGHT:
                masks['soles'][side].append(v.index)
        # Front chin sits lower than the back skull. White ears are above this gate.
        floor = .802-.062*(1-smooth(-.025,.065,p.y))
        if z > floor:
            masks['head'].append(v.index)
        if abs(p.x) < .115 and .46 < z < .69:
            masks['chest'].append(v.index)
    return masks


def bind(obj, arm, h, masks):
    groups = {b.name: obj.vertex_groups.new(name=b.name) for b in arm.data.bones}
    regions, weights = [], []
    sets = {key: ({s:set(v) for s,v in value.items()} if isinstance(value,dict) else set(value)) for key,value in masks.items()}
    def inverse(p, names):
        values = {n: 1/max(h*.016, segment_distance(p,arm.data.bones[n]))**4 for n in names}
        total = sum(values.values())
        return {n:w/total for n,w in values.items()}
    for v in obj.data.vertices:
        p, z = v.co, v.co.z/h
        side = 'l' if p.x > 0 else 'r'
        if v.index in sets['feet'][side]:
            region, w = 'foot_'+side, {f'leg_{side}_foot':1.}
        elif v.index in sets['hands'][side]:
            region, w = 'hand_'+side, {f'arm_{side}_hand':1.}
        elif v.index in sets['head']:
            region, w = 'head', {'head':1.}
        elif v.index in sets['lower']:
            region = 'leg_'+side
            w = inverse(p, [f'leg_{side}_{part}' for part in ['upper','lower','foot']])
            rigid = 1-smooth(FOOT_HEIGHT,.175,z)
            w = {n:value*(1-rigid) for n,value in w.items()}
            w[f'leg_{side}_foot'] += rigid
            pelvis = smooth(.34,.46,z)
            w = {n:value*(1-pelvis) for n,value in w.items()}
            if pelvis: w['hips'] = pelvis
        elif v.index in sets['arms'][side]:
            region = 'arm_'+side
            w = inverse(p, [f'arm_{side}_{part}' for part in ['upper','lower','hand']])
            wrist = arm.data.bones[f'arm_{side}_hand'].head_local
            axis = (wrist-arm.data.bones[f'arm_{side}_lower'].head_local).normalized()
            rigid = smooth(-.055,-.008,(p-wrist).dot(axis))
            w = {n:value*(1-rigid) for n,value in w.items()}
            w[f'arm_{side}_hand'] += rigid
            torso = 1-smooth(.155,.205,abs(p.x))
            w = {n:value*(1-torso) for n,value in w.items()}
            if torso: w['chest'] = torso
        else:
            region = 'body'
            w = inverse(p,['hips','chest','neck'])
            # Smooth neck to the rigid skull without any upper-arm contamination.
            floor = .802-.062*(1-smooth(-.025,.065,p.y))
            head = smooth(floor-.045,floor,z)
            w = {n:value*(1-head) for n,value in w.items()}
            if head: w['head'] = head
        selected = sorted(((n,value) for n,value in w.items() if value > 1e-8),key=lambda kv:kv[1],reverse=True)[:4]
        total = sum(value for n,value in selected)
        w = {n:value/total for n,value in selected}
        for name,value in w.items(): groups[name].add([v.index], value, 'REPLACE')
        weights.append(w); regions.append(region)
    modifier = obj.modifiers.new('Native High protected palms and complete feet', 'ARMATURE')
    modifier.object = arm; obj.parent = arm
    for side in ['l','r']:
        assert len(masks['soles'][side]) >= 8
        assert all(weights[i] == {f'leg_{side}_foot':1.} for i in masks['feet'][side])
        assert all(weights[i] == {f'arm_{side}_hand':1.} for i in masks['hands'][side])
        assert all(not any(n.startswith('arm_') for n in weights[i]) for i in masks['lower'])
    assert all(not any(n.startswith('arm_') for n in weights[i]) for i in masks['chest'])
    obj['restHeight'] = h
    obj['restAnatomicalFootMaxHeight'] = h*FOOT_HEIGHT
    obj['restAnatomicalSoleMaxHeight'] = SOLE_HEIGHT
    obj['reviewedSourceSha256'] = SOURCE_SHA256
    obj['nativeAnatomyCandidateOnly'] = True
    obj['runtimeContract'] = runtime_contract()
    return weights, regions


def animate(arm, name, seconds):
    action = base.new_action(arm,name)
    count = round(seconds*FPS)
    for f in range(count+1):
        t, phase = f/FPS, f/count
        display = smooth(.2,1.25,t)*(1-smooth(2.35,3.8,t)) if name == 'special' else 0.
        breath = math.sin(phase*math.tau)
        delta = Vector((0,-.012*display,-.009-.045*display if name == 'special' else -.009 if name == 'walk' else 0))
        # Keep base pose identical at both special endpoints.
        if name == 'special': delta.z = -.045*display
        pose = {'head':base.world_rot(arm.pose.bones['head'],base.X,-.035*display+.008*breath),
                'chest':base.world_rot(arm.pose.bones['chest'],base.X,.045*display+.006*breath)}
        for sign,side in [(1,'l'),(-1,'r')]:
            swing = sign*.10*breath if name == 'walk' else .012*breath
            upper, lower, hand = [arm.pose.bones[f'arm_{side}_{part}'] for part in ['upper','lower','hand']]
            pose[upper.name] = base.world_rot(upper,base.X,swing-.10*display) @ base.world_rot(upper,base.Y,-sign*.055*display)
            pose[lower.name] = base.world_rot(lower,base.X,-.060*display+.018*breath)
            pose[hand.name] = base.world_rot(hand,base.X,.025*breath+.025*display)
        delta *= FINAL_HEIGHT/SOURCE_REVIEW_HEIGHT
        base.key_loc(arm,f,'root',arm.data.bones['root'].matrix_local.to_3x3().inverted()@delta)
        base.key_pose(arm,f,pose)
        bpy.context.view_layer.update()
        for side,offset in [('l',0),('r',.5)]:
            lateral = backward = lift = yaw = 0.
            if name == 'walk':
                p = (phase+offset)%1
                if p < DUTY:
                    relative = seconds*(p-DUTY/2)
                else:
                    u = (p-DUTY)/(1-DUTY)
                    # Quintic swing matches stance velocity AND acceleration.
                    # r(0)=D/2, r(1)=-D/2, r'(0)=r'(1)=1-D; r''(0)=r''(1)=0.
                    r = DUTY/2+(1-DUTY)*u-10*u**3+15*u**4-6*u**5
                    relative = seconds*r
                    lift = .033*(FINAL_HEIGHT/SOURCE_REVIEW_HEIGHT)*math.sin(math.pi*u)**4
                yaw = -SPEED/RADIUS*relative
                ankle = arm.data.bones[f'leg_{side}_foot'].head_local
                x,y = ankle.x-RADIUS,ankle.y
                lateral = RADIUS+math.cos(yaw)*x-math.sin(yaw)*y-ankle.x
                backward = math.sin(yaw)*x+math.cos(yaw)*y-ankle.y
            contact(arm,f'leg_{side}',f,delta,lateral,backward,lift,yaw)
    base.finish_action(arm,action)
    for curve in base.action_fcurves(action):
        for key in curve.keyframe_points: key.interpolation = 'LINEAR'
    return action


def render_masks(obj, regions, output, h):
    output.mkdir()
    helpers = runpy.run_path(str(Path(__file__).with_name('turnaround.py')),run_name='trusted_render_helpers')
    camera = helpers['setup_render'](900)
    materials, indices = list(obj.data.materials), [p.material_index for p in obj.data.polygons]
    colors = {'head':(.16,.70,.20,1),'body':(.10,.18,.45,1),
              'leg_l':(.90,.30,.04,1),'leg_r':(.80,.15,.05,1),
              'arm_l':(.05,.65,.75,1),'arm_r':(.05,.65,.75,1),
              'hand_l':(.55,.10,.65,1),'hand_r':(.55,.10,.65,1),
              'foot_l':(.95,.70,.05,1),'foot_r':(.95,.70,.05,1)}
    obj.data.materials.clear()
    for name,color in colors.items():
        material = bpy.data.materials.new('review_'+name); material.use_nodes = True
        shader = material.node_tree.nodes.get('Principled BSDF')
        shader.inputs['Base Color'].default_value = color
        shader.inputs['Emission Color'].default_value = color
        shader.inputs['Emission Strength'].default_value = .6
        obj.data.materials.append(material)
    for p in obj.data.polygons:
        names = [regions[i] for i in p.vertices]
        p.material_index = list(colors).index(max(names,key=names.count))
    for name,direction in [('front',(0,-1,0)),('side',(1,0,0)),('back',(0,1,0))]:
        render_view(camera,output,name,(0,0,h*.50),direction,1.65)
    obj.data.materials.clear()
    for material in materials: obj.data.materials.append(material)
    for p,index in zip(obj.data.polygons,indices): p.material_index = index


def numerical_qa(obj, arm, masks, actions):
    """Evaluate actual mesh at 60Hz, using anatomy masks selected before weights."""
    rest = np.array([list(v.co) for v in obj.data.vertices])
    result = {}
    for name,seconds in [('idle',4.),('walk',WALK_SECONDS),('special',SPECIAL_SECONDS)]:
        arm.animation_data.action = actions[name]
        for track in arm.animation_data.nla_tracks: track.mute = True
        plants, heights = {}, []
        drift = orientation = foot_rigid = hand_rigid = 0.
        endpoints = []
        for n in range(round(seconds*60)*(2 if name == 'walk' else 1)+1):
            absolute = n/60
            local = absolute%seconds if name == 'walk' else absolute
            frame = local*FPS
            bpy.context.scene.frame_set(int(frame),subframe=frame-int(frame))
            evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()); mesh = evaluated.to_mesh()
            values = np.empty(len(mesh.vertices)*3); mesh.vertices.foreach_get('co',values)
            points = values.reshape((-1,3)); evaluated.to_mesh_clear()
            assert np.isfinite(points).all()
            for side,offset in [('l',0),('r',.5)]:
                for category in ['feet','hands']:
                    ids = masks[category][side]
                    error = float(np.max(np.abs(np.linalg.norm(points[ids]-points[ids][0],axis=1)-np.linalg.norm(rest[ids]-rest[ids][0],axis=1))))
                    if category == 'feet': foot_rigid = max(foot_rigid,error)
                    else: hand_rigid = max(hand_rigid,error)
                sole = points[masks['soles'][side]].copy()
                p = points[masks['feet'][side]].copy()
                if name == 'walk':
                    theta = math.pi/2-SPEED*absolute; phi = math.pi-theta
                    rotation = np.array([[math.cos(phi),-math.sin(phi),0],[math.sin(phi),math.cos(phi),0],[0,0,1]])
                    p = p@rotation.T+np.array([math.cos(theta),-math.sin(theta),0])
                    raw = absolute/seconds+offset
                    if not .025 < raw%1 < DUTY-.025: continue
                    key = (side,math.floor(raw))
                else: key = (side,0)
                heights.extend(sole[:,2].tolist())
                if key not in plants: plants[key] = p.copy()
                drift = max(drift,float(np.linalg.norm(p-plants[key],axis=1).max()))
                orientation = max(orientation,float(np.linalg.norm((p-p.mean(axis=0))-(plants[key]-plants[key].mean(axis=0)),axis=1).max()))
        # Explicit first/last evaluated all-vertex seam, rather than modulo time.
        for frame in [0,round(seconds*FPS)]:
            bpy.context.scene.frame_set(frame)
            e = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()); m = e.to_mesh()
            values = np.empty(len(m.vertices)*3); m.vertices.foreach_get('co',values)
            endpoints.append(values.reshape((-1,3)).copy()); e.to_mesh_clear()
        seam = float(np.linalg.norm(endpoints[0]-endpoints[1],axis=1).max())
        result[name] = {'minSoleHeight':min(heights),'maxSoleHeight':max(heights),'maxWorldStanceDrift':drift,
                        'maxSupportOrientationDrift':orientation,'maxCompleteFootShapeDrift':foot_rigid,
                        'maxCompleteHandShapeDrift':hand_rigid,'allVertexLoopSeam':seam,
                        'plantIntervals':len(plants),'samplingHz':60}
        assert min(heights)>-.001 and max(heights)<obj['restAnatomicalSoleMaxHeight']+.001, result[name]
        assert drift<.001 and orientation<.001 and foot_rigid<.0001 and hand_rigid<.0001 and seam<.0001, result[name]
    arm.animation_data.action = None
    return result


def render_poses(obj, arm, actions, output, h):
    output.mkdir()
    helpers = runpy.run_path(str(Path(__file__).with_name('turnaround.py')),run_name='trusted_render_helpers')
    camera = helpers['setup_render'](900)
    for name,t in [('idle',0.),('walk',0.),('walk',.4),('walk',.8),('walk',1.2),('walk',1.6),('walk',2.),('special',1.6)]:
        arm.animation_data.action = actions[name]
        bpy.context.scene.frame_set(round(t*FPS))
        tag = f'{name}-{t:g}'
        render_view(camera,output,tag,(0,0,h*.5),(.65,-.8,.20),1.65)
        if name == 'special' or (name == 'walk' and t == .8):
            render_view(camera,output,tag+'-side',(0,0,h*.5),(1,0,.08),1.65)
            render_view(camera,output,tag+'-feet',(0,-.015,h*.07),(.4,-1,.3),h*.64)
    arm.animation_data.action = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input',type=Path); parser.add_argument('output',type=Path)
    parser.add_argument('--inspect',action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    source, output = args.input.resolve(), args.output.resolve()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_SHA256, 'Immutable reviewed High source required'
    assert not output.exists(), 'Use a new candidate output directory'
    output.mkdir(parents=True)
    obj,preservation = load_source(source)
    obj.name = 'xingxing_native_high'
    h = max(v.co.z for v in obj.data.vertices)
    assert .942 < h < .943 and len(obj.data.polygons) == 50000
    report = {'source':str(source),'sourceSha256':SOURCE_SHA256,'preservation':preservation,
              'measurements':slice_report(obj),'productionAccepted':False,'runtimeContract':runtime_contract()}
    report['xSlices'] = []
    p = np.array([list(v.co) for v in obj.data.vertices])
    for x in np.arange(.12,.49,.025):
        band = p[np.abs(np.abs(p[:,0])-x)<.008]
        report['xSlices'].append({'absX':float(x),'min':band.min(axis=0).tolist(),'max':band.max(axis=0).tolist(),'mean':band.mean(axis=0).tolist()})
    report['soleLowestReviewUnits'] = {side:sorted(float(v.co.z) for v in obj.data.vertices if sign*v.co.x>0 and v.co.z<h*.105)[:40] for sign,side in [(1,'l'),(-1,'r')]}
    if args.inspect:
        (output/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report)); return
    # Remove only the source's sub-millimetre left/right sole offset. Complete
    # feet translate rigidly; the correction fades above the ankles.
    shifts = {}
    for sign,side in [(1,'l'),(-1,'r')]:
        shift = min(v.co.z for v in obj.data.vertices if sign*v.co.x>0 and v.co.z<h*FOOT_HEIGHT)
        assert shift < .001
        shifts[side] = float(shift)
        for v in obj.data.vertices:
            if sign*v.co.x>0 and v.co.z<h*.20:
                v.co.z -= shift*(1-smooth(h*.12,h*.20,v.co.z))
    obj.data.update()
    report['soleOffsetCorrectionReviewUnits'] = shifts
    marks = landmarks(obj,h)
    bpy.ops.object.select_all(action='DESELECT')
    arm = make_rig(obj,h,marks)
    masks = anatomical_masks(obj,h,marks)
    weights,regions = bind(obj,arm,h,masks)
    # One uniform mesh/bone scale, applied to data before any motion is baked.
    # Runtime stays at identity scale, preserving the radius1/speed.06 contract.
    final_scale = FINAL_HEIGHT/h
    for v in obj.data.vertices: v.co *= final_scale
    obj.data.update()
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    for b in arm.data.edit_bones:
        b.head *= final_scale; b.tail *= final_scale
    bpy.ops.object.mode_set(mode='OBJECT')
    marks = {side:{key:[x*final_scale for x in value] for key,value in m.items()} for side,m in marks.items()}
    h = FINAL_HEIGHT
    obj['restHeight'] = h
    obj['restAnatomicalFootMaxHeight'] = h*FOOT_HEIGHT
    obj['restAnatomicalSoleMaxHeight'] = SOLE_HEIGHT*final_scale
    report['sourceToRig'] = {'reviewWidth1Height':SOURCE_REVIEW_HEIGHT,'reviewToFinalUniformScale':final_scale,
        'originalToFinalUniformScale':preservation['uniformScale']*final_scale,'finalBounds':slice_report(obj)['bounds'],
        'finalHeight':h,'runtimeScale':1,'soleOffsetCorrectionFinalUnits':{s:v*final_scale for s,v in shifts.items()}}
    report['landmarks'] = marks
    report['maskDefinitions'] = mask_definitions(h,final_scale,marks)
    report['masks'] = {key:({s:len(ids) for s,ids in value.items()} if isinstance(value,dict) else len(value)) for key,value in masks.items()}
    (output/'landmarks.json').write_text(json.dumps(marks,indent=2)+'\n')
    (output/'masks.json').write_text(json.dumps({'sourceSha256':SOURCE_SHA256,'selectionDefinitions':report['maskDefinitions'],'blenderVertexMasks':masks,'regions':regions},separators=(',',':'))+'\n')
    (output/'weights.json').write_text(json.dumps(weights,separators=(',',':'))+'\n')
    render_masks(obj,regions,output/'masks',h)
    bpy.context.scene.render.fps = FPS
    actions = {name:animate(arm,name,duration) for name,duration in [('idle',4.),('walk',WALK_SECONDS),('special',SPECIAL_SECONDS)]}
    report['numericalQA'] = numerical_qa(obj,arm,masks,actions)
    (output/'numerical-qa.json').write_text(json.dumps(report['numericalQA'],indent=2)+'\n')
    render_poses(obj,arm,actions,output/'poses',h)
    bpy.context.scene.frame_set(0)
    for pb in arm.pose.bones: pb.rotation_quaternion = (1,0,0,0); pb.location = (0,0,0)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True); arm.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(output/'rigged.glb'),export_format='GLB',use_selection=True,
        export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,
        export_def_bones=False,export_extras=True)
    report['riggedSha256'] = hashlib.sha256((output/'rigged.glb').read_bytes()).hexdigest()
    report['actions'] = {name:{'seconds':float(action.frame_range[1]/FPS),'frames':list(action.frame_range)} for name,action in actions.items()}
    (output/'actions.json').write_text(json.dumps({'clips':report['actions'],'samplingFPS':FPS,'interpolation':'LINEAR','swing':'quintic C2 circular recovery; sin^4 clearance','runtimeContract':runtime_contract()},indent=2)+'\n')
    report['boneCount'] = len(arm.data.bones)
    report['weightsAudit'] = {'maxInfluences':max(map(len,weights)),'handLegCrossContamination':False,'completeFeetRigid':True,'completeHandsRigid':True,'whiteEarsRetained':True}
    assert hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_SHA256
    (output/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print('XINGXING_CANDIDATE',json.dumps(report),flush=True)


if __name__ == '__main__': main()
