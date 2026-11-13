"""Candidate-only native Zhuyan inspection and rigging; never publishes assets.

Blender --background --factory-startup --disable-autoexec --python-exit-code 1
  --python pipeline/blender/rig_zhuyan_native.py -- input.glb NEW_OUTPUT_DIR --inspect
Omit --inspect to write a rig with idle/walk/special and measured support evidence.
All source geometry/digits are preserved. High anatomy must be reviewed separately;
this script refuses an already populated output directory and records source hashes.
"""
import argparse
import hashlib
import json
import math
import runpy
import sys
from pathlib import Path

sys.dont_write_bytecode = True
# Only trusted repository helpers; never load modules beside downloaded assets.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Matrix, Vector
import rig_quadruped as base
from rig_yingzhao import contact

FPS = 30
SECONDS = 2.4
RADIUS = 1.
SPEED = .08
DUTY = .66


def smooth(a, b, x):
    t = max(0., min(1., (x-a)/(b-a)))
    return t*t*(3-2*t)


def load_source(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path), disable_bone_shape=True)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    assert len(meshes) == 1, ('Expected exactly one actual source mesh', len(meshes))
    obj = meshes[0]
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
    # Remove source skinning but keep its actual rest geometry, including the
    # importer's inverse-bind/dequantization transforms, before uniform scaling.
    for modifier in list(obj.modifiers):
        if modifier.type == 'ARMATURE':
            obj.modifiers.remove(modifier)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for node in list(bpy.context.scene.objects):
        if node is not obj:
            bpy.data.objects.remove(node, do_unlink=True)
    obj.vertex_groups.clear()
    points = np.array([list(v.co) for v in obj.data.vertices])
    lo, hi = points.min(axis=0), points.max(axis=0)
    scale = 1/max((hi-lo)[:2])
    origin = np.array([(lo[0]+hi[0])/2, (lo[1]+hi[1])/2, lo[2]])
    for vertex in obj.data.vertices:
        vertex.co = Vector((points[vertex.index]-origin)*scale)
    obj.data.update()
    obj.name = 'zhuyan_primate'
    return obj, {'uniformScale': float(scale), 'sourceOrigin': origin.tolist(),
                 'vertices': len(obj.data.vertices), 'faces': len(obj.data.polygons),
                 'geometryCleanup': False, 'digitsAddedOrReplaced': False}


def render_view(camera, output, name, target, direction, size):
    shot = camera.copy()
    shot.data = camera.data.copy()
    bpy.context.scene.collection.objects.link(shot)
    target = Vector(target)
    location = target+Vector(direction).normalized()*4
    shot.matrix_world = Matrix.LocRotScale(location, (target-location).to_track_quat('-Z', 'Y'), Vector((1, 1, 1)))
    shot.data.ortho_scale = size
    # Close anatomical crops clip only geometry in front of the crop plane;
    # this makes the real feet visible from above through the overhanging torso.
    if name.endswith('foot-top'):
        shot.data.clip_start = 3.77
    scene = bpy.context.scene
    scene.camera = shot
    scene.render.filepath = str(output/(name+'.png'))
    bpy.context.view_layer.update()
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(shot, do_unlink=True)


def render_anatomy(obj, folder, prefix='source'):
    folder.mkdir()
    helpers = runpy.run_path(str(Path(__file__).with_name('turnaround.py')), run_name='trusted_render_helpers')
    cam = helpers['setup_render'](900)
    points = np.array([list(v.co) for v in obj.data.vertices])
    h = float(points[:, 2].max())
    center = (points.min(axis=0)+points.max(axis=0))/2
    for name, direction in [('front',(0,-1,0)),('side',(1,0,0)),('back',(0,1,0)),('34',(.65,-.8,.22))]:
        render_view(cam, folder, prefix+'-'+name, center, direction, h*1.12)
    # These are anatomical camera crops, not tests for a numeric digit count.
    for name, direction in [('head-front',(0,-1,0)),('head-side',(1,0,0)),('head-back',(0,1,0))]:
        render_view(cam, folder, name, (0,-.04,h*.855), direction, h*.37)
    for sign, side in [(1,'left'),(-1,'right')]:
        ps = points[(points[:,2] < h*.37) & (points[:,2] > h*.16) & (sign*points[:,0] > .31)]
        if len(ps):
            target = (ps.min(axis=0)+ps.max(axis=0))/2
            for name, direction in [('front',(0,-1,0)),('back',(0,1,0)),('thumb',(-sign,-.7,-.1)),('outer',(sign,-.25,-.1)),('under',(0,-.7,-.7))]:
                render_view(cam, folder, side+'-hand-'+name, target, direction, h*.29)
        ps = points[(points[:,2] < h*.095) & (sign*points[:,0] > 0)]
        assert len(ps), 'Foot camera crop empty'
        target = (ps.min(axis=0)+ps.max(axis=0))/2
        for name, direction in [('front',(0,-1,.1)),('top',(0,-.1,1)),('sole',(0,-.1,-1))]:
            render_view(cam, folder, side+'-foot-'+name, target, direction, h*.27)
    render_view(cam, folder, 'feet-ground-side', (0,-.04,h*.055), (1,-.15,.05), h*.40)
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.glob('*.png')}


def slice_report(obj):
    p = np.array([list(v.co) for v in obj.data.vertices])
    h = float(p[:,2].max())
    slices = []
    for z in np.arange(.025, 1, .05):
        band = p[np.abs(p[:,2]/h-z) < .015]
        if len(band):
            slices.append({'heightRatio': float(z), 'count': len(band), 'min': band.min(axis=0).tolist(), 'max': band.max(axis=0).tolist()})
    return {'height':h,'bounds':[p.min(axis=0).tolist(),p.max(axis=0).tolist()],'slices':slices}


def anatomical_region(p, h):
    """Zhuyan-specific spatial gates, before consulting any skin weights.

    Unlike Changyou, this ape has a broad forward chin, much lower wrists,
    broad red feet, and no tail. Masks are rendered for every candidate.
    """
    z, x = p.z/h, abs(p.x)
    floor = .835-.125*(1-smooth(-.08, .16, p.y))
    width = .215+.040*smooth(.80, .86, z)
    if (z > floor and x < width) or z > .89:
        return 'head'
    return 'body'


def connected_lower_body(obj, h):
    """Flood real legs from the soles below the groin gate.

    The hanging thumbs overlap the thigh's X/Z range but are disconnected from
    it below this gate. Welding is virtual adjacency only: no geometry changes.
    """
    graph = [set() for _ in obj.data.vertices]
    for edge in obj.data.edges:
        a,b = edge.vertices
        graph[a].add(b)
        graph[b].add(a)
    coincident = {}
    for vertex in obj.data.vertices:
        key = tuple(round(float(v),5) for v in vertex.co)
        if key in coincident:
            other = coincident[key]
            graph[vertex.index].add(other)
            graph[other].add(vertex.index)
        else:
            coincident[key] = vertex.index
    def flood(seeds, allowed):
        reached = set(seeds)
        pending = list(reached)
        while pending:
            for other in graph[pending.pop()]:
                if other not in reached and allowed(obj.data.vertices[other].co):
                    reached.add(other)
                    pending.append(other)
        return reached
    lower = flood([v.index for v in obj.data.vertices if v.co.z < h*.15],lambda p:p.z < h*.435)
    hands = {}
    for sign,side in [(1,'l'),(-1,'r')]:
        hands[side] = flood([v.index for v in obj.data.vertices if sign*v.co.x > .39 and h*.22 < v.co.z < h*.32],lambda p:h*.17 < p.z < h*.385)
        assert len(hands[side]) > 300 and not (hands[side] & lower), 'Hand flood touched a leg'
    assert len(lower) > 3000
    return lower, hands


def foot_alignment(obj, h):
    shifts = {}
    for sign, side in [(1,'l'),(-1,'r')]:
        foot = [v for v in obj.data.vertices if v.co.z < h*.085 and sign*v.co.x > 0]
        assert foot
        shift = min(v.co.z for v in foot)
        assert shift < .012, ('Unexpected sole mismatch: review anatomy', side, shift)
        shifts[side] = shift
        for v in obj.data.vertices:
            if sign*v.co.x > 0 and v.co.z < h*.20:
                v.co.z -= shift*(1-smooth(h*.10, h*.20, v.co.z))
    obj.data.update()
    return shifts


def make_rig(obj, h):
    arm = bpy.data.objects.new('zhuyan_rig', bpy.data.armatures.new('zhuyan_native_anatomy'))
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(name, a, b, parent=None):
        item = arm.data.edit_bones.new(name)
        item.head, item.tail = a, b
        if parent:
            item.parent = arm.data.edit_bones[parent]
    bone('root', (0,0,0), (0,0,h*.1))
    bone('hips', (0,.13,h*.43), (0,.11,h*.56), 'root')
    bone('chest', (0,.11,h*.56), (0,.06,h*.73), 'hips')
    bone('neck', (0,.06,h*.73), (0,.015,h*.82), 'chest')
    bone('head', (0,.015,h*.82), (0,-.075,h*.95), 'neck')
    landmarks = {}
    def center(z, sign, minx, maxx, default, front=None):
        points = [v.co for v in obj.data.vertices if abs(v.co.z-z) < h*.018
                  and minx < sign*v.co.x < maxx and (front is None or v.co.y < front)]
        return sum(points, Vector())/len(points) if points else Vector(default)
    for sign, side in [(1,'l'),(-1,'r')]:
        hip = Vector((sign*.15,.13,h*.43))
        knee = center(h*.255,sign,.12,.32,(sign*.23,.035,h*.255))
        ankle = center(h*.105,sign,.13,.32,(sign*.24,.14,h*.105))
        ankle.z = h*.085
        shoulder = Vector((sign*.265,.055,h*.765))
        elbow = center(h*.575,sign,.29,.47,(sign*.365,.03,h*.575))
        wrist = center(h*.355,sign,.35,.50,(sign*.445,-.10,h*.355),front=.07)
        hand = Vector((wrist.x,wrist.y-.045,h*.245))
        bone(f'leg_{side}_upper', hip,knee,'hips')
        bone(f'leg_{side}_lower', knee,ankle,f'leg_{side}_upper')
        bone(f'leg_{side}_foot', ankle,ankle+Vector((0,-h*.10,-h*.035)),f'leg_{side}_lower')
        bone(f'arm_{side}_upper', shoulder,elbow,'chest')
        bone(f'arm_{side}_lower', elbow,wrist,f'arm_{side}_upper')
        bone(f'arm_{side}_hand', wrist,hand,f'arm_{side}_lower')
        landmarks[side] = {k:list(v) for k,v in [('hip',hip),('knee',knee),('ankle',ankle),('shoulder',shoulder),('elbow',elbow),('wrist',wrist)]}
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm, landmarks


def segment_distance(p, bone):
    a, b = bone.head_local, bone.tail_local
    d = b-a
    return (p-a-d*max(0.,min(1.,(p-a).dot(d)/d.length_squared))).length


def bind(obj, arm, h):
    groups = {b.name:obj.vertex_groups.new(name=b.name) for b in arm.data.bones}
    weights, regions = [], []
    masks = {'feet':{'l':[],'r':[]},'soles':{'l':[],'r':[]},'head':[],'chest':[],'hands':{'l':[],'r':[]}}
    def inverse(p, names):
        w = {n:1/max(h*.012,segment_distance(p,arm.data.bones[n]))**4 for n in names}
        total = sum(w.values())
        return {n:value/total for n,value in w.items()}
    lower_body, connected_hands = connected_lower_body(obj,h)
    for v in obj.data.vertices:
        p, z, x = v.co, v.co.z/h, abs(v.co.x)
        side = 'l' if p.x > 0 else 'r'
        region = ('hand_'+side if v.index in connected_hands[side] else
                  'leg_'+side if v.index in lower_body else anatomical_region(p,h))
        regions.append(region)
        # Select complete rest foot anatomy spatially before inspecting weights.
        if z < .085:
            masks['feet'][side].append(v.index)
            if p.z < .003:
                masks['soles'][side].append(v.index)
            w = {f'leg_{side}_foot':1.}
        elif region.startswith('hand_'):
            masks['hands'][side].append(v.index)
            w = {f'arm_{side}_hand':1.}
        elif region == 'head':
            masks['head'].append(v.index)
            w = {'head':1.}
        elif region.startswith('leg_'):
            w = inverse(p,[f'leg_{side}_{part}' for part in ['upper','lower','foot']])
            rigid = 1-smooth(.085,.16,z)
            w = {n:value*(1-rigid) for n,value in w.items()}
            w[f'leg_{side}_foot'] += rigid
            pelvis = smooth(.365,.435,z)*.8
            w = {n:value*(1-pelvis) for n,value in w.items()}
            if pelvis:
                w['hips'] = pelvis
        else:
            torso = inverse(p,['hips','chest','neck'])
            threshold = .315-.055*smooth(.45,.79,z)
            blend = smooth(threshold-.016,threshold+.03,x)
            # Broad native chest is protected even near the hanging upper arms.
            if x < .245 and z > .43:
                blend = 0.
                masks['chest'].append(v.index)
            if z > .82:
                blend *= 1-smooth(.82,.87,z)
            if blend:
                limb = inverse(p,[f'arm_{side}_{part}' for part in ['upper','lower','hand']])
                rigid = 1-smooth(.385,.445,z)
                limb = {n:value*(1-rigid) for n,value in limb.items()}
                limb[f'arm_{side}_hand'] += rigid
                w = {n:value*(1-blend) for n,value in torso.items()}
                for n,value in limb.items():
                    w[n] = w.get(n,0.)+value*blend
                if z < .35 and blend > .99999:
                    masks['hands'][side].append(v.index)
            else:
                w = torso
        selected = sorted(((n,value) for n,value in w.items() if value > 1e-8),key=lambda item:item[1],reverse=True)[:4]
        total = sum(value for n,value in selected)
        w = {n:value/total for n,value in selected}
        weights.append(w)
        for name,value in w.items():
            groups[name].add([v.index],value,'REPLACE')
    modifier = obj.modifiers.new('Native ape protected anatomy','ARMATURE')
    modifier.object = arm
    obj.parent = arm
    assert all(not any(n.startswith('arm_') for n in weights[i]) for i in masks['chest'])
    assert all(weights[i] == {'head':1.} for i in masks['head'])
    for side in ['l','r']:
        assert len(masks['soles'][side]) > 10, ('Complete sole patch required', side)
        assert all(weights[i] == {f'leg_{side}_foot':1.} for i in masks['feet'][side])
        assert len(masks['hands'][side]) > 30
    obj['restAnatomicalFootMaxHeight'] = h*.085
    obj['restAnatomicalSoleMaxHeight'] = .003
    obj['nativeAnatomyCandidateOnly'] = True
    obj['reviewedSourceSha256'] = obj.get('reviewedSourceSha256','')
    return weights, regions, masks


def animate(arm, name, seconds):
    action = base.new_action(arm,name)
    count = round(seconds*FPS)
    for f in range(count+1):
        t, phase = f/FPS, f/count
        display = smooth(.25,1.1,t)*(1-smooth(2.7,3.8,t)) if name == 'special' else 0.
        delta = Vector((0,0,-.008 if name == 'walk' else 0))
        pose = {'head':base.world_rot(arm.pose.bones['head'],base.X,-.04*display+.006*math.sin(phase*math.tau)),
                'chest':base.world_rot(arm.pose.bones['chest'],base.X,.003*math.sin(phase*math.tau))}
        for sign,side in [(1,'l'),(-1,'r')]:
            swing = sign*.08*math.sin(phase*math.tau) if name == 'walk' else .008*math.sin(phase*math.tau)
            upper = arm.pose.bones[f'arm_{side}_upper']
            lower = arm.pose.bones[f'arm_{side}_lower']
            pose[upper.name] = base.world_rot(upper,base.X,swing-.29*display)@base.world_rot(upper,base.Y,-sign*.065*display)
            pose[lower.name] = base.world_rot(lower,base.X,-.10*display)
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
                    relative = seconds*DUTY*(.5-u*u*(3-2*u))
                    lift = .042*math.sin(math.pi*u)
                yaw = -SPEED/RADIUS*relative
                ankle = arm.data.bones[f'leg_{side}_foot'].head_local
                x, y = ankle.x-RADIUS, ankle.y
                lateral = RADIUS+math.cos(yaw)*x-math.sin(yaw)*y-ankle.x
                backward = math.sin(yaw)*x+math.cos(yaw)*y-ankle.y
            contact(arm,f'leg_{side}',f,delta,lateral,backward,lift,yaw)
    base.finish_action(arm,action)
    for curve in base.action_fcurves(action):
        for key in curve.keyframe_points:
            key.interpolation = 'LINEAR'
    return action


def deformed_contact_qa(obj, arm, masks, actions):
    """Measure evaluated actual mesh, selected by rest anatomy, never skin tags."""
    report = {}
    for name,seconds in [('idle',4.),('walk',SECONDS),('special',4.)]:
        for track in arm.animation_data.nla_tracks:
            track.mute = True
        arm.animation_data.action = actions[name]
        plants, minima, maxima = {}, [], []
        max_drift = shape_drift = foot_shape_drift = hand_shape_drift = 0.
        samples = round(seconds*FPS*2)*(2 if name == 'walk' else 1)
        rest = np.array([list(v.co) for v in obj.data.vertices])
        for step in range(samples+1):
            absolute = step/(FPS*2)
            local = absolute%seconds if name == 'walk' else absolute
            frame = local*FPS
            bpy.context.scene.frame_set(int(frame),subframe=frame-int(frame))
            bpy.context.view_layer.update()
            evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            mesh = evaluated.to_mesh()
            values = np.empty(len(mesh.vertices)*3,dtype=np.float64)
            mesh.vertices.foreach_get('co',values)
            points = values.reshape((-1,3))
            assert np.isfinite(points).all()
            evaluated.to_mesh_clear()
            for side,offset in [('l',0),('r',.5)]:
                ids = masks['soles'][side]
                p = points[ids].copy()
                # All anatomical foot vertices must preserve their relative
                # shape, including toes that a wrong skin mask would omit.
                whole = points[masks['feet'][side]]
                rr = rest[masks['feet'][side]]
                foot_shape_drift = max(foot_shape_drift,float(np.max(np.abs(np.linalg.norm(whole-whole[0],axis=1)-np.linalg.norm(rr-rr[0],axis=1)))))
                hand = points[masks['hands'][side]]
                rh = rest[masks['hands'][side]]
                hand_shape_drift = max(hand_shape_drift,float(np.max(np.abs(np.linalg.norm(hand-hand[0],axis=1)-np.linalg.norm(rh-rh[0],axis=1)))))
                if name == 'walk':
                    theta = math.pi/2-SPEED/RADIUS*absolute
                    phi = math.pi-theta
                    rotation = np.array([[math.cos(phi),-math.sin(phi),0],[math.sin(phi),math.cos(phi),0],[0,0,1]])
                    p = p@rotation.T+np.array([RADIUS*math.cos(theta),-RADIUS*math.sin(theta),0])
                    raw = absolute/seconds+offset
                    if not .025 < raw%1 < DUTY-.025:
                        continue
                    key = (side,math.floor(raw))
                else:
                    key = (side,0)
                minima.append(float(p[:,2].min()))
                maxima.append(float(p[:,2].max()))
                if key not in plants:
                    plants[key] = p.copy()
                max_drift = max(max_drift,float(np.linalg.norm(p-plants[key],axis=1).max()))
                shape_drift = max(shape_drift,float(np.linalg.norm((p-p.mean(axis=0))-(plants[key]-plants[key].mean(axis=0)),axis=1).max()))
        report[name] = {'samples':samples+1,'minHeight':min(minima),'maxHeight':max(maxima),
                        'maxWorldStanceDrift':max_drift,'maxSupportOrientationDrift':shape_drift,
                        'maxAllFootShapeDrift':foot_shape_drift,'maxAllHandShapeDrift':hand_shape_drift,'plantIntervals':len(plants),
                        'selection':'rest spatial anatomy independent of weights; actual evaluated mesh vertices',
                        'soleVertices':{k:len(v) for k,v in masks['soles'].items()},
                        'allFootVertices':{k:len(v) for k,v in masks['feet'].items()}}
        assert min(minima) > -.001 and max(maxima) < .004, report[name]
        assert max_drift < .001 and shape_drift < .001 and foot_shape_drift < .0001 and hand_shape_drift < .0001, report[name]
    arm.animation_data.action = None
    return report


def render_masks(obj, regions, masks, output, h):
    output.mkdir()
    helpers = runpy.run_path(str(Path(__file__).with_name('turnaround.py')),run_name='trusted_render_helpers')
    camera = helpers['setup_render'](900)
    original = list(obj.data.materials)
    original_indices = [p.material_index for p in obj.data.polygons]
    obj.data.materials.clear()
    colors = {'head':(.15,.75,.2,1),'body':(.10,.18,.45,1),'leg_l':(.9,.3,.04,1),'leg_r':(.8,.15,.05,1),'hand_l':(.55,.1,.65,1),'hand_r':(.55,.1,.65,1)}
    for name,color in colors.items():
        material = bpy.data.materials.new('review_'+name)
        material.use_nodes = True
        shader = material.node_tree.nodes.get('Principled BSDF')
        shader.inputs['Base Color'].default_value = color
        shader.inputs['Emission Color'].default_value = color
        shader.inputs['Emission Strength'].default_value = .6
        obj.data.materials.append(material)
    for polygon in obj.data.polygons:
        names = [regions[i] for i in polygon.vertices]
        polygon.material_index = list(colors).index(max(names,key=names.count))
    for name,direction in [('front',(0,-1,0)),('side',(1,0,0))]:
        render_view(camera,output,'regions-'+name,(0,0,h*.52),direction,h*1.12)
        render_view(camera,output,'head-mask-'+name,(0,0,h*.82),direction,h*.50)
    obj.data.materials.clear()
    for material in original:
        obj.data.materials.append(material)
    for polygon,index in zip(obj.data.polygons,original_indices):
        polygon.material_index = index


def render_poses(obj, arm, actions, output, h):
    output.mkdir()
    helpers = runpy.run_path(str(Path(__file__).with_name('turnaround.py')),run_name='trusted_render_helpers')
    camera = helpers['setup_render'](1000)
    for name,time in [('idle',0.),('walk',0.),('walk',.6),('walk',1.2),('walk',1.8),('special',1.6)]:
        arm.animation_data.action = actions[name]
        bpy.context.scene.frame_set(round(time*FPS))
        bpy.context.view_layer.update()
        tag = f'{name}-{time:g}'
        render_view(camera,output,tag+'-34',(0,0,h*.50),(.65,-.8,.22),h*1.13)
        if name == 'special' or (name == 'walk' and time == .6):
            render_view(camera,output,tag+'-joints',(0,0,h*.70),(.7,-1,.1),h*.68)
            render_view(camera,output,tag+'-feet',(0,0,h*.09),(.5,-1,.35),h*.55)
            render_view(camera,output,tag+'-chin',(0,-.05,h*.80),(1,-.3,.0),h*.45)
    arm.animation_data.action = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--inspect', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    source = args.input.resolve()
    output = args.output.resolve()
    assert source.is_file()
    assert not output.exists(), 'Use a unique new candidate directory'
    output.mkdir(parents=True)
    obj, preservation = load_source(source)
    report = {'source':str(source),'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'preservation':preservation,'measurements':slice_report(obj),
              'productionAccepted':False,'anatomicalDigitCount':'requires actual image review, not inferred from bones'}
    if args.inspect:
        report['images'] = render_anatomy(obj, output/'anatomy')
    else:
        h = report['measurements']['height']
        report['soleOffsetCorrection'] = foot_alignment(obj,h)
        bpy.ops.object.select_all(action='DESELECT')
        arm, report['landmarks'] = make_rig(obj,h)
        obj['reviewedSourceSha256'] = report['sourceSha256']
        weights, regions, masks = bind(obj,arm,h)
        report['spatialMasks'] = {name:({k:len(v) for k,v in value.items()} if isinstance(value,dict) else len(value)) for name,value in masks.items()}
        report['weights'] = {'unweighted':0,'maxInfluences':max(map(len,weights)),'chestHasArmInfluence':False,'maskedHeadRigid':True,'maskedFeetRigid':True}
        render_masks(obj,regions,masks,output/'masks',h)
        bpy.context.scene.render.fps = FPS
        actions = {name:animate(arm,name,seconds) for name,seconds in [('idle',4.),('walk',SECONDS),('special',4.)]}
        report['actualDeformedSoleQA'] = deformed_contact_qa(obj,arm,masks,actions)
        render_poses(obj,arm,actions,output/'poses',h)
        bpy.context.scene.frame_set(0)
        for pb in arm.pose.bones:
            pb.rotation_quaternion = (1,0,0,0)
            pb.location = (0,0,0)
        bpy.context.view_layer.update()
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        arm.select_set(True)
        bpy.ops.export_scene.gltf(filepath=str(output/'rigged.glb'),export_format='GLB',use_selection=True,
            export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,
            export_def_bones=False,export_extras=True)
        report['runtimeParameters'] = {'radius':RADIUS,'speed':SPEED,'walkSeconds':SECONDS,'duty':DUTY}
        report['bones'] = len(arm.data.bones)
        report['clips'] = list(actions)
        report['outputSha256'] = hashlib.sha256((output/'rigged.glb').read_bytes()).hexdigest()
        report['images'] = {str(p.relative_to(output)):hashlib.sha256(p.read_bytes()).hexdigest() for p in output.rglob('*.png')}
    (output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    print('ZHUYAN_CANDIDATE', json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
