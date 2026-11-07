"""Six-foot Zhubieyu: dedicated sac skeleton, curved planted tripod gait.
Each actual sole is rigidly weighted, including its yaw. No quadruped template.
Compression must use gltf-transform optimize --meshopt-level medium
--resample false --simplify false --flatten false --join false, with WebP.
The default high animation filter visibly breaks the inverse foot constraints.
"""
import math
import sys
from pathlib import Path
import bpy
from mathutils import Vector
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_quadruped as animation
from rig_ershu import rigid, smooth
from rig_yingzhao import contact
from assemble_zhubieyu import FEET, HIPS, KNEES, ROWS

FPS = 30
RADIUS = 1.0
SPEED = .10
WALK_SECONDS = 2.2
DUTY = .68
OFFSETS = {f'{row}_{label}': ((i + (0 if side == 1 else 1)) % 2) * .5 for i, (row, _) in enumerate(ROWS) for side, label in [(1, 'l'), (-1, 'r')]}


def armature():
    arm = bpy.data.objects.new('zhubieyu_rig', bpy.data.armatures.new('zhubieyu_sac_skeleton'))
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    arm.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    def bone(name, head, tail, parent=None):
        b = arm.data.edit_bones.new(name)
        b.head, b.tail = head, tail
        if parent:
            b.parent = arm.data.edit_bones[parent]
    bone('root', (0, 0, 0), (0, 0, .10))
    bone('mantle', (0, 0, .29), (0, 0, .69), 'root')
    for key, foot in FEET.items():
        bone(key + '_upper', HIPS[key], KNEES[key], 'root')
        bone(key + '_lower', KNEES[key], foot, key + '_upper')
        bone(key + '_foot', foot, foot + Vector((0, -.12, 0)), key + '_lower')
    pearl = bpy.data.objects['zhubieyu_pearl']
    center = sum((v.co for v in pearl.data.vertices), Vector()) / len(pearl.data.vertices)
    bone('pearl', center, center + Vector((0, 0, .12)), 'mantle')
    bpy.ops.object.mode_set(mode='OBJECT')
    return arm


def skin_leg(obj, arm, key):
    groups = {name: obj.vertex_groups.new(name=key + '_' + name) for name in ['upper', 'lower', 'foot']}
    for v in obj.data.vertices:
        # Entire sole and toes are rigid. The upper/ankle blend retains the
        # naturally sculpted HIGH skin rather than separating at joints.
        z = v.co.z
        lower = smooth(.075, .145, z)
        upper = smooth(.30, .46, z)
        weights = {'foot': 1 - lower, 'lower': lower * (1 - upper), 'upper': lower * upper}
        for name, value in weights.items():
            if value > 1e-8:
                groups[name].add([v.index], value, 'REPLACE')
    mod = obj.modifiers.new('three-bone continuous natural limb', 'ARMATURE')
    mod.object = arm
    obj.parent = arm


def animate(arm, name, seconds):
    act = animation.new_action(arm, name)
    n = round(seconds * FPS)
    for frame in range(n + 1):
        t, phase = frame / FPS, frame / n
        display = smooth(.15, 1.0, t) * (1 - smooth(3.1, 4.6, t)) if name == 'special' else 0
        breath = math.sin(math.tau * phase)
        delta = Vector((0, 0, -.014 if name == 'walk' else -.008 * display + .002 * breath))
        animation.key_loc(arm, frame, 'root', arm.data.bones['root'].matrix_local.to_3x3().inverted() @ delta)
        mantle = arm.pose.bones['mantle']
        mantle.scale = (1 + .006 * breath + .015 * display, 1 - .003 * breath, 1 + .009 * breath + .025 * display)
        mantle.keyframe_insert('scale', frame=frame)
        pearl = arm.pose.bones['pearl']
        pearl.scale = Vector((1, 1, 1)) * (1 + display * .10)
        pearl.keyframe_insert('scale', frame=frame)
        animation.key_loc(arm, frame, 'pearl', Vector((0, .018 * display, 0)))
        bpy.context.view_layer.update()
        for leg, offset in OFFSETS.items():
            lateral = backward = lift = yaw = 0
            if name == 'walk':
                p = (phase + offset) % 1
                if p < DUTY:
                    relative = seconds * (p - DUTY / 2)
                else:
                    u = (p - DUTY) / (1 - DUTY)
                    relative = seconds * DUTY * (.5 - u * u * (3 - 2 * u))
                    lift = .045 * math.sin(math.pi * u)
                yaw = -SPEED / RADIUS * relative
                ankle = FEET[leg]
                x, y = ankle.x - RADIUS, ankle.y
                lateral = RADIUS + math.cos(yaw) * x - math.sin(yaw) * y - ankle.x
                backward = math.sin(yaw) * x + math.cos(yaw) * y - ankle.y
            contact(arm, leg, frame, delta, lateral, backward, lift, yaw)
    animation.finish_action(arm, act)
    for fc in animation.action_fcurves(act):
        for key in fc.keyframe_points:
            key.interpolation = 'LINEAR'


def main():
    source, output = sys.argv[sys.argv.index('--') + 1:]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=source)
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    for obj in meshes:
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.ops.object.select_all(action='DESELECT')
    arm = armature()
    for obj in meshes:
        if obj.name.startswith('zhubieyu_leg_'):
            skin_leg(obj, arm, obj.name.removeprefix('zhubieyu_leg_'))
        else:
            rigid(obj, arm, 'pearl' if obj.name == 'zhubieyu_pearl' else 'mantle')
    bpy.context.scene.render.fps = FPS
    for name, seconds in [('idle', 4), ('walk', WALK_SECONDS), ('special', 4.8)]:
        animate(arm, name, seconds)
    bpy.context.scene.frame_set(0)
    bpy.ops.export_scene.gltf(filepath=output, export_format='GLB', export_animations=True, export_animation_mode='NLA_TRACKS', export_skins=True, export_def_bones=False)
    assert all(animation.unweighted_count(obj) == 0 for obj in meshes)
    print('ZHUBIEYU_RIG', len(arm.data.bones), 'bones; six planted feet; no unweighted vertices')


if __name__ == '__main__':
    main()
