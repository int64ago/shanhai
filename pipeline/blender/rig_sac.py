"""
浑沌囊体型（sac，如帝江）自动绑骨骼 + 程序化关键帧（idle / walk / alert），导出带动画的 GLB。
无头、无面目；主体为浑圆囊体，预留四翼挂点（wing_{fl,fr,bl,br}_attach）与六足挂点（leg_{fl,fr,ml,mr,bl,br}_attach）。

输入须先经过 normalize.py。脚本会把囊体抬离地面 clearance 米，留出腹下六足的站立空间。

用法：
  Blender --background --factory-startup --python pipeline/blender/rig_sac.py -- \
      <in.glb> <out.glb> [--clearance 0.20] [--preview out.png]
"""
import argparse
import math
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

FPS = 30


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('input')
    p.add_argument('output')
    p.add_argument('--clearance', type=float, default=0.20)
    p.add_argument('--preview')
    return p.parse_args(argv)


def load(path, clearance):
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
    # 抬起囊体，给腹下六足留出站立高度
    obj.matrix_world = Matrix.Translation(Vector((0, 0, clearance)))
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    return obj


def measure(obj):
    vs = [obj.matrix_world @ v.co for v in obj.data.vertices]
    lo = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
    hi = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
    center = (lo + hi) / 2
    size = hi - lo
    return {'lo': lo, 'hi': hi, 'center': center, 'size': size}


def build_armature(m):
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
        return b

    c = m['center']
    s = m['size']
    lo, hi = m['lo'], m['hi']
    bone('root', Vector((0, 0, 0)), Vector((0, 0, 0.12)), deform=False)
    # core 控制整体弹跳、倾侧与歌舞旋动；upper 控制囊体上部的呼吸起伏
    bone('core', Vector((0, 0, c.z - s.z * 0.18)), Vector((0, 0, c.z + s.z * 0.05)), 'root')
    bone('upper', Vector((0, 0, c.z + s.z * 0.05)), Vector((0, 0, hi.z - s.z * 0.08)), 'core')

    # 四翼挂点：肩背两侧前（主翼）、后（副翼），往囊内深缩使翼根完全埋入羽毛/皮囊中
    for fb, ky, kz in (('f', -0.08, 0.18), ('b', 0.12, 0.06)):
        for side, sx in (('l', 1.0), ('r', -1.0)):
            p = Vector((sx * s.x * 0.26, c.y + ky * s.y, c.z + kz * s.z))
            bone(f'wing_{fb}{side}_attach', p, p + Vector((sx * 0.1, 0, 0.04)), 'upper', deform=False)

    # 六足挂点：囊体底部向内收拢，挂点须收在囊底内圈，避免大腿上沿露出囊壁外
    leg_z = lo.z + s.z * 0.18
    for pos_name, ky, kx in (('f', -0.16, 0.19), ('m', 0.0, 0.23), ('b', 0.16, 0.19)):
        for side, sx in (('l', 1.0), ('r', -1.0)):
            p = Vector((sx * s.x * kx, c.y + ky * s.y, leg_z))
            bone(f'leg_{pos_name}{side}_attach', p, p + Vector((0, 0, -0.1)), 'core', deform=False)

    bpy.ops.object.mode_set(mode='OBJECT')
    return arm


def skin(obj, arm):
    """按顶点到 core / upper 的距离分配权重并平滑，使囊体下半与上半在呼吸时有柔顺的体积形变。"""
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
        ws = [1.0 / max(d, 1e-3) ** 3.0 for d, _ in scored]
        total = sum(ws)
        for (_, name), w in zip(scored, ws):
            groups[name].add([v.index], w / total, 'REPLACE')

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
    bpy.ops.object.vertex_group_smooth(group_select_mode='ALL', factor=0.5, repeat=8)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode='ALL', lock_active=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    mod = obj.modifiers.new('rig', 'ARMATURE')
    mod.object = arm
    obj.parent = arm


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


def anim_idle(arm, m):
    """4 秒循环：囊体浑沌吐纳，上下柔和起伏并微微摇晃"""
    action = new_action(arm, 'idle')
    n = 4 * FPS
    h = m['size'].z
    for f in range(0, n + 1, 4):
        t = f / n * 2 * math.pi
        breath = math.sin(t * 2)
        sway = math.sin(t)
        key_pose(arm, f, {
            'core': world_rot(arm.pose.bones['core'], Y, 0.045 * sway)
                    @ world_rot(arm.pose.bones['core'], X, 0.03 * math.cos(t)),
            'upper': world_rot(arm.pose.bones['upper'], Y, 0.035 * math.cos(t))
                     @ world_rot(arm.pose.bones['upper'], Z, 0.04 * sway),
        })
        key_loc(arm, f, 'core', Vector((0, 0.018 * h * breath, 0)))
        key_loc(arm, f, 'upper', Vector((0, 0.015 * h * math.sin(t * 2 - 0.6), 0)))
    finish_action(arm, action)


def anim_walk(arm, m):
    """1 秒循环：六足三脚架步态驱动下的轻快颠动与左右摆荡"""
    action = new_action(arm, 'walk')
    n = FPS
    h = m['size'].z
    for f in range(0, n + 1, 2):
        t = f / n * 2 * math.pi
        bob = math.cos(t * 2)
        sway = math.sin(t)
        key_pose(arm, f, {
            'core': world_rot(arm.pose.bones['core'], Y, 0.06 * sway)
                    @ world_rot(arm.pose.bones['core'], Z, 0.05 * sway)
                    @ world_rot(arm.pose.bones['core'], X, -0.06 + 0.03 * bob),
            'upper': world_rot(arm.pose.bones['upper'], Y, -0.04 * sway)
                     @ world_rot(arm.pose.bones['upper'], X, 0.04 * math.sin(t * 2)),
        })
        key_loc(arm, f, 'core', Vector((0, 0.022 * h * bob, 0)))
    finish_action(arm, action)


def anim_alert(arm, m):
    """2 秒循环：「是识歌舞」——欢快击节弹跳、旋身倾侧"""
    action = new_action(arm, 'alert')
    n = 2 * FPS
    h = m['size'].z
    for f in range(0, n + 1, 2):
        t = f / n * 2 * math.pi
        hop = abs(math.sin(t * 2))
        twist = math.sin(t)
        tilt = math.cos(t * 2)
        key_pose(arm, f, {
            'core': world_rot(arm.pose.bones['core'], Z, 0.22 * twist)
                    @ world_rot(arm.pose.bones['core'], Y, 0.14 * math.sin(t * 2))
                    @ world_rot(arm.pose.bones['core'], X, 0.10 * tilt),
            'upper': world_rot(arm.pose.bones['upper'], Z, 0.15 * math.cos(t))
                     @ world_rot(arm.pose.bones['upper'], Y, 0.10 * tilt),
        })
        key_loc(arm, f, 'core', Vector((0, 0.09 * h * (hop - 0.3), 0)))
        key_loc(arm, f, 'upper', Vector((0, 0.03 * h * math.sin(t * 4), 0)))
    finish_action(arm, action)


def main():
    args = parse_args()
    bpy.context.scene.render.fps = FPS
    obj = load(args.input, args.clearance)
    m = measure(obj)
    print('SAC_BOUNDS', tuple(round(v, 3) for v in m['lo']), tuple(round(v, 3) for v in m['hi']))
    arm = build_armature(m)
    skin(obj, arm)
    anim_idle(arm, m)
    anim_walk(arm, m)
    anim_alert(arm, m)
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
