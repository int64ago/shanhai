"""
禽鸟型（avian，如毕方、凤凰、精卫、蛊雕）自动绑骨骼 + 程序化关键帧（idle / walk / alert），导出带动画的 GLB。
兼容居中独足（如毕方「一足」）与对称双足禽鸟：
- 躯干与头颈尾：root / pelvis / chest / neck / head / tail_feather
- 双翼三段链：wing_{l,r}_{1,2,3}
- 鸟足三段链：leg_upper / leg_lower / foot（独足居中 x≈0）
- 灵火/特效挂点：beak_attach / wing_l_attach / wing_r_attach / tail_attach

输入须先经过 normalize.py：头朝 -Y（glTF +Z），脚底 z=0。
"""
import argparse
import math
import sys

import bpy
from mathutils import Quaternion, Vector

FPS = 30


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('input')
    p.add_argument('output')
    p.add_argument('--preview')
    return p.parse_args(argv)


def load(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if len(meshes) != 1:
        raise RuntimeError(f'期望 1 个网格，实际 {len(meshes)}；请先跑 normalize.py')
    obj = meshes[0]
    for o in list(bpy.context.scene.objects):
        if o is not obj:
            bpy.data.objects.remove(o)
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def landmarks(obj):
    vs = [obj.matrix_world @ v.co for v in obj.data.vertices]
    xs = [v.x for v in vs]
    ys = [v.y for v in vs]
    zs = [v.z for v in vs]
    span = max(xs) - min(xs)
    height = max(zs)
    y_min, y_max = min(ys), max(ys)

    # 落地鸟爪中心
    low = [v for v in vs if v.z < height * 0.08]
    foot_c = sum(low, Vector()) / max(1, len(low))
    leg_mid = [v for v in vs if height * 0.12 < v.z < height * 0.35 and abs(v.x) < span * 0.15]
    leg_c = sum(leg_mid, Vector()) / max(1, len(leg_mid))
    leg_x = leg_c.x if leg_mid else 0.0
    leg_y = leg_c.y if leg_mid else foot_c.y

    # 躯干（中轴附近、腿部以上、颈部以下）
    torso_pts = [v for v in vs if abs(v.x) < span * 0.12 and height * 0.42 < v.z < height * 0.68]
    torso_c = sum(torso_pts, Vector()) / max(1, len(torso_pts))

    # 头部与长喙（最上方 + 最前方）
    top_pts = [v for v in vs if v.z > height * 0.78 and abs(v.x) < span * 0.12]
    beak_tip = min(top_pts, key=lambda v: v.y) if top_pts else Vector((0, y_min, height * 0.85))
    skull_pts = [v for v in top_pts if v.y > beak_tip.y + (y_max - y_min) * 0.12]
    head_base = sum(skull_pts, Vector()) / max(1, len(skull_pts)) if skull_pts else Vector((0, torso_c.y - 0.06, height * 0.84))

    # 尾羽尖端（躯干后方 y 最大处）
    rear_pts = [v for v in vs if abs(v.x) < span * 0.16 and v.y > torso_c.y + 0.08 and height * 0.35 < v.z < height * 0.72]
    tail_tip = max(rear_pts, key=lambda v: v.y) if rear_pts else Vector((0, y_max, torso_c.z - 0.05))

    # 双翼采样（左翼 +X，右翼 -X）
    def wing_chain(sign):
        w_pts = [v for v in vs if sign * v.x > span * 0.10 and v.z > height * 0.42]
        if not w_pts:
            return [
                Vector((sign * span * 0.10, torso_c.y, torso_c.z + 0.04)),
                Vector((sign * span * 0.24, torso_c.y + 0.02, torso_c.z + 0.12)),
                Vector((sign * span * 0.38, torso_c.y + 0.03, torso_c.z + 0.22)),
                Vector((sign * span * 0.48, torso_c.y + 0.04, torso_c.z + 0.30)),
            ]
        x_max = max(sign * v.x for v in w_pts)
        anchors = []
        for frac in (0.18, 0.45, 0.72, 0.95):
            target_x = sign * x_max * frac
            band = [v for v in w_pts if abs(v.x - target_x) < x_max * 0.08]
            if band:
                c = sum(band, Vector()) / len(band)
                anchors.append(c)
            else:
                anchors.append(Vector((target_x, torso_c.y, torso_c.z + frac * 0.25)))
        return anchors

    return {
        'span': span,
        'height': height,
        'leg_x': leg_x,
        'leg_y': leg_y,
        'pelvis': Vector((0, leg_y + 0.01, height * 0.46)),
        'chest': Vector((0, torso_c.y - 0.02, height * 0.58)),
        'neck_base': Vector((0, torso_c.y - 0.04, height * 0.65)),
        'head_base': Vector((0, head_base.y, head_base.z)),
        'beak_tip': Vector((0, beak_tip.y, beak_tip.z)),
        'tail_base': Vector((0, torso_c.y + 0.07, height * 0.49)),
        'tail_tip': Vector((0, tail_tip.y, tail_tip.z)),
        'wing_l': wing_chain(1.0),
        'wing_r': wing_chain(-1.0),
    }


def build_armature(lm):
    arm_data = bpy.data.armatures.new('rig')
    arm = bpy.data.objects.new('rig', arm_data)
    bpy.context.scene.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm_data.edit_bones

    def bone(name, head, tail, parent=None, deform=True):
        b = eb.new(name)
        b.head, b.tail = head, tail
        b.roll = 0
        b.use_deform = deform
        if parent:
            b.parent = eb[parent]
            b.use_connect = (eb[parent].tail - head).length < 1e-4
        return b

    h = lm['height']
    bone('root', Vector((0, 0, 0)), Vector((0, 0, h * 0.12)), deform=False)
    bone('pelvis', lm['pelvis'], lm['chest'], 'root')
    bone('chest', lm['chest'], lm['neck_base'], 'pelvis')
    bone('neck', lm['neck_base'], lm['head_base'], 'chest')
    bone('head', lm['head_base'], lm['beak_tip'], 'neck')
    bone('tail_feather', lm['tail_base'], lm['tail_tip'], 'pelvis')

    # 居中独足三段链（大腿 → 胫跗骨 → 鸟趾）
    lx, ly = lm['leg_x'], lm['leg_y']
    hip_pt = Vector((lx, ly, h * 0.44))
    knee_pt = Vector((lx, ly + 0.01, h * 0.24))
    ankle_pt = Vector((lx, ly, h * 0.045))
    toe_pt = Vector((lx, ly - 0.08, 0.0))
    bone('leg_upper', hip_pt, knee_pt, 'pelvis')
    bone('leg_lower', knee_pt, ankle_pt, 'leg_upper')
    bone('foot', ankle_pt, toe_pt, 'leg_lower')

    # 左右双翼三段骨骼链
    for side, pts in (('l', lm['wing_l']), ('r', lm['wing_r'])):
        bone(f'wing_{side}_1', pts[0], pts[1], 'chest')
        bone(f'wing_{side}_2', pts[1], pts[2], f'wing_{side}_1')
        bone(f'wing_{side}_3', pts[2], pts[3], f'wing_{side}_2')
        bone(f'wing_{side}_attach', pts[2], pts[3], f'wing_{side}_3', deform=False)

    bone('beak_attach', lm['beak_tip'], lm['beak_tip'] + Vector((0, -0.05, 0)), 'head', deform=False)
    bone('tail_attach', lm['tail_tip'], lm['tail_tip'] + Vector((0, 0.06, 0)), 'tail_feather', deform=False)

    bpy.ops.object.mode_set(mode='OBJECT')
    return arm


def skin(obj, arm, falloff=5.5, keep=3):
    """按顶点到骨骼线段的距离分配权重并平滑，适配展翼禽鸟复杂的飞羽拓扑。"""
    deform = [b for b in arm.data.bones if b.use_deform]
    segs = [(b.name, arm.matrix_world @ b.head_local, arm.matrix_world @ b.tail_local) for b in deform]
    obj.vertex_groups.clear()
    groups = {name: obj.vertex_groups.new(name=name) for name, _, _ in segs}
    mw = obj.matrix_world
    for v in obj.data.vertices:
        p = mw @ v.co
        scored = []
        for name, a, b in segs:
            ab = b - a
            t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-8)))
            d = (a + ab * t - p).length
            scored.append((d, name))
        scored.sort()
        nearest = scored[:keep]
        ws = [1.0 / max(d, 1e-4) ** falloff for d, _ in nearest]
        total = sum(ws)
        for (_, name), w in zip(nearest, ws):
            if w / total > 0.01:
                groups[name].add([v.index], w / total, 'REPLACE')

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
    bpy.ops.object.vertex_group_smooth(group_select_mode='ALL', factor=0.5, repeat=6)
    bpy.ops.object.vertex_group_limit_total(group_select_mode='ALL', limit=4)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode='ALL', lock_active=False)
    bpy.ops.object.mode_set(mode='OBJECT')

    mod = obj.modifiers.new('rig', 'ARMATURE')
    mod.object = arm
    obj.parent = arm
    print(f'SKIN avian distance weights done, verts={len(obj.data.vertices)}')


def world_rot(pb, axis, angle):
    rest = pb.bone.matrix_local.to_3x3()
    return Quaternion(rest.inverted() @ Vector(axis), angle)


def key_pose(arm, frame, pose):
    for name, q in pose.items():
        pb = arm.pose.bones[name]
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = q
        pb.keyframe_insert('rotation_quaternion', frame=frame)


def key_loc(arm, frame, name, loc):
    pb = arm.pose.bones[name]
    pb.location = loc
    pb.keyframe_insert('location', frame=frame)


def new_action(arm, name):
    arm.animation_data_create()
    action = bpy.data.actions.new(name)
    arm.animation_data.action = action
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = Quaternion()
        pb.location = Vector()
    return action


def action_fcurves(action):
    if hasattr(action, 'layers') and action.layers:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    yield from bag.fcurves
    else:
        yield from action.fcurves


def finish_action(arm, action):
    for fc in action_fcurves(action):
        for kp in fc.keyframe_points:
            kp.interpolation = 'BEZIER'
        mod = fc.modifiers.new('CYCLES')
        mod.mode_before = mod.mode_after = 'REPEAT'
    track = arm.animation_data.nla_tracks.new()
    track.name = action.name
    track.strips.new(action.name, int(action.frame_range[0]), action)
    track.mute = True
    arm.animation_data.action = None


X = (1, 0, 0)
Y = (0, 1, 0)
Z = (0, 0, 1)


def anim_idle(arm, lm):
    """4 秒循环：独足鹤立、轻舒双翼呼吸，修颈微转顾盼"""
    action = new_action(arm, 'idle')
    n = 4 * FPS
    h = lm['height']
    for f in range(0, n + 1, 4):
        t = f / n * 2 * math.pi
        breath = math.sin(t * 2)
        flap1 = math.sin(t * 2 - 0.3)
        flap2 = math.sin(t * 2 - 0.9)
        flap3 = math.sin(t * 2 - 1.5)
        key_pose(arm, f, {
            'pelvis': world_rot(arm.pose.bones['pelvis'], X, 0.02 * breath),
            'chest': world_rot(arm.pose.bones['chest'], X, -0.025 * breath),
            'neck': world_rot(arm.pose.bones['neck'], Z, 0.14 * math.sin(t))
                    @ world_rot(arm.pose.bones['neck'], X, 0.04 * math.cos(t * 2)),
            'head': world_rot(arm.pose.bones['head'], X, -0.04 * math.cos(t * 2))
                    @ world_rot(arm.pose.bones['head'], Y, 0.06 * math.sin(t + 0.5)),
            'tail_feather': world_rot(arm.pose.bones['tail_feather'], X, 0.05 * flap2),
            'wing_l_1': world_rot(arm.pose.bones['wing_l_1'], Y, 0.07 * flap1),
            'wing_l_2': world_rot(arm.pose.bones['wing_l_2'], Y, 0.09 * flap2),
            'wing_l_3': world_rot(arm.pose.bones['wing_l_3'], Y, 0.11 * flap3),
            'wing_r_1': world_rot(arm.pose.bones['wing_r_1'], Y, -0.07 * flap1),
            'wing_r_2': world_rot(arm.pose.bones['wing_r_2'], Y, -0.09 * flap2),
            'wing_r_3': world_rot(arm.pose.bones['wing_r_3'], Y, -0.11 * flap3),
        })
        key_loc(arm, f, 'pelvis', Vector((0, 0.008 * h * breath, 0)))
    finish_action(arm, action)


def anim_walk(arm, lm):
    """1 秒循环：毕方独足轻跃行进 + 双翼随步伐拍动平衡"""
    action = new_action(arm, 'walk')
    n = FPS
    h = lm['height']
    for f in range(0, n + 1, 2):
        t = f / n * 2 * math.pi
        hop = math.sin(t)
        lift = max(0.0, hop)
        flap1 = math.sin(t - 0.2)
        flap2 = math.sin(t - 0.7)
        flap3 = math.sin(t - 1.2)
        u_ang = -0.22 * math.cos(t)
        l_ang = 0.36 * lift
        f_ang = -(u_ang + l_ang) + 0.18 * lift
        key_pose(arm, f, {
            'pelvis': world_rot(arm.pose.bones['pelvis'], X, -0.06 + 0.05 * hop),
            'chest': world_rot(arm.pose.bones['chest'], X, -0.04 * hop),
            'neck': world_rot(arm.pose.bones['neck'], X, 0.08 * math.cos(t)),
            'head': world_rot(arm.pose.bones['head'], X, -0.06 * math.cos(t)),
            'tail_feather': world_rot(arm.pose.bones['tail_feather'], X, 0.12 * math.cos(t)),
            'leg_upper': world_rot(arm.pose.bones['leg_upper'], X, u_ang),
            'leg_lower': world_rot(arm.pose.bones['leg_lower'], X, l_ang),
            'foot': world_rot(arm.pose.bones['foot'], X, f_ang),
            'wing_l_1': world_rot(arm.pose.bones['wing_l_1'], Y, 0.18 * flap1),
            'wing_l_2': world_rot(arm.pose.bones['wing_l_2'], Y, 0.22 * flap2),
            'wing_l_3': world_rot(arm.pose.bones['wing_l_3'], Y, 0.25 * flap3),
            'wing_r_1': world_rot(arm.pose.bones['wing_r_1'], Y, -0.18 * flap1),
            'wing_r_2': world_rot(arm.pose.bones['wing_r_2'], Y, -0.22 * flap2),
            'wing_r_3': world_rot(arm.pose.bones['wing_r_3'], Y, -0.25 * flap3),
        })
        key_loc(arm, f, 'pelvis', Vector((0, 0.032 * h * lift, 0)))
    finish_action(arm, action)


def anim_alert(arm, lm):
    """2 秒循环：「其鸣自訆，见则其邑有讹火」——振翅腾跃、昂首长唳"""
    action = new_action(arm, 'alert')
    n = 2 * FPS
    h = lm['height']
    for f in range(0, n + 1, 2):
        t = f / n * 2 * math.pi
        flap1 = math.sin(t * 2)
        flap2 = math.sin(t * 2 - 0.55)
        flap3 = math.sin(t * 2 - 1.1)
        soar = abs(math.sin(t))
        key_pose(arm, f, {
            'pelvis': world_rot(arm.pose.bones['pelvis'], X, 0.08 * math.sin(t)),
            'chest': world_rot(arm.pose.bones['chest'], X, -0.16),
            'neck': world_rot(arm.pose.bones['neck'], X, -0.20 + 0.06 * math.sin(t * 2))
                    @ world_rot(arm.pose.bones['neck'], Z, 0.15 * math.sin(t)),
            'head': world_rot(arm.pose.bones['head'], X, 0.18),
            'tail_feather': world_rot(arm.pose.bones['tail_feather'], X, 0.16 * flap2),
            'leg_upper': world_rot(arm.pose.bones['leg_upper'], X, 0.18 * soar),
            'leg_lower': world_rot(arm.pose.bones['leg_lower'], X, 0.25 * soar),
            'foot': world_rot(arm.pose.bones['foot'], X, 0.22 * soar),
            'wing_l_1': world_rot(arm.pose.bones['wing_l_1'], Y, 0.32 * flap1),
            'wing_l_2': world_rot(arm.pose.bones['wing_l_2'], Y, 0.36 * flap2),
            'wing_l_3': world_rot(arm.pose.bones['wing_l_3'], Y, 0.38 * flap3),
            'wing_r_1': world_rot(arm.pose.bones['wing_r_1'], Y, -0.32 * flap1),
            'wing_r_2': world_rot(arm.pose.bones['wing_r_2'], Y, -0.36 * flap2),
            'wing_r_3': world_rot(arm.pose.bones['wing_r_3'], Y, -0.38 * flap3),
        })
        key_loc(arm, f, 'pelvis', Vector((0, 0.06 * h * soar, 0)))
    finish_action(arm, action)


def main():
    args = parse_args()
    bpy.context.scene.render.fps = FPS
    obj = load(args.input)
    lm = landmarks(obj)
    print('LANDMARKS', {k: (tuple(round(c, 3) for c in v) if isinstance(v, Vector) else v) for k, v in lm.items() if not k.startswith('wing_')})
    arm = build_armature(lm)
    skin(obj, arm)
    anim_idle(arm, lm)
    anim_walk(arm, lm)
    anim_alert(arm, lm)
    bpy.ops.export_scene.gltf(
        filepath=args.output,
        export_format='GLB',
        export_animations=True,
        export_animation_mode='NLA_TRACKS',
        export_skins=True,
        export_def_bones=False,
    )
    print('EXPORTED', args.output, 'bones', len(arm.data.bones))


main()
