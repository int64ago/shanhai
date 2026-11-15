"""Native Lu: reviewed repair4 only; no remesh/UV edits, exact circular hoof IK.
Blender --background --factory-startup --disable-autoexec --python-exit-code 1
  --python pipeline/blender/rig_lu_fish_native.py -- SOURCE.glb NEW_OUTPUT
"""
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import json
import math
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

TRUSTED = Path(__file__).resolve().parent
sys.path.insert(0, str(TRUSTED))
from rig_quadruped import landmarks, build_armature, new_action, action_fcurves, world_rot
from rig_jingwei import set_segment

SOURCE_SHA = '367b05b52fb5e3c2f8ffc2e1b556b6f9c2be567bec439b9e214b07108881c9a7'
HEIGHT = 1.35
FPS = 60
RADIUS, SPEED, WALK, DUTY = 1.05, .16, 1.6, .68
PHASE = {'back_l': 0., 'front_l': .25, 'back_r': .5, 'front_r': .75}
DURATIONS = {'idle': 4., 'walk': WALK, 'special': 4.}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def smooth(a, b, value):
    t = max(0., min(1., (value-a)/(b-a)))
    return t*t*(3-2*t)


def load(source):
    assert sha(source) == SOURCE_SHA, 'Only frozen, reviewed repair4 may be rigged'
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    assert len(meshes) == 1
    obj = meshes[0]
    mw = obj.matrix_world.copy()
    positions = np.array([list(mw@v.co) for v in obj.data.vertices])
    scale = HEIGHT/positions[:,2].max()
    normal_matrix = mw.to_3x3().inverted().transposed()
    normals = [(normal_matrix@n.vector).normalized() for n in obj.data.corner_normals]
    for v, p in zip(obj.data.vertices, positions):
        v.co = p*scale
    obj.matrix_world = Matrix.Identity(4)
    for face in obj.data.polygons:
        face.use_smooth = True
    obj.data.normals_split_custom_set(normals)
    obj.data.update()
    for other in list(bpy.context.scene.objects):
        if other != obj:
            bpy.data.objects.remove(other, do_unlink=True)
    assert len(obj.data.polygons) == 50000
    return obj, np.array([list(v.co) for v in obj.data.vertices]), scale


def native_fingerprint(obj):
    digest = hashlib.sha256()
    for values,dtype in [([list(v.co) for v in obj.data.vertices],'<f4'),
        ([list(p.vertices) for p in obj.data.polygons],'<u4'),
        ([p.material_index for p in obj.data.polygons],'<u4'),
        ([list(n.vector) for n in obj.data.corner_normals],'<f4')]:
        digest.update(np.asarray(values,dtype=dtype).tobytes())
    for layer in obj.data.uv_layers:
        digest.update(np.asarray([list(v.uv) for v in layer.data],dtype='<f4').tobytes())
    for material in obj.data.materials:
        digest.update(material.name.encode())
        for node in material.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image and node.image.packed_file:
                digest.update(node.image.packed_file.data)
    return digest.hexdigest()


def make_rig(obj, points, scale):
    lm = landmarks(obj)
    lm['rear'] = Vector((0., .25*scale, .408*scale))
    # Long native tail must never set hips or torso landmarks.
    arm = build_armature(lm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.data.edit_bones
    # Preserve native rest mesh while giving straight generated limbs sufficient
    # analytic reach for the short curved stride; no stretch or bone scaling.
    for leg in PHASE:
        knee = eb[leg+'_lower'].head.copy()
        knee.y += (.035 if leg.startswith('front') else -.035)*scale
        eb[leg+'_upper'].tail = knee
        eb[leg+'_lower'].head = knee
    def bone(name, a, b, parent):
        result = eb.new(name)
        result.head, result.tail = Vector(a)*scale, Vector(b)*scale
        result.parent = eb[parent]
        result.use_connect = False
        return result
    for side, sign in [('l',1),('r',-1)]:
        joints = [(sign*.105,-.155,.435),(sign*.205,-.135,.473),
                  (sign*.29,-.12,.355),(sign*.38,-.105,.21)]
        for i in range(3):
            bone(f'wing_{side}_{i}', joints[i], joints[i+1], 'spine2' if i == 0 else f'wing_{side}_{i-1}')
    ys = np.linspace(.253, .5, 10)
    centers = []
    normalized = points/scale
    for y in ys:
        region = normalized[(np.abs(normalized[:,1]-y)<.013)&(np.abs(normalized[:,0])<.045)&(normalized[:,2]>.34)]
        if not len(region):
            region = normalized[np.argsort(np.abs(normalized[:,1]-y))[:30]]
        centers.append((float(np.mean(region[:,0])),float(y),float(np.mean(region[:,2]))))
    for i in range(len(centers)-1):
        bone(f'tail_{i}', centers[i], centers[i+1], 'hips' if i == 0 else f'tail_{i-1}')
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm, lm, centers


def bind(obj, arm, p, scale):
    q = p/scale
    groups = {b.name: obj.vertex_groups.new(name=b.name) for b in arm.data.bones if b.use_deform}
    masks = {name: [] for name in ['head','wing_l','wing_r','tail',*['hoof_'+k for k in PHASE]]}
    all_weights = []
    for i, (x,y,z) in enumerate(q):
        side = 'l' if x>0 else 'r'
        fb = 'front' if y<-.025 else 'back'
        leg = f'{fb}_{side}'
        # Geometric masks are defined from frozen source coordinates, not weights.
        hoof = z<.045 and abs(x)>.035
        wing = smooth(.115,.165,abs(x))*(1-smooth(.035,.08,y))*smooth(.16,.21,z)
        tail = smooth(.246,.274,y)*smooth(.27,.30,z)
        head = 1-smooth(-.305,-.255,y)
        limb = (1-smooth(.22,.35,z))*smooth(.025,.055,abs(x))*(1-wing)*(1-tail)
        if hoof:
            w = {leg+'_foot':1.}
            masks['hoof_'+leg].append(i)
        elif wing>0:
            u = max(0.,min(2.,(abs(x)-.16)/.105))
            a = min(1,int(u)); f = u-a
            w = {f'wing_{side}_{a}':wing*(1-f), f'wing_{side}_{a+1}':wing*f, 'spine2':1-wing}
            if wing>.99:
                masks['wing_'+side].append(i)
        elif tail>0:
            u = max(0.,min(8.,(y-.253)/(.247/9)))
            a = min(7,int(u)); f = u-a
            w = {f'tail_{a}':tail*(1-f),f'tail_{a+1}':tail*f,'hips':1-tail}
            if tail>.99:
                masks['tail'].append(i)
        elif head>0:
            w = {'head':head,'neck':1-head}
            if head>.999:
                masks['head'].append(i)
        elif limb>0:
            # Source-specific vertical joint blending, with rigid whole hoof capsule.
            ankle = smooth(.045,.10,z)
            knee = smooth(.16,.245,z)
            leg_weights = {leg+'_foot':1-ankle,leg+'_lower':ankle*(1-knee),leg+'_upper':ankle*knee}
            torso = 'spine2' if fb=='front' else 'hips'
            w = {name:value*limb for name,value in leg_weights.items()}
            w[torso] = 1-limb
        else:
            a = smooth(-.23,-.12,y)
            b = smooth(-.03,.13,y)
            w = {'neck':1-a,'spine2':a*(1-b),'hips':a*b}
        w = {k:float(v) for k,v in w.items() if v>1e-8}
        total = sum(w.values())
        w = {k:v/total for k,v in w.items()}
        assert len(w)<=4 and abs(sum(w.values())-1)<1e-8
        for name,value in w.items():
            groups[name].add([i],value,'REPLACE')
        all_weights.append(w)
    modifier = obj.modifiers.new('NativeLuSkin','ARMATURE')
    modifier.object = arm
    obj.parent = arm
    assert all(masks.values()), {k:len(v) for k,v in masks.items()}
    return masks, all_weights


def rz(angle):
    return Matrix.Rotation(angle,4,'Z')


def stance(rest, tau):
    omega = SPEED/RADIUS
    center = Vector((RADIUS*math.sin(omega*tau),-RADIUS*math.cos(omega*tau),0))
    plant = Vector((0,-RADIUS,0))+rz(math.pi/2)@rest
    return rz(-math.pi/2-omega*tau)@(plant-center)


def foot_target(rest, phase):
    if phase<DUTY:
        tau = (phase-DUTY/2)*WALK
        return stance(rest,tau), -SPEED/RADIUS*tau, 0.
    q = (phase-DUTY)/(1-DUTY)
    span = (1-DUTY)*WALK
    a,b = stance(rest,DUTY/2*WALK),stance(rest,-DUTY/2*WALK)
    eps = 1e-4
    va = (stance(rest,DUTY/2*WALK+eps)-stance(rest,DUTY/2*WALK-eps))/(2*eps)
    vb = (stance(rest,-DUTY/2*WALK+eps)-stance(rest,-DUTY/2*WALK-eps))/(2*eps)
    aa = (stance(rest,DUTY/2*WALK+eps)-a*2+stance(rest,DUTY/2*WALK-eps))/(eps*eps)
    ab = (stance(rest,-DUTY/2*WALK+eps)-b*2+stance(rest,-DUTY/2*WALK-eps))/(eps*eps)
    c0,c1,c2 = a,va*span,aa*span*span/2
    d = b-c0-c1-c2
    v = vb*span-c1-c2*2
    acc = ab*span*span-c2*2
    c3,c4,c5 = d*10-v*4+acc*.5, d*(-15)+v*7-acc, d*6-v*3+acc*.5
    target = c0+c1*q+c2*q*q+c3*q**3+c4*q**4+c5*q**5
    lift = math.sin(math.pi*q)**4
    target.z += .065*lift
    # Match stance orientation and angular velocity at both swing endpoints.
    blend = q*q*q*(10-15*q+6*q*q)
    yaw = -SPEED/RADIUS*(DUTY/2*WALK+q*span-WALK*blend)
    return target,yaw,lift


def contact(arm, leg, target, yaw=0.):
    upper,lower,foot = [arm.pose.bones[leg+'_'+name] for name in ('upper','lower','foot')]
    rest = upper.bone
    parent = upper.parent
    hip = parent.matrix @ parent.bone.matrix_local.inverted() @ rest.head_local
    direction = target-hip
    distance = direction.length
    l1,l2 = upper.bone.length,lower.bone.length
    assert distance < l1+l2-1e-5, ('Unreachable hoof',leg,distance,l1+l2)
    axis = direction.normalized()
    bend = lower.bone.head_local-(rest.head_local+foot.bone.head_local)/2
    bend -= axis*bend.dot(axis)
    if bend.length < 1e-4:
        bend = Vector((0,1 if leg.startswith('front') else -1,0))
        bend -= axis*bend.dot(axis)
    bend.normalize()
    along = (l1*l1-l2*l2+distance*distance)/(2*distance)
    knee = hip+axis*along+bend*math.sqrt(max(0,l1*l1-along*along))
    set_segment(upper,hip,knee)
    set_segment(lower,knee,target)
    foot.matrix = Matrix.Translation(target)@rz(yaw)@Matrix.Translation(-foot.bone.head_local)@foot.bone.matrix_local
    bpy.context.view_layer.update()


def animate(arm, name, duration, sole_offsets):
    action = new_action(arm,name)
    for frame in range(round(duration*FPS)+1):
        t = frame/FPS
        cycle = 2*math.pi*t/duration
        for pb in arm.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        burst = math.sin(math.pi*t/duration)**4 if name=='special' else 0.
        for bone,axis,angle in [('spine1',(1,0,0),.006*math.sin(cycle*2)),
            ('neck',(1,0,0),-.08*burst+.012*math.sin(cycle)),('head',(0,0,1),.018*math.sin(cycle))]:
            arm.pose.bones[bone].rotation_quaternion = world_rot(arm.pose.bones[bone],axis,angle)
        for side,sign in [('l',1),('r',-1)]:
            for i in range(3):
                pb = arm.pose.bones[f'wing_{side}_{i}']
                pb.rotation_quaternion = world_rot(pb,(0,1,0),-sign*(.014*math.sin(cycle+i*.35)+burst*(.42 if i==0 else .10)))
        for i in range(9):
            pb = arm.pose.bones[f'tail_{i}']
            # Phase-delay chain starts and ends in the same rest-safe cycle.
            pb.rotation_quaternion = world_rot(pb,(0,0,1),(.022+.018*burst)*math.sin(cycle-i*.45))
        bpy.context.view_layer.update()
        for leg,offset in PHASE.items():
            rest = arm.data.bones[leg+'_foot'].head_local.copy()
            rest.z -= sole_offsets[leg]
            if name=='walk':
                target,yaw,_ = foot_target(rest,(t/WALK+offset)%1)
            else:
                target,yaw = rest,0.
            contact(arm,leg,target,yaw)
        for pb in arm.pose.bones:
            pb.keyframe_insert('rotation_quaternion',frame=frame,group=pb.name)
            pb.keyframe_insert('location',frame=frame,group=pb.name)
    for fc in action_fcurves(action):
        for key in fc.keyframe_points:
            key.interpolation = 'LINEAR'
    track = arm.animation_data.nla_tracks.new()
    track.name = name
    track.strips.new(name,0,action)
    track.mute = True
    arm.animation_data.action = None
    return action


def render_views(obj, arm, actions, out, points, masks):
    import runpy
    helpers = runpy.run_path(str(TRUSTED/'turnaround.py'),run_name='trusted_helpers')
    camera = helpers['setup_render'](900)
    scene = bpy.context.scene
    scene.render.image_settings.file_format = 'PNG'
    def render(tag, center, direction, size):
        c,d = Vector(center),Vector(direction).normalized()
        camera.location = c+d*5
        camera.rotation_euler = (c-camera.location).to_track_quat('-Z','Y').to_euler()
        camera.data.ortho_scale = size
        scene.render.filepath = str(out/(tag+'.png'))
        bpy.ops.render.render(write_still=True)
    center = (points.min(axis=0)+points.max(axis=0))/2
    size = max(np.ptp(points,axis=0))*1.22
    # Actual exported rig is reimported before these render calls.
    for name,action in actions.items():
        arm.animation_data.action = action
        arm.animation_data.action_slot = action.slots[0]
        for step in (0,1,2):
            frame = DURATIONS[name]*FPS*step/3
            scene.frame_set(int(frame),subframe=frame%1)
            render(f'{name}-{step}',center,(.7,-1,.3),size)
    arm.animation_data.action = None
    arm.data.pose_position = 'REST'
    indices = [p.material_index for p in obj.data.polygons]
    mats = list(obj.data.materials)
    palette = [(0.50,.48,.41,1),(.65,.28,.13,1),(.1,.46,.5,1),(.24,.5,.15,1),(.45,.18,.48,1),(.10,.2,.55,1)]
    obj.data.materials.clear()
    for i,color in enumerate(palette):
        material = bpy.data.materials.new('Mask'+str(i))
        material.diffuse_color = color
        material.use_nodes = True
        nodes = material.node_tree.nodes
        nodes.clear()
        emission = nodes.new('ShaderNodeEmission')
        emission.inputs['Color'].default_value = color
        output = nodes.new('ShaderNodeOutputMaterial')
        material.node_tree.links.new(emission.outputs[0],output.inputs['Surface'])
        obj.data.materials.append(material)
    lookup = {}
    for name,ids in masks.items():
        for index in ids:
            lookup[index] = 1 if name=='head' else 2 if name.startswith('wing') else 3 if name=='tail' else 4 if 'front' in name else 5
    for face in obj.data.polygons:
        face.material_index = max(lookup.get(i,0) for i in face.vertices)
    render('source-masks-34',center,(.7,-1,.3),size)
    render('source-masks-side',center,(1,0,.05),size)
    obj.data.materials.clear()
    for mat in mats:
        obj.data.materials.append(mat)
    for face,index in zip(obj.data.polygons,indices):
        face.material_index = index
    arm.data.pose_position = 'POSE'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('output',type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    source,out = args.source.resolve(),args.output.resolve()
    assert not out.exists()
    assert out.is_relative_to(TRUSTED.parent.parent/'raw/_build')
    out.mkdir(parents=True)
    obj,points,scale = load(source)
    original_fingerprint = native_fingerprint(obj)
    arm,lm,tail = make_rig(obj,points,scale)
    masks,weights = bind(obj,arm,points,scale)
    soles = {leg:float(points[masks['hoof_'+leg],2].min()) for leg in PHASE}
    (out/'rest-reference.json').write_text(json.dumps({'beast':'lu_fish','sourceSha256':SOURCE_SHA,'coordinates':'Blender [x,y,z], height1.35; glTF=[x,z,-y]', 'points':points.tolist(),'masks':masks},separators=(',',':'))+'\n')
    bpy.context.scene.render.fps = FPS
    bpy.context.scene.render.fps_base = 1.
    actions = {name:animate(arm,name,duration,soles) for name,duration in DURATIONS.items()}
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    assert native_fingerprint(obj) == original_fingerprint, 'Skinning changed native geometry/UV/normals/materials'
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    arm.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(out/'rigged.glb'),export_format='GLB',use_selection=True,
        export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,
        export_def_bones=False,export_extras=True,export_normals=True,export_frame_range=False)
    report = {'beast':'lu_fish','sourceSha256':SOURCE_SHA,'riggedSha256':sha(out/'rigged.glb'),
        'triangles':len(obj.data.polygons),'vertices':len(points),'scale':scale,'bones':len(arm.data.bones),
        'sourceTopologyUvPbrUnchanged':True,'normalizedNativeFingerprintSha256':original_fingerprint,
        'rigScriptSha256':sha(Path(__file__).resolve()),'nativeWingTailMeshes':True,'soleOffsets':soles,
        'runtimeContract':{'radius':RADIUS,'speed':SPEED,'walkSeconds':WALK,'duty':DUTY,'phases':PHASE,'yaw':'PI-angle; exact counter-yaw hooves'},
        'masks':{k:len(v) for k,v in masks.items()},'tailCenters':tail,'productionAccepted':False}
    (out/'audit.json').write_text(json.dumps(report,indent=2)+'\n')
    # Import the saved GLB, never render the unsaved working rig as evidence.
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(out/'rigged.glb'))
    obj = next(o for o in bpy.context.scene.objects if o.type=='MESH')
    arm = next(o for o in bpy.context.scene.objects if o.type=='ARMATURE')
    bpy.context.scene.render.fps = FPS
    bpy.context.scene.render.fps_base = 1.
    actions = {}
    for track in arm.animation_data.nla_tracks:
        for strip in track.strips:
            actions[strip.action.name] = strip.action
    assert set(actions)==set(DURATIONS), list(actions)
    # Match actual-export masks by rest geometry, because GLB splits material seams.
    from mathutils.kdtree import KDTree
    tree = KDTree(len(points))
    for i,p in enumerate(points): tree.insert(p,i)
    tree.balance()
    mapped = {name:[] for name in masks}
    selected = {name:set(ids) for name,ids in masks.items()}
    for v in obj.data.vertices:
        _,index,error = tree.find(obj.matrix_world@v.co)
        assert error<1e-5
        for name,ids in selected.items():
            if index in ids: mapped[name].append(v.index)
    actual_points = np.array([list(obj.matrix_world@v.co) for v in obj.data.vertices])
    render_views(obj,arm,actions,out,actual_points,mapped)
    assert sha(source)==SOURCE_SHA
    print('LU_NATIVE_RIG',json.dumps(report),flush=True)

if __name__=='__main__':
    main()
