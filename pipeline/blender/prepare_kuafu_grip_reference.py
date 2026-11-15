"""Curl the five-digit native hand into a grip for a reviewed High reference.

Authored deformation only. Does not claim that the Medium source had a closed grip.
Blender --background --factory-startup --disable-autoexec --python-exit-code 1
  --python pipeline/blender/prepare_kuafu_grip_reference.py -- <input.glb> <new-output.glb>
"""
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


def smooth(low, high, value):
    t = max(0., min(1., (value-low)/(high-low)))
    return t*t*(3-2*t)


def main():
    source, target = map(Path, sys.argv[sys.argv.index('--')+1:])
    if target.exists():
        raise ValueError('Use a new candidate output')
    target.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source.resolve()))
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    points = [o.matrix_world @ v.co for o in meshes for v in o.data.vertices]
    low = Vector([min(p[k] for p in points) for k in range(3)])
    high = Vector([max(p[k] for p in points) for k in range(3)])
    scale = 1/(high-low).z
    normalizer = Matrix.Translation(Vector((-(high.x+low.x)*.5*scale, -(high.y+low.y)*.5*scale, -low.z*scale))) @ Matrix.Scale(scale, 4)
    for obj in meshes:
        transform = normalizer @ obj.matrix_world
        for vertex in obj.data.vertices:
            p = transform @ vertex.co
            original = p.copy()
            # Four fingers stay distinct. Bend their longitudinal centers around
            # a shared transverse gripping axis instead of shrinking their tips.
            finger_weight = smooth(.56, .66, original.z) * smooth(-.17, -.10, original.x)
            if finger_weight:
                base = .625
                distance = max(0., original.z-base)
                radius = .132
                theta = distance/radius
                center_y = -.005
                cross = original.y-center_y
                bent = original.copy()
                bent.y = center_y-radius*(1-math.cos(theta))+cross*math.cos(theta)
                bent.z = base+radius*math.sin(theta)+cross*math.sin(theta)
                p = p.lerp(bent, finger_weight)
            # Oppose the thumb across the oval opening. A smooth web blend keeps
            # the palm/wrist continuous and leaves the four fingers untouched.
            thumb_weight = (1-smooth(-.17, -.11, original.x))*smooth(.38, .53, original.z)
            if thumb_weight:
                root = Vector((-.125, .005, .48))
                opposed = root + Matrix.Rotation(math.radians(92), 3, 'Y') @ (original-root)
                opposed.y -= .12 * smooth(.42, .70, original.z)
                p = p.lerp(opposed, thumb_weight)
            if not all(math.isfinite(c) for c in p):
                raise ValueError('Nonfinite grip deformation')
            vertex.co = p
        obj.matrix_world = Matrix.Identity(4)
        obj.parent = None
        obj.data.update()
        # Blender derives smooth normals on the edited guide, not at runtime.
        if obj.data.has_custom_normals:
            obj.data.normals_split_custom_set([(0., 0., 0.)]*len(obj.data.loops))
        for polygon in obj.data.polygons:
            polygon.use_smooth = True
    bpy.ops.object.select_all(action='DESELECT')
    for obj in meshes:
        obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(target.resolve()), export_format='GLB',
        use_selection=True, export_animations=False, export_yup=True)


if __name__ == '__main__':
    main()
