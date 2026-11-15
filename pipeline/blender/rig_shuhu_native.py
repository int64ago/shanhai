"""Native v13 Shuhu rig. Unified builder CLI: INPUT OUTPUT --preview PREVIEW.png.

Forty bones: eight axial, four three-bone legs, paired four-bone wings,
and twelve curved snake-tail bones. All native geometry/UV/PBR is retained.
Calibration coordinates below are in the reviewed source frame (max extent=1).
"""
import argparse
import json
import math
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import bpy
import numpy as np
from mathutils import Matrix, Vector
import rig_quadruped as base
from rig_jingwei import set_segment
from rig_jimeng_native import native_fingerprint

ROOT = Path(__file__).resolve().parents[2]
QA = ROOT / 'raw/_build/shuhu-v13-rig-qa'
FPS, RADIUS, SPEED, DUTY = 30, 1.0, .10, .68
DURATIONS = {'idle': 4., 'walk': 2.4, 'special': 4.8}
LEGS = ('front_l', 'front_r', 'back_l', 'back_r')
PHASES = {'back_l': 0., 'front_l': .25, 'back_r': .5, 'front_r': .75}


def smooth(a, b, x):
    t = np.clip((x-a)/(b-a), 0, 1)
    return t*t*(3-2*t)


def activate(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def calibration(obj):
    local = np.array([tuple(v.co) for v in obj.data.vertices])
    matrix = np.asarray(obj.matrix_world)
    pts = local @ matrix[:3,:3].T + matrix[:3,3]
    extent = np.ptp(pts, axis=0)
    scale = float(max(extent))
    p = pts / scale
    feet = {}
    for leg in LEGS:
        side = 1 if leg.endswith('_l') else -1
        mask = (p[:, 2] < .045) & (p[:, 0]*side > 0)
        mask &= p[:, 1] < -.12 if leg.startswith('front') else p[:, 1] >= -.12
        band = p[mask]
        if len(band) < 100:
            raise ValueError('Calibrate a changed native hoof: ' + leg)
        mid = (band.min(axis=0)+band.max(axis=0))/2
        feet[leg] = Vector((mid[0], mid[1], 0))*scale
    lm = {'height': float(extent[2]), 'length': scale, 'legs': feet,
          'front_y': -.32*scale, 'back_y': .145*scale,
          'hips': Vector((0,.135,.445))*scale,
          'chest': Vector((0,-.29,.465))*scale, 'chest_top': .59*scale,
          'head': Vector((.015,-.385,.69))*scale,
          'snout': Vector((.02,-.49,.685))*scale,
          'rear': Vector((0,.205,.50))*scale}
    # The tail centerline follows the reviewed High, including the terminal curl.
    template = np.array([(0,.20,.50),(0,.275,.48),(.018,.345,.435),
                         (.07,.415,.36),(.14,.473,.28),(.21,.484,.225),
                         (.265,.46,.20),(.285,.425,.217),(.282,.405,.25)])
    for i in range(2, len(template)-1):
        tangent = template[min(i+1,len(template)-1)]-template[i-1]
        tangent /= np.linalg.norm(tangent)
        delta = p-template[i]
        band = (np.abs(delta@tangent)<.006) & (np.linalg.norm(delta,axis=1)<.052) & (p[:,1]>.255)
        if np.count_nonzero(band)>30:
            cross = p[band]
            template[i] = (np.quantile(cross,.03,axis=0)+np.quantile(cross,.97,axis=0))/2
    arc = np.r_[0,np.cumsum(np.linalg.norm(np.diff(template,axis=0),axis=1))]
    samples = np.linspace(0,arc[-1],13)
    tail = np.stack([np.interp(samples,arc,template[:,k]) for k in range(3)],axis=1)*scale
    return p, scale, lm, tail


def add_axial(arm):
    activate(arm)
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.data.edit_bones
    eb.remove(eb['tail_attach'])
    neck = eb['neck']
    old_tail = neck.tail.copy()
    middle = neck.head.lerp(old_tail,.52)
    neck.name = 'neck1'
    neck.tail = middle
    neck2 = eb.new('neck2')
    neck2.head, neck2.tail = middle, old_tail
    neck2.parent, neck2.use_connect = neck, True
    eb['head'].parent = neck2
    bpy.ops.object.mode_set(mode='OBJECT')


def add_appendages(arm, scale, tail):
    activate(arm)
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.data.edit_bones
    for side, label in [(1,'l'),(-1,'r')]:
        points = [(side*.12,-.225,.49),(side*.20,-.245,.53),
                  (side*.28,-.26,.57),(side*.345,-.27,.62),(side*.407,-.275,.675)]
        for i in range(4):
            b = eb.new(f'wing_{label}_{i}')
            b.head, b.tail = Vector(points[i])*scale, Vector(points[i+1])*scale
            b.parent = eb['chest' if i==0 else f'wing_{label}_{i-1}']
            b.use_connect = i>0
    for i in range(12):
        b = eb.new(f'snake_{i:02d}')
        b.head, b.tail = Vector(tail[i]), Vector(tail[i+1])
        b.parent = eb['hips' if i==0 else f'snake_{i-1:02d}']
        b.use_connect = i>0
    bpy.ops.object.mode_set(mode='OBJECT')


def distances(points, bones):
    result = []
    for bone in bones:
        a, b = np.array(bone.head_local), np.array(bone.tail_local)
        ab = b-a
        t = np.clip(((points-a)@ab)/max(float(ab@ab),1e-12),0,1)
        result.append(np.linalg.norm(points-a-t[:,None]*ab,axis=1))
    return np.stack(result,axis=1)


def weights_for(points, bones, keep=3):
    d = distances(points,bones)
    order = np.argsort(d,axis=1)
    keep = min(keep,len(bones))
    weights = np.zeros_like(d)
    ids = order[:,:keep]
    values = 1/np.maximum(np.take_along_axis(d,ids,axis=1),.004)**4
    values /= values.sum(axis=1,keepdims=True)
    np.put_along_axis(weights,ids,values,axis=1)
    return weights


def constrain_skin(obj, arm, p, scale, tail):
    bones = [b for b in arm.data.bones if b.use_deform]
    names = [b.name for b in bones]
    cols = {name:i for i,name in enumerate(names)}
    n = len(p)
    w = np.zeros((n,len(bones)),dtype=np.float32)
    for vertex in obj.data.vertices:
        for group in vertex.groups:
            name = obj.vertex_groups[group.group].name
            if name in cols:w[vertex.index,cols[name]]=group.weight
    xyz = p*scale
    def assign(mask, subset):
        if not np.any(mask):return
        w[mask]=0
        values = weights_for(xyz[mask],[arm.data.bones[name] for name in subset])
        w[np.ix_(mask,[cols[name] for name in subset])] = values
    axial = ['hips','spine1','spine2','chest','neck1','neck2','head']
    head = (np.abs(p[:,0]-.015)<.105) & (((p[:,2]>.64)&(p[:,1]<-.255)) | ((p[:,2]>.595)&(p[:,1]<-.405)))
    wing = (np.abs(p[:,0])>.115)&(p[:,1]<-.105)&(p[:,2]>.31)&~head
    tail_d = distances(xyz,[arm.data.bones[f'snake_{i:02d}'] for i in range(12)])
    snake = (tail_d.min(axis=1)<.065*scale)&(p[:,1]>.20)
    # Torso cannot inherit limb or appendage weights through a nearby surface.
    torso = ~head&~wing&~snake
    assign(torso,axial)
    for leg in LEGS:
        side = 1 if leg.endswith('_l') else -1
        mask = (p[:,0]*side>=0)&(p[:,2]<.47)&~head&~wing&~snake
        mask &= p[:,1]<-.12 if leg.startswith('front') else p[:,1]>=-.12
        subset = [leg+'_upper',leg+'_lower',leg+'_foot', 'chest' if leg.startswith('front') else 'hips']
        limb = weights_for(xyz[mask],[arm.data.bones[name] for name in subset])
        blend = (1-smooth(.24,.47,p[mask,2])) * (1-smooth(.22,.32,p[mask,2])*(1-smooth(.015,.065,np.abs(p[mask,0]))))
        w[mask] *= 1-blend[:,None]
        for col,name in enumerate(subset):
            w[mask,cols[name]] += limb[:,col]*blend
        hoof = mask&(p[:,2]<.043)
        w[hoof]=0
        w[hoof,cols[leg+'_foot']]=1
    for side,label in [(1,'l'),(-1,'r')]:
        mask = wing&(p[:,0]*side>0)
        subset = [f'wing_{label}_{i}' for i in range(4)]
        assign(mask,subset)
        root = 1-smooth(.12,.19,np.abs(p[mask,0]))
        w[mask] *= (1-root[:,None])
        w[mask,cols['chest']] += root
    assign(snake,[f'snake_{i:02d}' for i in range(12)])
    root = 1-smooth(.205,.285,p[snake,1])
    w[snake] *= (1-root[:,None])
    w[snake,cols['hips']] += root
    w[head]=0
    w[head,cols['head']]=1
    missing = w.sum(axis=1)<1e-6
    assign(missing,axial)
    # Four influences, normalized before writing; original mesh attributes stay intact.
    order = np.argsort(w,axis=1)
    np.put_along_axis(w,order[:,:-4],0,axis=1)
    w /= w.sum(axis=1,keepdims=True)
    obj.vertex_groups.clear()
    for col,name in enumerate(names):
        group = obj.vertex_groups.new(name=name)
        # Quantized batches avoid a million Python operator calls; renormalized below.
        quant = np.rint(w[:,col]*4095).astype(np.int16)
        positive=np.flatnonzero(quant>0)
        ordered=positive[np.argsort(quant[positive])]
        values,starts=np.unique(quant[ordered],return_index=True)
        for value,indices in zip(values,np.split(ordered,starts[1:])):
            group.add(indices.tolist(),float(value)/4095,'REPLACE')
    base.normalize_weights(obj)
    diagnostic = np.tile((.65,.58,.43,1.),(n,1))
    diagnostic[head]=(.9,.18,.24,1)
    diagnostic[wing&(p[:,0]>0)]=(.12,.65,.9,1)
    diagnostic[wing&(p[:,0]<0)]=(.72,.28,.9,1)
    diagnostic[snake]=(.15,.72,.35,1)
    for i,leg in enumerate(LEGS):
        side = 1 if leg.endswith('_l') else -1
        mask = (p[:,0]*side>0)&(p[:,2]<.31)&~snake&~wing
        mask &= p[:,1]<-.12 if leg.startswith('front') else p[:,1]>=-.12
        diagnostic[mask]=[(.9,.65,.15,1),(.9,.4,.12,1),(.25,.45,.9,1),(.2,.8,.7,1)][i]
    return diagnostic, {k:int(v) for k,v in [('head',head.sum()),('wing',wing.sum()),('snake',snake.sum())]}


def contact(arm, leg, frame, lateral=0, backward=0, lift=0, yaw=0):
    upper,lower,foot = [arm.pose.bones[leg+'_'+part] for part in ('upper','lower','foot')]
    parent = upper.parent
    hip = parent.matrix @ (parent.bone.matrix_local.inverted() @ upper.bone.head_local)
    ankle = foot.bone.head_local
    target = ankle+Vector((lateral,backward,lift))
    axis = target-hip
    direction = axis.normalized()
    l1,l2 = upper.bone.length,lower.bone.length
    distance = min(axis.length,(l1+l2)*.99999)
    along = (l1*l1-l2*l2+distance*distance)/(2*distance)
    normal = Vector((0,-direction.z,direction.y)).normalized()
    rest_axis = (lower.bone.tail_local-upper.bone.head_local).normalized()
    rest_normal = Vector((0,-rest_axis.z,rest_axis.y)).normalized()
    sign = 1 if (upper.bone.tail_local-upper.bone.head_local).dot(rest_normal)>=0 else -1
    knee = hip+direction*along+normal*math.sqrt(max(0,l1*l1-along*along))*sign
    set_segment(upper,hip,knee)
    set_segment(lower,knee,target)
    foot.matrix = Matrix.Translation(target)@Matrix.Rotation(yaw,4,'Z')@Matrix.Translation(-ankle)@foot.bone.matrix_local
    bpy.context.view_layer.update()
    for bone in (upper,lower,foot):
        bone.keyframe_insert('rotation_quaternion',frame=frame)
        bone.keyframe_insert('location',frame=frame)


def animate(arm,name,seconds):
    action = base.new_action(arm,name)
    count = round(seconds*FPS)
    for frame in range(count+1):
        phase,t = frame/count,frame/FPS
        envelope = float(smooth(.15,.95,t)*(1-smooth(3.35,4.65,t))) if name=='special' else 0.
        pose = {}
        pose['head']=base.world_rot(arm.pose.bones['head'],base.X,.009*math.sin(phase*math.tau)-.018*envelope)
        pose['neck1']=base.world_rot(arm.pose.bones['neck1'],base.X,-.012*envelope)
        pose['chest']=base.world_rot(arm.pose.bones['chest'],base.X,-.018*envelope)
        for side,label in [(1,'l'),(-1,'r')]:
            for i in range(4):
                bone = arm.pose.bones[f'wing_{label}_{i}']
                angle = (.012 if name=='idle' else .023)*math.sin(phase*math.tau-i*.35)
                angle += envelope*(.20 if i==0 else .055)*math.sin(t*math.tau*.55-i*.4)
                pose[bone.name]=base.world_rot(bone,base.Y,-side*angle)
        for i in range(12):
            bone=arm.pose.bones[f'snake_{i:02d}']
            amplitude=(.009+.018*i/11)*(1+.7*envelope)
            pose[bone.name]=base.world_rot(bone,base.Z,amplitude*math.sin(phase*math.tau-i*.40))@base.world_rot(bone,base.X,.4*amplitude*math.sin(phase*math.tau-i*.4+.8))
        delta=Vector((0,0,-.016 if name=='walk' else -.003*(1-math.cos(phase*math.tau))-.009*envelope))
        base.key_loc(arm,frame,'root',arm.data.bones['root'].matrix_local.to_3x3().inverted()@delta)
        base.key_pose(arm,frame,pose)
        bpy.context.view_layer.update()
        for leg in LEGS:
            lateral=backward=lift=yaw=0.
            if name=='walk':
                p=(phase+PHASES[leg])%1
                if p<DUTY:relative=seconds*(p-DUTY/2)
                else:
                    u=(p-DUTY)/(1-DUTY)
                    recovery=u*u*u*(10-15*u+6*u*u)
                    relative=seconds*DUTY*(.5-recovery)
                    lift=.052*math.sin(math.pi*u)**2
                yaw=-SPEED/RADIUS*relative
                ankle=arm.data.bones[leg+'_foot'].head_local
                x,y=ankle.x-RADIUS,ankle.y
                lateral=RADIUS+math.cos(yaw)*x-math.sin(yaw)*y-ankle.x
                backward=math.sin(yaw)*x+math.cos(yaw)*y-ankle.y
            contact(arm,leg,frame,lateral,backward,lift,yaw)
    base.finish_action(arm,action)
    for fc in base.action_fcurves(action):
        for key in fc.keyframe_points:key.interpolation='LINEAR'
    return action


def render_view(obj,path,direction=(1,-1.6,.35),size=900):
    scene=bpy.context.scene
    scene.render.engine='CYCLES'
    scene.cycles.samples=12
    scene.cycles.use_denoising=True
    scene.render.resolution_x=scene.render.resolution_y=size
    scene.render.resolution_percentage=100
    scene.view_settings.view_transform='AgX'
    if not scene.world:
        world=bpy.data.worlds.new('native_rig_world')
        world.use_nodes=True
        world.node_tree.nodes['Background'].inputs[0].default_value=(.52,.52,.52,1)
        world.node_tree.nodes['Background'].inputs[1].default_value=.8
        scene.world=world
        for i,(loc,power) in enumerate([((3,-4,5),450),((-4,-2,3),300),((1,4,4),300)]):
            data=bpy.data.lights.new('softbox'+str(i),'AREA');data.energy=power;data.size=4
            light=bpy.data.objects.new(data.name,data);scene.collection.objects.link(light);light.location=loc
            light.rotation_euler=(Vector((0,0,.7))-light.location).to_track_quat('-Z','Y').to_euler()
    target=Vector((0,0,.71))
    cam=bpy.data.objects.new('review_cam',bpy.data.cameras.new('review_cam'))
    scene.collection.objects.link(cam);cam.data.type='ORTHO';cam.data.ortho_scale=1.95
    cam.location=target+Vector(direction).normalized()*5
    cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler()
    scene.camera=cam;bpy.context.view_layer.update();scene.render.filepath=str(path)
    bpy.ops.render.render(write_still=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source');parser.add_argument('output');parser.add_argument('--preview',required=True)
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    QA.mkdir(parents=True,exist_ok=True)
    obj=base.load(args.source)
    activate(obj)
    # Retain the preparation node's positive uniform normalization transform.
    before=native_fingerprint(obj)
    p,scale,lm,tail=calibration(obj)
    arm=base.build_armature(lm);arm.name='shuhu_native_rig';add_axial(arm)
    # Heat -> water-tight proxy -> distance fallback for the native body/limbs.
    base.skin(obj,arm)
    add_appendages(arm,scale,tail)
    diagnostic,counts=constrain_skin(obj,arm,p,scale,tail)
    attr=obj.data.color_attributes.new(name='shuhu_mask_review',type='FLOAT_COLOR',domain='POINT')
    attr.data.foreach_set('color',diagnostic.astype(np.float32).ravel())
    original_materials=list(obj.data.materials)
    maskmat=bpy.data.materials.new('anatomical_mask_review');maskmat.use_nodes=True
    nodes=maskmat.node_tree.nodes;nodes.clear();out=nodes.new('ShaderNodeOutputMaterial');emit=nodes.new('ShaderNodeEmission');col=nodes.new('ShaderNodeVertexColor');col.layer_name=attr.name
    maskmat.node_tree.links.new(col.outputs['Color'],emit.inputs['Color']);maskmat.node_tree.links.new(emit.outputs[0],out.inputs[0])
    obj.data.materials.clear();obj.data.materials.append(maskmat)
    render_view(obj,QA/'mask_front.png',(0,-1,0))
    render_view(obj,QA/'mask_back.png',(0,1,0))
    render_view(obj,QA/'mask_34.png')
    obj.data.materials.clear()
    for mat in original_materials:obj.data.materials.append(mat)
    obj.data.color_attributes.remove(attr)
    after=native_fingerprint(obj)
    if before!=after:raise ValueError('Skin stage changed native geometry/UV/normals/PBR')
    bpy.context.scene.render.fps=FPS
    actions={name:animate(arm,name,seconds) for name,seconds in DURATIONS.items()}
    arm.animation_data.action=actions['idle'];bpy.context.scene.frame_set(0)
    render_view(obj,Path(args.preview))
    for name,action in actions.items():
        arm.animation_data.action=action
        for fraction in [.25,.5,.75]:
            bpy.context.scene.frame_set(round(DURATIONS[name]*FPS*fraction))
            render_view(obj,QA/f'{name}_{round(fraction*100)}.png')
    arm.animation_data.action=None
    bpy.context.scene.frame_set(0)
    activate(obj);arm.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(Path(args.output).resolve()),export_format='GLB',use_selection=True,
                             export_animations=True,export_animation_mode='NLA_TRACKS',export_skins=True,
                             export_def_bones=False,export_extras=True)
    manifest={'source':str(Path(args.source).resolve()),'triangles':500000,
              'boneCount':len(arm.data.bones),'maskCounts':counts,
              'unweightedVertices':base.unweighted_count(obj),'nativeFingerprint':after,
              'nativeGeometryPreserved':before==after,'runtime':{'radius':RADIUS,'speed':SPEED,'scale':1,'fps':FPS,'stanceDuty':DUTY,'durations':DURATIONS},
              'tailCenterline':tail.tolist(),'landmarks':{key:list(value) for key,value in lm.items() if isinstance(value,Vector)}}
    (QA/'rig-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print('SHUHU_RIG',len(arm.data.bones),'bones; 500000 triangles; unweighted',base.unweighted_count(obj),flush=True)


if __name__=='__main__':main()
