"""Quadruped rig for Mengji with a ground-locked crouch as its alert clip.

「是善伏」: the beast sinks low, holds its breath, then raises its head to call
and stands up. Legs use a planar two-bone solve so paws stay planted while the
body drops; the clip length matches SPECIAL_SECONDS in src/beasts/Quadruped.tsx.
"""
import math
import sys
from pathlib import Path

from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_quadruped as rig
from rig_quadruped import FPS, X, finish_action, key_loc, key_pose, new_action, world_rot

SECONDS = 4.6
DROP = 0.30  # fraction of standing height


def smooth(a, b, x):
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def plane(v):
    return Vector((v.y, v.z))


def signed_angle(a, b):
    """Rotation about +X taking a to b, with (y, z) as the plane basis."""
    return math.atan2(a.x * b.y - a.y * b.x, a.dot(b))


def solve_leg(arm, leg, drop):
    """Return world-X angles for upper/lower/foot keeping the ankle fixed."""
    upper = arm.data.bones[f'{leg}_upper']
    lower = arm.data.bones[f'{leg}_lower']
    top, knee, ankle = plane(upper.head_local), plane(upper.tail_local), plane(lower.tail_local)
    l1, l2 = (knee - top).length, (ankle - knee).length
    moved = top - Vector((0, drop))
    reach = ankle - moved
    d = min(reach.length, (l1 + l2) * 0.999)
    along = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
    height = math.sqrt(max(0.0, l1 * l1 - along * along))
    unit = reach.normalized()
    normal = Vector((-unit.y, unit.x))
    # Keep the joint on the side it already bends toward at rest.
    rest_unit = (ankle - top).normalized()
    rest_side = (knee - top).dot(Vector((-rest_unit.y, rest_unit.x)))
    side = 1 if rest_side >= 0 else -1
    if abs(rest_side) < 1e-5:
        side = -1 if leg.startswith('front') else 1
    new_knee = moved + unit * along + normal * height * side
    u_ang = signed_angle(knee - top, new_knee - moved)
    l_ang = signed_angle(ankle - knee, ankle - new_knee) - u_ang
    return u_ang, l_ang, -(u_ang + l_ang)


def anim_alert(arm, lm):
    action = new_action(arm, 'alert')
    n = round(SECONDS * FPS)
    bones = arm.pose.bones
    for f in range(0, n + 1, 2):
        s = f / FPS
        crouch = smooth(0.1, 1.0, s) * (1 - smooth(3.5, 4.4, s))
        raised = smooth(1.55, 1.95, s) * (1 - smooth(3.2, 3.8, s))
        breath = math.sin(s * 5.0) * smooth(0.9, 1.3, s) * (1 - smooth(1.5, 1.8, s))
        # The body rises slightly while calling, then fully on the way out.
        drop = lm['height'] * DROP * crouch * (1 - 0.3 * raised)
        pose = {}
        for leg in ('front_l', 'front_r', 'back_l', 'back_r'):
            u_ang, l_ang, f_ang = solve_leg(arm, leg, drop)
            for part, angle in (('upper', u_ang), ('lower', l_ang), ('foot', f_ang)):
                pb = bones[f'{leg}_{part}']
                pose[pb.name] = world_rot(pb, X, angle)
        # Positive X rotation lowers a forward-pointing bone in this head-to--Y rig.
        neck = 0.22 * crouch * (1 - raised) - 0.3 * raised + 0.012 * breath
        pose['neck'] = world_rot(bones['neck'], X, neck)
        pose['head'] = world_rot(bones['head'], X, -0.08 * crouch * (1 - raised) - 0.14 * raised)
        pose['chest'] = world_rot(bones['chest'], X, 0.012 * breath)
        key_pose(arm, f, pose)
        # The root bone points along world +Z, so its local -Y is world down.
        key_loc(arm, f, 'root', Vector((0, -drop, 0)))
    finish_action(arm, action)


rig.anim_alert = anim_alert

if __name__ == '__main__':
    rig.main()
