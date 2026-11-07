"""Zouwu's measured paw-locked gait and gathering/springing display.

The walk covers 0.18 units/sec at runtime. Its 1.6s four-beat cycle has a
0.65 stance duty, so each planted ankle travels backwards exactly 0.1872.
A planar two-link solve preserves ankle height and cancels paw rotation.
The alert is a gentle gathering of the limbs then a short airborne bound,
an artistic interpretation of 乘之日行千里, not a claim of recorded flight.
"""
import math
import sys
from pathlib import Path
from mathutils import Vector

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rig_quadruped as rig
from rig_quadruped import FPS, X, finish_action, key_loc, key_pose, new_action, world_rot


def smooth(a, b, x):
    t = max(0, min(1, (x-a)/(b-a)))
    return t*t*(3-2*t)


def solve(arm, leg, drop, stride=0, lift=0):
    upper = arm.data.bones[f'{leg}_upper']
    lower = arm.data.bones[f'{leg}_lower']
    top = Vector((upper.head_local.y, upper.head_local.z-drop))
    knee = Vector((upper.tail_local.y, upper.tail_local.z-drop))
    ankle = Vector((lower.tail_local.y+stride, lower.tail_local.z+lift))
    rest_u = Vector((upper.tail_local.y-upper.head_local.y, upper.tail_local.z-upper.head_local.z))
    rest_l = Vector((lower.tail_local.y-lower.head_local.y, lower.tail_local.z-lower.head_local.z))
    reach = ankle-top
    l1, l2 = rest_u.length, rest_l.length
    d = min(reach.length, (l1+l2)*.9999)
    along = (l1*l1-l2*l2+d*d)/(2*d)
    h = math.sqrt(max(0, l1*l1-along*along))
    unit = reach.normalized()
    normal = Vector((-unit.y, unit.x))
    sign = -1 if leg.startswith('front') else 1
    joint = top+unit*along+normal*h*sign
    def angle(a, b):
        return math.atan2(a.x*b.y-a.y*b.x, a.dot(b))
    u = angle(rest_u, joint-top)
    l = angle(rest_l, ankle-joint)-u
    return u, l, -u-l


def legs_pose(arm, drop, targets=None):
    pose = {}
    for leg in ('front_l', 'front_r', 'back_l', 'back_r'):
        stride, lift = targets.get(leg, (0, 0)) if targets else (0, 0)
        for part, a in zip(('upper', 'lower', 'foot'), solve(arm, leg, drop, stride, lift)):
            pb = arm.pose.bones[f'{leg}_{part}']
            pose[pb.name] = world_rot(pb, X, a)
    return pose


def idle(arm, lm):
    action = new_action(arm, 'idle')
    for f in range(0, 4*FPS+1, 2):
        t = f/(4*FPS)*math.tau
        drop = .018+.003*math.sin(t)
        pose = legs_pose(arm, drop)
        pose['neck'] = world_rot(arm.pose.bones['neck'], (0, 0, 1), .045*math.sin(t))
        pose['head'] = world_rot(arm.pose.bones['head'], X, .018*math.sin(t))
        key_pose(arm, f, pose)
        key_loc(arm, f, 'root', Vector((0, -drop, 0)))
    finish_action(arm, action)


def walk(arm, lm):
    action = new_action(arm, 'walk')
    seconds, duty = 1.6, .65
    distance = .18*seconds*duty
    phases = {'back_l': 0, 'front_l': .25, 'back_r': .5, 'front_r': .75}
    n = round(seconds*FPS)
    for f in range(n+1):
        targets = {}
        for leg, ph in phases.items():
            p = (f/n+ph)%1
            swing, lift = rig.leg_cycle(p, duty)
            targets[leg] = (-distance/2*swing, .055*lift)
        drop = .035
        pose = legs_pose(arm, drop, targets)
        pose['neck'] = world_rot(arm.pose.bones['neck'], X, .016*math.cos(f/n*math.tau*2))
        key_pose(arm, f, pose)
        key_loc(arm, f, 'root', Vector((0, -drop, 0)))
    finish_action(arm, action)


def alert(arm, lm):
    action = new_action(arm, 'alert')
    n = round(4.6*FPS)
    for f in range(n+1):
        s = f/FPS
        crouch = smooth(.2, 1.2, s)*(1-smooth(1.6, 1.9, s))
        land = smooth(2.35, 2.55, s)*(1-smooth(2.55, 3.2, s))
        air = smooth(1.75, 1.95, s)*(1-smooth(2.15, 2.45, s))
        drop = .018+.08*crouch+.055*land
        # While airborne the paws tuck with the root; contact returns to the
        # exact standing ankle height at landing, with no static foot sliding.
        targets = {leg: ((-.025 if leg.startswith('front') else .025)*air, .075*air)
                   for leg in ('front_l', 'front_r', 'back_l', 'back_r')}
        pose = legs_pose(arm, drop, targets)
        pose['neck'] = world_rot(arm.pose.bones['neck'], X, .13*crouch-.10*air)
        pose['head'] = world_rot(arm.pose.bones['head'], X, -.08*crouch)
        key_pose(arm, f, pose)
        key_loc(arm, f, 'root', Vector((0, -drop+.16*air, 0)))
    finish_action(arm, action)


base_skin = rig.skin


def skin_with_paws(obj, arm):
    base_skin(obj, arm)
    lm = rig.landmarks(obj)
    # Automatic heat weights blend some sole vertices into the moving lower
    # leg. Keep soles rigid to the counter-rotated foot, fading up the ankle.
    for vertex in obj.data.vertices:
        if vertex.co.z >= .14:
            continue
        leg = min(lm['legs'], key=lambda n: (Vector((vertex.co.x, vertex.co.y, 0))-lm['legs'][n]).length_squared)
        foot = obj.vertex_groups[f'{leg}_foot']
        w = 1-smooth(.08, .14, vertex.co.z)
        old = {g.group: g.weight for g in vertex.groups}
        for index, weight in old.items():
            obj.vertex_groups[index].add([vertex.index], weight*(1-w), 'REPLACE')
        foot.add([vertex.index], old.get(foot.index, 0)*(1-w)+w, 'REPLACE')
    rig.normalize_weights(obj)
    print('SKIN zouwu: rigid soles with smooth ankle transition')


rig.skin = skin_with_paws
rig.anim_idle = idle
rig.anim_walk = walk
rig.anim_alert = alert
if __name__ == '__main__':
    rig.main()
