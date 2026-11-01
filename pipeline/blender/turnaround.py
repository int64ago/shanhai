"""
从已有模型渲染多视图，作为 Rodin 图生 3D 的输入（方案 4：三视图 → 图生 3D）。
渲染前先做两处造型修正：
  - 抬高后半身、拉直后腿（AI 文生 3D 的四足常是后腿半蹲）
  - 把身体自带的短尾压进臀部（尾巴在运行时另外挂）

输入须先经过 normalize.py：头朝 -Y，脚底 z=0。

用法：
  Blender --background --factory-startup --python pipeline/blender/turnaround.py -- \
      <in.glb> <out_dir> [--raise auto|<米>] [--keep-tail] [--size 1024] [--view 34|side|front|back]

输出 <out_dir>/view_{34,side,front,back}.png，第一张（3/4 视角）用于材质生成。
"""
import argparse
import math
import sys

import bpy
from mathutils import Matrix, Vector


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('input')
    p.add_argument('out_dir')
    p.add_argument('--raise', dest='raise_', default='auto')
    p.add_argument('--keep-tail', action='store_true')
    p.add_argument('--size', type=int, default=1024)
    p.add_argument('--view', choices=['34', 'side', 'front', 'back'])
    return p.parse_args(argv)


def load(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if len(meshes) != 1:
        raise RuntimeError(f'期望 1 个网格，实际 {len(meshes)}；请先跑 normalize.py')
    obj = meshes[0]
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in list(bpy.context.scene.objects):
        if o is not obj:
            bpy.data.objects.remove(o)
    return obj


def smoothstep(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def measure(vs):
    height = max(v.z for v in vs)
    low = [v for v in vs if v.z < height * 0.1]
    mid = (min(v.y for v in low) + max(v.y for v in low)) / 2
    front_y = sum(v.y for v in low if v.y < mid) / max(1, sum(1 for v in low if v.y < mid))
    back_y = sum(v.y for v in low if v.y >= mid) / max(1, sum(1 for v in low if v.y >= mid))
    length = max(v.y for v in vs) - min(v.y for v in vs)

    def top_at(y):
        sl = [v.z for v in vs if abs(v.y - y) < length * 0.04]
        return max(sl)

    def torso_mid(y):
        sl = [v.z for v in vs if abs(v.y - y) < length * 0.04 and v.z > height * 0.3]
        return (max(sl) + min(sl)) / 2

    return {
        'height': height,
        'length': length,
        'front_y': front_y,
        'back_y': back_y,
        'chest_top': top_at(front_y),
        'rump_top': top_at(back_y),
        'hip_z': torso_mid(back_y),
    }


def fix_pose(obj, raise_, keep_tail):
    me = obj.data
    vs = [v.co.copy() for v in me.vertices]
    m = measure(vs)
    if raise_ == 'auto':
        dz = max(0.0, min(0.12, (m['chest_top'] - m['rump_top']) * 0.85))
    else:
        dz = float(raise_)
    print(f"MEASURE front_y={m['front_y']:.3f} back_y={m['back_y']:.3f} chest_top={m['chest_top']:.3f} "
          f"rump_top={m['rump_top']:.3f} hip_z={m['hip_z']:.3f} -> raise {dz:.3f}")

    y_cut = m['back_y'] + m['length'] * 0.09
    for v in me.vertices:
        p = v.co
        # 后半身抬高：髋以下按比例拉伸（脚仍贴地），髋以上整体平移；沿身体前后平滑过渡
        w = smoothstep(m['front_y'], m['back_y'], p.y) * dz
        if p.z < m['hip_z']:
            p.z *= 1 + w / m['hip_z']
        else:
            p.z += w
        # 短尾压进臀部
        if not keep_tail and p.y > y_cut:
            p.y = y_cut + (p.y - y_cut) * 0.18
    me.update()


def setup_render(size):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.view_settings.view_transform = 'Standard'
    world = bpy.data.worlds.new('w')
    world.use_nodes = True
    bg = world.node_tree.nodes['Background']
    bg.inputs[0].default_value = (0.92, 0.92, 0.92, 1)
    bg.inputs[1].default_value = 1.0
    scene.world = world
    # 均匀环境光 + 一盏很弱的顶光，只给一点体积感，不要明显投影（会被烘进贴图）
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
    sun.data.energy = 1.2
    sun.data.angle = math.radians(30)
    sun.rotation_euler = (math.radians(25), 0, math.radians(20))
    scene.collection.objects.link(sun)
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
    cam.data.type = 'ORTHO'
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


def render_views(obj, cam, out_dir, only_view=None):
    pts = [v.co for v in obj.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    center = (lo + hi) / 2
    extent = max(hi - lo)
    cam.data.ortho_scale = extent * 1.15
    d = extent * 3
    # 头朝 -Y：正面相机在 -Y，侧面在 +X
    views = [
        ('34', Vector((d * 0.62, -d * 0.72, d * 0.3))),
        ('side', Vector((d, 0, 0))),
        ('front', Vector((0, -d, 0))),
        ('back', Vector((0, d, 0))),
    ]
    for name, offset in views:
        if only_view and name != only_view:
            continue
        # Separate cameras keep background EEVEE from reusing an evaluated
        # transform from the previous view on Blender 5.2/macOS.
        shot_cam = cam.copy()
        shot_cam.data = cam.data.copy()
        bpy.context.scene.collection.objects.link(shot_cam)
        location = center + offset
        rotation = (center - location).to_track_quat('-Z', 'Y')
        shot_cam.matrix_world = Matrix.LocRotScale(location, rotation, Vector((1, 1, 1)))
        bpy.context.scene.camera = shot_cam
        bpy.context.view_layer.update()
        bpy.context.scene.render.filepath = f'{out_dir}/view_{name}.png'
        bpy.ops.render.render(write_still=True)
        print('VIEW', name)


def main():
    args = parse_args()
    obj = load(args.input)
    fix_pose(obj, args.raise_, args.keep_tail)
    cam = setup_render(args.size)
    render_views(obj, cam, args.out_dir, only_view=args.view)


if __name__ == '__main__':
    main()
