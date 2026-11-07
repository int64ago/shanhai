"""Tianma's wingless dog rig: fold all four legs in flight, unfold to land.

Run after normalization (head towards Blender -Y, paws at z=0):
  blender --background --python pipeline/blender/rig_tianma.py -- body_norm.glb body_rig.glb

The 4.6-second alert clip matches the altitude envelope in Tianma.tsx and the
shared Quadruped special timer. Altitude lives in the runtime wrapper so an
interrupted flight can descend smoothly rather than resetting the root bone.
"""
import math
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_quadruped as rig
from rig_quadruped import FPS, X, finish_action, key_pose, new_action, world_rot

SECONDS = 4.6


def smooth(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def anim_alert(arm, lm):
    action = new_action(arm, 'alert')
    bones = arm.pose.bones
    for frame in range(round(SECONDS * FPS) + 1):
        seconds = frame / FPS
        # Lift before folding; extend the paws while still above the ground.
        folded = smooth(0.55, 1.35, seconds) * (1 - smooth(2.9, 3.75, seconds))
        pose = {}
        for leg in ('front_l', 'front_r', 'back_l', 'back_r'):
            front = leg.startswith('front')
            upper = (0.72 if front else -0.70) * folded
            lower = (-1.46 if front else 1.40) * folded
            foot = -(upper + lower) * 0.7
            for part, angle in (('upper', upper), ('lower', lower), ('foot', foot)):
                bone = bones[f'{leg}_{part}']
                pose[bone.name] = world_rot(bone, X, angle)
        pose['neck'] = world_rot(bones['neck'], X, -0.055 * folded)
        pose['head'] = world_rot(bones['head'], X, 0.025 * folded)
        pose['chest'] = world_rot(bones['chest'], X, 0.012 * folded * math.sin(seconds * 3))
        key_pose(arm, frame, pose)
    finish_action(arm, action)


base_skin = rig.skin


def skin_complete(obj, arm):
    base_skin(obj, arm)
    # The dog's skull and lower jaw are one rigid unit; shoulder folding must not
    # pull a pale throat vertex through the black face.
    head = [v.index for v in obj.data.vertices if (v.co.z > 0.82 and v.co.y < -0.04) or (v.co.z > 0.70 and v.co.y < -0.30)]
    for group in obj.vertex_groups:
        group.remove(head)
    obj.vertex_groups['head'].add(head, 1, 'REPLACE')
    print('TIANMA_SKIN rigid head vertices', len(head))
    deform = [bone for bone in arm.data.bones if bone.use_deform]
    filled = 0
    for vertex in obj.data.vertices:
        if any(group.weight > 1e-3 for group in vertex.groups):
            continue
        point = obj.matrix_world @ vertex.co
        def distance(bone):
            start = arm.matrix_world @ bone.head_local
            end = arm.matrix_world @ bone.tail_local
            axis = end - start
            t = max(0, min(1, (point - start).dot(axis) / axis.length_squared))
            return (point - start - axis * t).length_squared
        bone = min(deform, key=distance)
        obj.vertex_groups[bone.name].add([vertex.index], 1, 'REPLACE')
        filled += 1
    print('TIANMA_SKIN filled remaining unweighted vertices', filled)


rig.skin = skin_complete
rig.anim_alert = anim_alert

if __name__ == '__main__':
    rig.main()
