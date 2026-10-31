"""
标准化 Rodin 产物：合并网格、清理、缩放到目标尺寸、原点落地、朝向 +Z（glTF 前方）。

用法：
  Blender --background --factory-startup --python pipeline/blender/normalize.py -- \
      <in.glb> <out.glb> [--length 1.0] [--yaw 0] [--preview out.png]

--length  身体最长水平边的目标长度（米）
--yaw     额外绕竖直轴旋转的角度（度），用来纠正 AI 模型朝向
--max-texture  超过该边长的贴图先缩小（Extreme-High 的 12K 贴图会让中间文件过大）
"""
import argparse
import math
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument('input')
    p.add_argument('output')
    p.add_argument('--length', type=float, default=1.0)
    p.add_argument('--yaw', type=float, default=0.0)
    p.add_argument('--preview')
    p.add_argument('--max-texture', type=int, default=4096)
    p.add_argument('--trim-tail', action='store_true')
    return p.parse_args(argv)


def import_mesh(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        raise RuntimeError('输入里没有网格')
    bpy.ops.object.select_all(action='DESELECT')
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    # 去掉导入时的空父级，烘焙变换
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in list(bpy.context.scene.objects):
        if o is not obj:
            bpy.data.objects.remove(o)
    return obj


def cleanup(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context='VERTS')
    # 去掉体积极小的漂浮碎片（AI 网格常见）
    islands = []
    seen = set()
    for f in bm.faces:
        if f.index in seen:
            continue
        stack, island = [f], []
        seen.add(f.index)
        while stack:
            cur = stack.pop()
            island.append(cur)
            for e in cur.edges:
                for nf in e.link_faces:
                    if nf.index not in seen:
                        seen.add(nf.index)
                        stack.append(nf)
        islands.append(island)
    if len(islands) > 1:
        largest = max(len(i) for i in islands)
        tiny = [f for i in islands if len(i) < largest * 0.01 for f in i]
        bmesh.ops.delete(bm, geom=tiny, context='FACES')
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    after = len(bm.verts)
    bm.free()
    print(f'CLEANUP verts {before} -> {after}, islands {len(islands)}')


def bounds(obj):
    pts = [obj.matrix_world @ v.co for v in obj.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def normalize(obj, length, yaw, trim_tail=False):
    # Blender 内 Z 向上；glTF 导出时 +Y(Blender) → -Z(glTF)，所以 Blender 的 -Y 是 glTF 前方 +Z
    obj.matrix_world = Matrix.Rotation(math.radians(yaw), 4, 'Z') @ obj.matrix_world
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    scale_to_length(obj, length)
    if trim_tail:
        trim_hanging_tail(obj)
        scale_to_length(obj, length)
    lo, hi = bounds(obj)
    print('BBOX', tuple(round(v, 3) for v in lo), tuple(round(v, 3) for v in hi))


def scale_to_length(obj, length):
    lo, hi = bounds(obj)
    size = hi - lo
    scale = length / max(size.x, size.y)
    center = (lo + hi) / 2
    obj.matrix_world = Matrix.Scale(scale, 4) @ Matrix.Translation(Vector((-center.x, -center.y, -lo.z)))
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def smoothstep(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def trim_hanging_tail(obj):
    """去掉四足模型自带的下垂短尾（多尾神兽的尾巴由运行时单独挂接）：
    只删两后腿中缝和踝部后方明显超出后腿轮廓的尾尖，保留两侧后腿完整厚度，再把尾根推回臀部弧面。"""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    to_del = []
    for f in bm.faces:
        c = f.calc_center_median()
        if 0.14 < c.z < 0.46:
            y_max = 0.408 if c.z < 0.18 else 0.392
            if (abs(c.x) < 0.052 and c.y > 0.345) or c.y > y_max:
                to_del.append(f)
    bmesh.ops.delete(bm, geom=to_del, context='FACES')
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context='VERTS')
    for v in bm.verts:
        p = v.co
        if p.z > 0.17:
            lim = 0.388 - 0.020 * smoothstep(0.18, 0.55, p.z) - 0.025 * (1 - smoothstep(0.03, 0.09, abs(p.x)))
            if p.y > lim:
                p.y = lim + (p.y - lim) * 0.08
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()


def shrink_textures(limit):
    for img in bpy.data.images:
        w, h = img.size
        if max(w, h) > limit:
            k = limit / max(w, h)
            img.scale(int(w * k), int(h * k))
            print(f'TEXTURE {img.name} {w}x{h} -> {img.size[0]}x{img.size[1]}')


def stats(obj):
    obj.data.calc_loop_triangles()
    print('TRIS', len(obj.data.loop_triangles), 'VERTS', len(obj.data.vertices))


def render_preview(obj, path):
    lo, hi = bounds(obj)
    center = (lo + hi) / 2
    size = max(hi - lo)
    scene = bpy.context.scene
    shots = [('side', Vector((size * 2.4, 0, size * 0.5))), ('front', Vector((0, -size * 2.4, size * 0.5)))]
    sun = bpy.data.objects.new('sun', bpy.data.lights.new('sun', 'SUN'))
    sun.data.energy = 4
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))
    scene.collection.objects.link(sun)
    world = bpy.data.worlds.new('w')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = (0.75, 0.73, 0.68, 1)
    scene.world = world
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = scene.render.resolution_y = 512
    cam = bpy.data.objects.new('cam', bpy.data.cameras.new('cam'))
    scene.collection.objects.link(cam)
    scene.camera = cam
    for name, offset in shots:
        cam.location = center + offset
        cam.rotation_euler = (center - cam.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = path.replace('.png', f'_{name}.png')
        bpy.ops.render.render(write_still=True)
    for o in (sun, cam):
        bpy.data.objects.remove(o)


def main():
    args = parse_args()
    obj = import_mesh(args.input)
    obj.name = 'body'
    cleanup(obj)
    normalize(obj, args.length, args.yaw, args.trim_tail)
    stats(obj)
    shrink_textures(args.max_texture)
    if args.preview:
        render_preview(obj, args.preview)
    bpy.ops.export_scene.gltf(filepath=args.output, export_format='GLB', use_selection=False)
    print('EXPORTED', args.output)


main()
