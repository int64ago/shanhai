"""Zouwu's inverse circular paw targets and short, grounded spring.

The runtime's 1.8m turn at .18m/s is inverted for every planted ankle AND paw
orientation. The sole stays fixed in world XYZ through the full support phase.
--existing-rig keeps the shipped cat mesh, normals, UVs, skeleton and weights.
"""
import math
import sys
from pathlib import Path
import bpy
from mathutils import Matrix, Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_quadruped as rig
from rig_jingwei import set_segment
from rig_quadruped import FPS, X, finish_action, key_loc, key_pose, new_action, world_rot

RADIUS = 1.8
SPEED = .18
DUTY = .65
WALK_SECONDS = 1.6


def smooth(a, b, x):
    t = max(0, min(1, (x-a)/(b-a)))
    return t*t*(3-2*t)


def contact(arm, leg, frame, delta, lateral=0, backward=0, lift=0, yaw=0):
    upper,lower,foot = (arm.pose.bones[leg+'_'+part] for part in ('upper','lower','foot'))
    hip = upper.bone.head_local+delta
    ankle = foot.bone.head_local
    target = ankle+Vector((lateral,backward,lift))
    direction = (target-hip).normalized()
    l1,l2 = upper.bone.length,lower.bone.length
    distance = min((target-hip).length,(l1+l2)*.99999)
    along = (l1*l1-l2*l2+distance*distance)/(2*distance)
    normal = Vector((0,-direction.z,direction.y)).normalized()
    # Keep the shipped cat's authored elbow/hock branch. The importer's bone
    # display tails are not anatomical guides for selecting the IK branch.
    sign = -1 if leg.startswith('front') else 1
    knee = hip+direction*along+normal*math.sqrt(max(0,l1*l1-along*along))*sign
    set_segment(upper,hip,knee)
    set_segment(lower,knee,target)
    foot.matrix = Matrix.Translation(target)@Matrix.Rotation(yaw,4,'Z')@Matrix.Translation(-ankle)@foot.bone.matrix_local
    bpy.context.view_layer.update()
    for bone in (upper,lower,foot):
        bone.keyframe_insert('rotation_quaternion',frame=frame)
        bone.keyframe_insert('location',frame=frame)


def animate(arm, name, seconds):
    action = new_action(arm, name)
    n = round(seconds*FPS)
    for frame in range(n+1):
        t, phase = frame/FPS, frame/n
        crouch = land = air = 0
        if name == 'alert':
            crouch = smooth(.2, 1.2, t)*(1-smooth(1.6, 1.85, t))
            land = smooth(2.38, 2.58, t)*(1-smooth(2.58, 3.2, t))
            air = smooth(1.78, 1.98, t)*(1-smooth(2.12, 2.40, t))
        drop = .035 if name == 'walk' else .018+.003*math.sin(phase*math.tau) if name == 'idle' else .018+.065*crouch+.045*land
        delta = Vector((0, 0, -drop+.14*air))
        pose = {'neck':world_rot(arm.pose.bones['neck'],X,.09*crouch-.065*air),
                'head':world_rot(arm.pose.bones['head'],X,-.05*crouch+.012*math.sin(phase*math.tau))}
        key_loc(arm,frame,'root',arm.data.bones['root'].matrix_local.to_3x3().inverted()@delta)
        key_pose(arm,frame,pose)
        bpy.context.view_layer.update()
        for leg,offset in [('back_l',0),('front_l',.25),('back_r',.5),('front_r',.75)]:
            lateral = backward = lift = yaw = 0
            if name == 'walk':
                p = (phase+offset)%1
                if p < DUTY:
                    relative = seconds*(p-DUTY/2)
                else:
                    u = (p-DUTY)/(1-DUTY)
                    relative = seconds*DUTY*(.5-u*u*(3-2*u))
                    lift = .055*math.sin(math.pi*u)
                yaw = -SPEED/RADIUS*relative
                ankle = arm.data.bones[leg+'_foot'].head_local
                x, y = ankle.x-RADIUS, ankle.y
                lateral = RADIUS+math.cos(yaw)*x-math.sin(yaw)*y-ankle.x
                backward = math.sin(yaw)*x+math.cos(yaw)*y-ankle.y
            elif name == 'alert':
                # The feet leave and regain exactly the same ground anchors.
                # Root height and tuck share the same compact flight envelope.
                lift = .18*air
                backward = (-.018 if leg.startswith('front') else .018)*air
            contact(arm,leg,frame,delta,lateral,backward,lift,yaw)
    finish_action(arm,action)
    # Avoid Bezier overshoot around ankle contacts and takeoff/landing.
    for curve in rig.action_fcurves(action):
        for key in curve.keyframe_points:
            key.interpolation = 'LINEAR'


def idle(arm, lm): animate(arm,'idle',4)
def walk(arm, lm): animate(arm,'walk',WALK_SECONDS)
def alert(arm, lm): animate(arm,'alert',4.6)


base_skin = rig.skin


def skin_with_paws(obj, arm):
    base_skin(obj, arm)
    lm = rig.landmarks(obj)
    for vertex in obj.data.vertices:
        if vertex.co.z >= .14:
            continue
        leg = min(lm['legs'],key=lambda n:(Vector((vertex.co.x,vertex.co.y,0))-lm['legs'][n]).length_squared)
        foot = obj.vertex_groups[f'{leg}_foot']
        w = 1-smooth(.08,.14,vertex.co.z)
        old = {g.group:g.weight for g in vertex.groups}
        for index,weight in old.items():
            obj.vertex_groups[index].add([vertex.index],weight*(1-w),'REPLACE')
        foot.add([vertex.index],old.get(foot.index,0)*(1-w)+w,'REPLACE')
    rig.normalize_weights(obj)


def existing(source, output):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    arm = next(o for o in bpy.context.scene.objects if o.type == 'ARMATURE')
    body = bpy.data.objects['body']
    arm.animation_data_clear()
    for bone in arm.pose.bones:
        bone.matrix_basis.identity()
    # Importer-only bone display meshes and old actions are not runtime assets.
    for obj in list(bpy.context.scene.objects):
        if obj not in (arm,body): bpy.data.objects.remove(obj,do_unlink=True)
    for action in list(bpy.data.actions): bpy.data.actions.remove(action)
    bpy.context.scene.render.fps = FPS
    for name,seconds in [('idle',4),('walk',WALK_SECONDS),('alert',4.6)]:
        animate(arm,name,seconds)
    bpy.context.scene.frame_set(0)
    bpy.ops.export_scene.gltf(filepath=output,export_format='GLB',export_animations=True,
                            export_animation_mode='NLA_TRACKS',export_skins=True,export_def_bones=False)
    print('ZOUWU_RIG retained',len(body.data.vertices),'vertices;',len(arm.data.bones),'bones')


rig.skin = skin_with_paws
rig.anim_idle = idle
rig.anim_walk = walk
rig.anim_alert = alert
if __name__ == '__main__':
    argv = sys.argv[sys.argv.index('--')+1:]
    if '--existing-rig' in argv:
        argv.remove('--existing-rig')
        existing(*argv)
    else:
        rig.main()
