"""
四足自动绑骨骼 + 程序化关键帧（idle / walk / alert），导出带动画的 GLB。

输入须先经过 normalize.py：身体沿 Blender Y 轴，头朝 -Y（glTF +Z），脚底 z=0。

用法：
  Blender --background --factory-startup --python pipeline/blender/rig_quadruped.py -- \
      <in.glb> <out.glb> [--preview out.png]

骨骼命名约定（运行时依赖）：
  root / hips / spine1 / spine2 / chest / neck / head / tail_attach
  {front,back}_{l,r}_{upper,lower,foot}
"""
import argparse
import math
import sys

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

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
    return obj


# ---------------------------------------------------------------- 关键点检测

def landmarks(obj):
    vs = [obj.matrix_world @ v.co for v in obj.data.vertices]
    ys = [v.y for v in vs]
    zs = [v.z for v in vs]
    y0, y1 = min(ys), max(ys)  # y0 = 鼻尖（前），y1 = 臀/尾桩（后）
    height = max(zs)
    length = y1 - y0

    def band(lo, hi):
        return [v for v in vs if y0 + lo * length <= v.y <= y0 + hi * length]

    # 腿：贴地的顶点按前后、左右分四簇
    low = [v for v in vs if v.z < height * 0.12]
    mid_y = (min(v.y for v in low) + max(v.y for v in low)) / 2
    legs = {}
    for fb, cond_y in (('front', lambda v: v.y < mid_y), ('back', lambda v: v.y >= mid_y)):
        for side, cond_x in (('l', lambda v: v.x > 0), ('r', lambda v: v.x <= 0)):
            pts = [v for v in low if cond_y(v) and cond_x(v)]
            if not pts:
                raise RuntimeError(f'找不到 {fb}_{side} 腿的落地点')
            c = sum(pts, Vector()) / len(pts)
            legs[f'{fb}_{side}'] = Vector((c.x, c.y, 0.0))

    front_y = (legs['front_l'].y + legs['front_r'].y) / 2
    back_y = (legs['back_l'].y + legs['back_r'].y) / 2

    def torso_center(y):
        sl = [v for v in vs if abs(v.y - y) < length * 0.04 and v.z > height * 0.3]
        top = max(v.z for v in sl)
        # 躯干下沿：该切片内腿以上最低的连续体，用高度 40% 以上的最小 z 近似
        belly = min(v.z for v in sl if v.z > height * 0.35)
        return (top + belly) / 2, top, belly

    chest_z, chest_top, _ = torso_center(front_y)
    hips_z, hips_top, _ = torso_center(back_y)

    # 头：最前 18% 的切片
    head_pts = band(0.0, 0.18)
    head_c = sum(head_pts, Vector()) / len(head_pts)
    snout = min(vs, key=lambda v: v.y)
    # 尾根取骶骨高度（髋中心偏上）的中轴后缘，再略微内缩，让外挂尾巴自然嵌进臀部毛发
    sacrum_z = hips_z + (hips_top - hips_z) * 0.25
    rear_pt = max((v for v in vs if abs(v.z - sacrum_z) < height * 0.06 and abs(v.x) < length * 0.04), key=lambda v: v.y)
    rear = Vector((0, rear_pt.y - length * 0.025, sacrum_z))

    return {
        'height': height,
        'length': length,
        'legs': legs,
        'front_y': front_y,
        'back_y': back_y,
        'chest': Vector((0, front_y, chest_z)),
        'chest_top': chest_top,
        'hips': Vector((0, back_y, hips_z)),
        'head': Vector((0, head_c.y, head_c.z)),
        'snout': Vector((0, snout.y, snout.z)),
        'rear': Vector((0, rear.y, rear.z)),
    }


# ---------------------------------------------------------------- 骨架

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
            b.use_connect = (parent and (eb[parent].tail - head).length < 1e-4)
        return b

    h = lm['height']
    hips, chest = lm['hips'], lm['chest']
    bone('root', Vector((0, 0, 0)), Vector((0, 0, h * 0.15)), deform=False)
    s1 = hips.lerp(chest, 1 / 3)
    s2 = hips.lerp(chest, 2 / 3)
    bone('hips', hips + Vector((0, 0.0, 0)), s1, 'root')
    # hips 指向前方；spine 链连接到胸
    bone('spine1', s1, s2, 'hips')
    bone('spine2', s2, chest, 'spine1')
    neck_base = chest + Vector((0, 0, (lm['chest_top'] - chest.z) * 0.5))
    bone('chest', chest, neck_base, 'spine2')
    head_base = lm['head'] + Vector((0, (lm['head'].y - lm['snout'].y) * 0.6, 0))
    bone('neck', neck_base, head_base, 'chest')
    bone('head', head_base, lm['snout'], 'neck')
    tail_dir = (lm['rear'] - hips).normalized()
    bone('tail_attach', lm['rear'], lm['rear'] + tail_dir * h * 0.15, 'hips', deform=False)

    for name, foot in lm['legs'].items():
        is_front = name.startswith('front')
        top = Vector((foot.x * 0.85, foot.y, (chest if is_front else hips).z))
        knee = Vector((foot.x, foot.y + (0.02 if is_front else -0.04) * lm['length'], h * 0.32))
        ankle = Vector((foot.x, foot.y, h * 0.07))
        toe = Vector((foot.x, foot.y - 0.06 * lm['length'], 0.0))
        parent = 'spine2' if is_front else 'hips'
        bone(f'{name}_upper', top, knee, parent)
        bone(f'{name}_lower', knee, ankle, f'{name}_upper')
        bone(f'{name}_foot', ankle, toe, f'{name}_lower')

    bpy.ops.object.mode_set(mode='OBJECT')
    return arm


# ---------------------------------------------------------------- 蒙皮

def unweighted_count(obj):
    groups = {g.index for g in obj.vertex_groups}
    return sum(1 for v in obj.data.vertices if not any(g.group in groups and g.weight > 1e-3 for g in v.groups))


def skin(obj, arm):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    missing = unweighted_count(obj)
    print(f'SKIN heat weights, unweighted verts: {missing}/{len(obj.data.vertices)}')
    if missing > len(obj.data.vertices) * 0.01:
        print('SKIN fallback: voxel proxy + data transfer')
        skin_via_proxy(obj, arm)
        missing = unweighted_count(obj)
        print(f'SKIN proxy done, unweighted verts: {missing}')
    if missing > len(obj.data.vertices) * 0.01:
        print('SKIN fallback: bone-distance weights + smoothing')
        skin_by_distance(obj, arm)
        print(f'SKIN distance done, unweighted verts: {unweighted_count(obj)}')
    normalize_weights(obj)


def skin_by_distance(obj, arm, falloff=5.0, keep=3):
    """最后的兜底：按顶点到骨骼线段的距离取权重（反距离幂），再沿网格边平滑。不依赖网格质量，不会失败。"""
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
            t = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
            d = (a + ab * t - p).length
            scored.append((d, name))
        scored.sort()
        nearest = scored[:keep]
        ws = [1.0 / max(d, 1e-4) ** falloff for d, _ in nearest]
        total = sum(ws)
        for (d, name), w in zip(nearest, ws):
            if w / total > 0.01:
                groups[name].add([v.index], w / total, 'REPLACE')
    # 平滑关节过渡，避免肩、胯处硬折
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
    bpy.ops.object.vertex_group_smooth(group_select_mode='ALL', factor=0.5, repeat=6)
    bpy.ops.object.mode_set(mode='OBJECT')
    # 骨架修改器（heat 失败时 parent_set 可能已加过）
    if not any(m.type == 'ARMATURE' for m in obj.modifiers):
        mod = obj.modifiers.new('rig', 'ARMATURE')
        mod.object = arm
    obj.parent = arm


def skin_via_proxy(obj, arm):
    """AI 网格常因非流形/自交导致热扩散权重失败：在水密体素代理上求权重，再传回原网格。"""
    proxy = obj.copy()
    proxy.data = obj.data.copy()
    proxy.modifiers.clear()
    proxy.vertex_groups.clear()
    proxy.parent = None
    bpy.context.scene.collection.objects.link(proxy)
    mod = proxy.modifiers.new('voxel', 'REMESH')
    mod.mode = 'VOXEL'
    mod.voxel_size = obj.dimensions.length * 0.006
    bpy.context.view_layer.objects.active = proxy
    bpy.ops.object.modifier_apply(modifier='voxel')

    bpy.ops.object.select_all(action='DESELECT')
    proxy.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    print(f'SKIN proxy verts {len(proxy.data.vertices)}, unweighted {unweighted_count(proxy)}')

    obj.vertex_groups.clear()
    for g in proxy.vertex_groups:
        obj.vertex_groups.new(name=g.name)
    dt = obj.modifiers.new('weights', 'DATA_TRANSFER')
    dt.object = proxy
    dt.use_vert_data = True
    dt.data_types_verts = {'VGROUP_WEIGHTS'}
    dt.vert_mapping = 'POLYINTERP_NEAREST'
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.datalayout_transfer(modifier='weights')
    # 让 Data Transfer 排在 Armature 前面再应用
    bpy.ops.object.modifier_move_to_index(modifier='weights', index=0)
    bpy.ops.object.modifier_apply(modifier='weights')
    bpy.data.objects.remove(proxy)


def normalize_weights(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
    bpy.ops.object.vertex_group_limit_total(group_select_mode='ALL', limit=4)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode='ALL', lock_active=False)
    bpy.ops.object.mode_set(mode='OBJECT')


# ---------------------------------------------------------------- 动画

def world_rot(pb, axis, angle):
    """把世界空间（骨架空间）的旋转轴换到骨骼本地空间，返回本地四元数"""
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


def action_fcurves(action):
    # Blender 4.4+ 的分层 Action：fcurve 在 layers → strips → channelbags 里
    if hasattr(action, 'layers') and action.layers:
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    yield from bag.fcurves
    else:
        yield from action.fcurves


X = (1, 0, 0)  # 骨架空间 X：绕它转 = 抬头/低头、腿前后摆
Z = (0, 0, 1)  # 绕 Z：左右转头
Y = (0, 1, 0)  # 绕 Y：侧倾


def anim_idle(arm, lm):
    """4 秒循环：呼吸起伏 + 头部缓慢环顾"""
    action = new_action(arm, 'idle')
    n = 4 * FPS
    for f in range(0, n + 1, 6):
        t = f / n * 2 * math.pi
        breath = math.sin(t * 2)
        key_pose(arm, f, {
            'spine1': world_rot(arm.pose.bones['spine1'], X, 0.012 * breath),
            'chest': world_rot(arm.pose.bones['chest'], X, -0.02 * breath),
            'neck': world_rot(arm.pose.bones['neck'], Z, 0.12 * math.sin(t)) @ world_rot(arm.pose.bones['neck'], X, 0.03 * math.sin(t * 2 + 1)),
            'head': world_rot(arm.pose.bones['head'], Y, 0.05 * math.sin(t + 0.6)),
        })
        key_loc(arm, f, 'hips', Vector((0, 0.003 * lm['height'] * breath, 0)))
    finish_action(arm, action)


def leg_cycle(p, duty=0.6):
    """
    单腿步态：p ∈ [0,1)。前 duty 段着地（脚相对身体匀速后移），其余为摆动（抬起前送）。
    返回 swing ∈ [-1,1]（-1 = 最靠后，1 = 最靠前）和 lift ∈ [0,1]。
    匀速后移是为了让着地的脚和地面不打滑；之前用正弦摆动，脚在地上来回蹭。
    """
    if p < duty:
        return 1 - 2 * (p / duty), 0.0
    q = (p - duty) / (1 - duty)
    s = q * q * (3 - 2 * q)
    return -1 + 2 * s, math.sin(q * math.pi)


def anim_walk(arm, lm):
    """1 秒一个步态周期的慢步（四拍：左后 → 左前 → 右后 → 右前），比对角小跑更符合狐狸在“行”时的姿态"""
    action = new_action(arm, 'walk')
    n = FPS
    phase = {'back_l': 0.0, 'front_l': 0.25, 'back_r': 0.5, 'front_r': 0.75}
    for f in range(0, n + 1, 1):
        t = f / n
        pose = {}
        for leg, ph in phase.items():
            swing, lift = leg_cycle((t + ph) % 1.0)
            upper = arm.pose.bones[f'{leg}_upper']
            lower = arm.pose.bones[f'{leg}_lower']
            foot = arm.pose.bones[f'{leg}_foot']
            front = leg.startswith('front')
            # 绕 X 负转 = 腿向前摆（头朝 -Y），正转 = 向后蹬
            u_ang = -(0.24 if front else 0.22) * swing
            # 抬腿时温和屈膝/折腕，幅度不宜过大以免后腿小腿缩成细棍
            l_ang = (0.38 if front else -0.26) * lift
            # 脚掌抵消上两节的旋转以保持平踩地面，抬起时趾尖自然微垂（正值朝下）
            f_ang = -(u_ang + l_ang) + 0.15 * lift
            pose[upper.name] = world_rot(upper, X, u_ang)
            pose[lower.name] = world_rot(lower, X, l_ang)
            pose[foot.name] = world_rot(foot, X, f_ang)
        # 身体：每步一次轻微起伏，脊柱随着地腿左右扭，头颈反向稳定
        bob = math.cos(t * 4 * math.pi)
        sway = math.sin(t * 2 * math.pi)
        pose['spine1'] = world_rot(arm.pose.bones['spine1'], Z, 0.04 * sway)
        pose['spine2'] = world_rot(arm.pose.bones['spine2'], Z, -0.03 * sway)
        pose['neck'] = world_rot(arm.pose.bones['neck'], X, 0.03 * bob) @ world_rot(arm.pose.bones['neck'], Z, -0.02 * sway)
        key_pose(arm, f, pose)
        key_loc(arm, f, 'hips', Vector((0, 0.006 * lm['height'] * bob, 0)))
    finish_action(arm, action)


def anim_alert(arm, lm):
    """2 秒循环：警觉——昂首前倾、压低前身，头部快速小幅扫视"""
    action = new_action(arm, 'alert')
    n = 2 * FPS
    for f in range(0, n + 1, 3):
        t = f / n * 2 * math.pi
        key_pose(arm, f, {
            'spine2': world_rot(arm.pose.bones['spine2'], X, 0.06),
            'chest': world_rot(arm.pose.bones['chest'], X, -0.18),
            'neck': world_rot(arm.pose.bones['neck'], X, -0.22) @ world_rot(arm.pose.bones['neck'], Z, 0.25 * math.sin(t)),
            'head': world_rot(arm.pose.bones['head'], X, 0.15),
            'front_l_upper': world_rot(arm.pose.bones['front_l_upper'], X, -0.08),
            'front_r_upper': world_rot(arm.pose.bones['front_r_upper'], X, -0.08),
        })
    finish_action(arm, action)


# ---------------------------------------------------------------- 预览与导出

def render_preview(obj, arm, path, lm):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = scene.render.resolution_y = 512
    world = bpy.data.worlds.new('w')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (0.75, 0.73, 0.68, 1)
    scene.world = world
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
    sun.data.energy = 4
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))
    scene.collection.objects.link(sun)
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
    scene.collection.objects.link(cam)
    scene.camera = cam
    size = lm['length']
    center = Vector((0, (lm['snout'].y + lm['rear'].y) / 2, lm['height'] / 2))
    cam.location = center + Vector((size * 2.2, size * 0.4, size * 0.4))
    cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()

    for track in arm.animation_data.nla_tracks:
        action = track.strips[0].action
        arm.animation_data.action = action
        frames = int(action.frame_range[1])
        for i, f in enumerate((0, frames // 4, frames // 2)):
            scene.frame_set(f)
            scene.render.filepath = path.replace('.png', f'_{action.name}_{i}.png')
            bpy.ops.render.render(write_still=True)
    arm.animation_data.action = None
    scene.frame_set(0)
    bpy.data.objects.remove(sun)
    bpy.data.objects.remove(cam)


def main():
    args = parse_args()
    obj = load(args.input)
    bpy.context.scene.render.fps = FPS
    lm = landmarks(obj)
    print('LANDMARKS', {k: (tuple(round(c, 3) for c in v) if isinstance(v, Vector) else v) for k, v in lm.items() if k != 'legs'})
    print('LEGS', {k: tuple(round(c, 3) for c in v) for k, v in lm['legs'].items()})
    arm = build_armature(lm)
    skin(obj, arm)
    anim_idle(arm, lm)
    anim_walk(arm, lm)
    anim_alert(arm, lm)
    if args.preview:
        render_preview(obj, arm, args.preview, lm)
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
