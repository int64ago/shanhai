"""Candidate-only Bashe axial rig. Never writes public assets or edits the source.

Run Blender with --background --factory-startup --disable-autoexec
--python-exit-code 1 --python pipeline/blender/rig_bashe_native.py --
INPUT_GLB raw/_build/bashe-UNIQUE --head-end min|max [--axis x|y]

The anatomical head end must be established by image review, not view filenames.
--inspect-only emits oriented source views and sections before any rig is made.
Only positive uniform scale and rigid orientation are applied to source geometry.
The first bone holds the head rigid; 23 further segments follow measured sections.
"""
import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.dont_write_bytecode = True
FPS = 30
BONES = 24
CLEARANCE = 0.006


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def quantile(values, fraction):
    values = sorted(values)
    return values[round((len(values) - 1) * fraction)]


def curves(action):
    for layer in action.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                yield from bag.fcurves


def import_source(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(args.input))
    meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if not meshes:
        raise ValueError('No mesh in source')
    for obj in meshes:
        if obj.modifiers or obj.type != 'MESH' or obj.vertex_groups:
            raise ValueError('Expected an unrigged native mesh')
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for obj in list(bpy.context.scene.objects):
        if obj not in meshes:
            bpy.data.objects.remove(obj, do_unlink=True)
    points = [v.co.copy() for o in meshes for v in o.data.vertices]
    if not all(math.isfinite(c) for p in points for c in p):
        raise ValueError('Nonfinite source positions')
    lo = Vector(tuple(min(p[k] for p in points) for k in range(3)))
    hi = Vector(tuple(max(p[k] for p in points) for k in range(3)))
    axis = 'xy'.index(args.axis) if args.axis else max((0, 1), key=lambda k: hi[k] - lo[k])
    other = 1 - axis
    if (hi[axis] - lo[axis]) < 3 * (hi[other] - lo[other]):
        raise ValueError('Expected an uncoiled snake; review source instead of forcing an axial fit')
    # A proper rotation puts the explicitly reviewed anatomical head at Blender -Y.
    sign = 1 if args.head_end == 'max' else -1
    heading = Vector((sign if axis == 0 else 0, sign if axis == 1 else 0, 0))
    yaw = -math.pi / 2 - math.atan2(heading.y, heading.x)
    rotation = Matrix.Rotation(yaw, 4, 'Z')
    scale = args.length / (hi[axis] - lo[axis])
    center = (lo + hi) / 2
    transform = Matrix.Scale(scale, 4) @ rotation @ Matrix.Translation(-center)
    for i, obj in enumerate(meshes):
        obj.data.transform(transform)
        obj.name = f'bashe_native_{i:02}'
    points = [v.co.copy() for o in meshes for v in o.data.vertices]
    floor = min(p.z for p in points)
    for obj in meshes:
        obj.data.transform(Matrix.Translation((0, 0, CLEARANCE - floor)))
    for image in bpy.data.images:
        if max(image.size) > args.max_texture:
            ratio = args.max_texture / max(image.size)
            image.scale(round(image.size[0] * ratio), round(image.size[1] * ratio))
    return meshes, {'source_axis': 'xy'[axis], 'source_head_end': args.head_end,
                    'uniform_scale': scale, 'rotation_z_radians': yaw,
                    'source_bounds_blender': [list(lo), list(hi)]}


def measure(meshes, head_fraction):
    pts = [v.co.copy() for o in meshes for v in o.data.vertices]
    ymin, ymax = min(p.y for p in pts), max(p.y for p in pts)
    length = ymax - ymin
    # Cross-section midpoints are independent of vertex density and texture seams.
    sections = []
    for i in range(121):
        y = ymin + length * i / 120
        band = [p for p in pts if abs(p.y - y) <= length / 100]
        if not band:
            raise ValueError(f'Discontinuous source at longitudinal section {i}')
        sections.append(Vector(((quantile([p.x for p in band], .02) + quantile([p.x for p in band], .98)) / 2,
                                y, (quantile([p.z for p in band], .02) + quantile([p.z for p in band], .98)) / 2)))
    for _ in range(3):
        sections = [sections[0]] + [(sections[i-1] + sections[i]*2 + sections[i+1])/4
                                    for i in range(1, 120)] + [sections[-1]]
    def point(fraction):
        at = max(0, min(120, fraction * 120))
        k = min(119, int(at))
        return sections[k].lerp(sections[k+1], at-k)
    fractions = [0] + [head_fraction + (1-head_fraction)*i/(BONES-1) for i in range(BONES)]
    centers = [point(p) for p in fractions]
    # Adapt the animated rest line to the source's lower envelope. This changes
    # bone poses only: the native surface, topology, UVs and normals stay intact.
    # Broad bands avoid fitting individual scale dents or texture-seam vertices.
    lower = []
    for center in centers:
        band = [p.z for p in pts if abs(p.y-center.y) <= length*.018]
        lower.append(min(band))
    for _ in range(2):
        lower = [lower[0]] + [(lower[i-1]+2*lower[i]+lower[i+1])/4
                             for i in range(1,len(lower)-1)] + [lower[-1]]
    fitted = [c + Vector((0,0,-max(0,z-.018))) for c,z in zip(centers,lower)]
    # One rigid head span followed by measured, gradually tapered body spans.
    fitted[0] = centers[0].copy(); fitted[1] = centers[1].copy()
    return centers, fitted, lower, sections, ymin, length


def blue_head_texture(meshes, ymin, length):
    """Tint only head UV texels; keep eye/nostril ink and existing cyan intact.

    A barycentric anatomical mask fades from the crown into the first 15% of
    body length. No material overrides or extra meshes are needed at runtime.
    """
    import numpy as np
    masks = {}
    for obj in meshes:
        uv = obj.data.uv_layers.active
        if uv is None:
            raise ValueError('Head palette correction requires native UVs')
        obj.data.calc_loop_triangles()
        for tri in obj.data.loop_triangles:
            material = obj.data.materials[tri.material_index]
            shader = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
            links = shader.inputs['Base Color'].links
            if not links or links[0].from_node.type != 'TEX_IMAGE':
                raise ValueError('Expected a native base-color image')
            image = links[0].from_node.image
            fractions = np.array([(obj.data.vertices[k].co.y-ymin)/length for k in tri.vertices])
            if fractions.min() >= .15:
                continue
            width, height = image.size
            if image.name not in masks:
                masks[image.name] = (image, np.zeros((height,width), dtype=np.float32))
            mask = masks[image.name][1]
            coords = np.array([uv.data[k].uv[:] for k in tri.loops]) * [width,height]
            low = np.maximum(0,np.floor(coords.min(axis=0)).astype(int))
            high = np.minimum([width-1,height-1],np.ceil(coords.max(axis=0)).astype(int))
            if np.any(high < low):
                continue
            yy,xx = np.mgrid[low[1]:high[1]+1,low[0]:high[0]+1]
            a,b,c = coords
            den = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
            if abs(den)<1e-8:
                continue
            w0 = ((b[1]-c[1])*(xx+.5-c[0])+(c[0]-b[0])*(yy+.5-c[1]))/den
            w1 = ((c[1]-a[1])*(xx+.5-c[0])+(a[0]-c[0])*(yy+.5-c[1]))/den
            w2 = 1-w0-w1
            inside = (w0>=-1e-5)&(w1>=-1e-5)&(w2>=-1e-5)
            p = w0*fractions[0]+w1*fractions[1]+w2*fractions[2]
            fade = np.clip((p-.075)/.075,0,1)
            value = (1-fade*fade*(3-2*fade))*inside
            patch = mask[low[1]:high[1]+1,low[0]:high[0]+1]
            np.maximum(patch,value,out=patch)
    results = []
    for image, mask in masks.values():
        # One-texel atlas bleed avoids a seam at triangle borders, without
        # changing geometry or painting another anatomical region.
        padded = np.pad(mask,1)
        mask = np.maximum.reduce([padded[y:y+mask.shape[0],x:x+mask.shape[1]]
                                  for y,x in ((1,1),(0,1),(2,1),(1,0),(1,2))])
        pixels = np.empty(len(image.pixels),dtype=np.float32)
        image.pixels.foreach_get(pixels)
        rgba = pixels.reshape((*mask.shape,4)); rgb = rgba[:,:,:3]
        lum = rgb @ np.array([.2126,.7152,.0722])
        ink_guard = np.clip((lum-.04)/.09,0,1)
        ink_guard = ink_guard*ink_guard*(3-2*ink_guard)
        cyan_guard = 1-np.clip((rgb[:,:,1]-rgb[:,:,0]-.025)/.15,0,1)
        amount = mask*ink_guard*cyan_guard*.90
        # Lift the head pigment above the ink ramp's deep-shadow band while
        # retaining luminance variation. A small PBR tint alone becomes black
        # under the existing shader and does not satisfy the chosen 青首 palette.
        teal = np.stack((lum*.40+.025,lum*.75+.36,lum*.78+.38),axis=-1)
        rgb[:] = np.clip(rgb*(1-amount[:,:,None])+teal*amount[:,:,None],0,1)
        image.pixels.foreach_set(rgba.ravel())
        image.update(); image.pack()
        results.append({'image':image.name,'affected_texels':int(np.count_nonzero(amount>.01)),
                        'head_fade_fraction':[.075,.15], 'dark_texels_preserved_below':.04,
                        'native_head_luminance_quantiles':np.quantile(lum[mask>.8],[.1,.5,.9]).tolist(),
                        'blue_green_lift':[.025,.36,.38],
                        'body_texture_unchanged_outside_head_mask':True})
    return results


def build_rig(meshes, centers):
    arm = bpy.data.objects.new('bashe_candidate_rig', bpy.data.armatures.new('bashe_candidate_rig'))
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm.data.edit_bones
    root = eb.new('root'); root.head = (0, 0, 0); root.tail = (0, 0, .1)
    for i in range(BONES):
        bone = eb.new('head' if i == 0 else f'axial_{i:02}')
        bone.head = centers[i]; bone.tail = centers[i+1]
        bone.parent = root if i == 0 else eb['head' if i == 1 else f'axial_{i-1:02}']
        bone.use_connect = i > 0
    bpy.ops.object.mode_set(mode='OBJECT')
    # The uncoiled longitudinal coordinate gives a continuous projection without
    # branch ambiguity. Protect the head; blend adjoining segment centers cubically.
    mids = [(centers[i].y+centers[i+1].y)/2 for i in range(BONES)]
    mids[0] = centers[1].y - (centers[-1].y-centers[0].y)*.015
    for obj in meshes:
        groups = [obj.vertex_groups.new(name='head' if i == 0 else f'axial_{i:02}') for i in range(BONES)]
        for vertex in obj.data.vertices:
            y = vertex.co.y
            if y <= mids[0]:
                groups[0].add([vertex.index], 1, 'REPLACE')
                continue
            upper = next((i for i in range(1, BONES) if y <= mids[i]), BONES-1)
            lower = upper-1
            w = smooth((y-mids[lower])/(mids[upper]-mids[lower]))
            groups[lower].add([vertex.index], 1-w, 'REPLACE')
            groups[upper].add([vertex.index], w, 'REPLACE')
        mod = obj.modifiers.new('Bashe smooth axial deformation', 'ARMATURE')
        mod.object = arm
        obj.parent = arm
    return arm


def evaluated(meshes):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    output = []
    for obj in meshes:
        result = obj.evaluated_get(depsgraph)
        output.extend(result.matrix_world @ v.co for v in result.data.vertices)
    return output


def apply_segments(arm, centers):
    for i in range(BONES):
        pb = arm.pose.bones['head' if i == 0 else f'axial_{i:02}']
        rest = pb.bone
        rotation = (rest.tail_local-rest.head_local).rotation_difference(centers[i+1]-centers[i])
        pb.matrix = Matrix.Translation(centers[i]) @ rotation.to_matrix().to_4x4() @ rest.matrix_local.to_quaternion().to_matrix().to_4x4()
        bpy.context.view_layer.update()


def animate(arm, meshes, rest, fitted, name, seconds):
    arm.animation_data_create()
    action = bpy.data.actions.new(name)
    arm.animation_data.action = action
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'; pb.matrix_basis.identity()
    n = round(seconds * FPS)
    clearances, peak_lifts = [], []
    for frame in range(n+1):
        phase = frame/n * math.tau
        display = math.sin(math.pi*frame/n)**2 if name == 'special' else 0
        directions = []
        for i in range(BONES):
            p = i/(BONES-1)
            wave = math.sin(phase - p*math.tau*1.35)
            if i == 0:
                yaw = .009*math.sin(phase)
            else:
                amplitude = {'idle': .035, 'walk': .30, 'special': .14}[name]
                yaw = amplitude * wave * smooth(p/.18) * (1-.22*smooth((p-.8)/.2))
            direction = (fitted[i+1]-fitted[i]).normalized() * (rest[i+1]-rest[i]).length
            direction = Quaternion((0,0,1), yaw) @ direction
            if name == 'special':
                # Controlled anterior rise; no hood, coils, limbs or extra anatomy.
                pitch = -.23 * display * (1-smooth(p/.36))
                right = Vector((direction.y, -direction.x, 0)).normalized()
                direction = Quaternion(right, pitch) @ direction
            directions.append(direction)
        start = rest[0].copy()
        start.z = fitted[-1].z - sum(d.z for d in directions)
        posed = [start]
        for direction in directions:
            posed.append(posed[-1]+direction)
        apply_segments(arm, posed)
        points = evaluated(meshes)
        # Measure the actual skinned belly, not bone endpoints or rest bounds.
        correction = CLEARANCE - min(p.z for p in points)
        for point in posed:
            point.z += correction
        apply_segments(arm, posed)
        points = evaluated(meshes)
        if not all(math.isfinite(c) for p in points for c in p):
            raise ValueError(f'Nonfinite deformation in {name} frame {frame}')
        clearances.append(min(p.z for p in points))
        peak_lifts.append(posed[0].z-rest[0].z)
        for pb in arm.pose.bones:
            pb.keyframe_insert('location', frame=frame)
            pb.keyframe_insert('rotation_quaternion', frame=frame)
    for fc in curves(action):
        for point in fc.keyframe_points:
            point.interpolation = 'LINEAR'
    track = arm.animation_data.nla_tracks.new(); track.name = name
    track.strips.new(name, 0, action); track.mute = True
    arm.animation_data.action = None
    return action, {'duration': seconds, 'frames_checked': n+1,
                    'minimum_skinned_z': min(clearances), 'maximum_minimum_skinned_z': max(clearances),
                    'maximum_head_lift': max(peak_lifts)}


def setup_render(length):
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'; scene.cycles.samples = 24
    scene.render.resolution_x = 1440; scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.world = bpy.data.worlds.new('Bashe review world'); scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.72,.73,.75,1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = .45
    scene.view_settings.view_transform = 'AgX'
    floor_mat = bpy.data.materials.new('review floor'); floor_mat.diffuse_color = (.64,.61,.54,1)
    bpy.ops.mesh.primitive_plane_add(size=length*8)
    floor = bpy.context.object; floor.name = 'REVIEW_ONLY_floor'; floor.data.materials.append(floor_mat)
    for name, location, energy, size in [('key',(length,-length,length*1.5),1100,5),
                                         ('fill',(-length,-length*.5,length),700,5)]:
        light = bpy.data.objects.new(name, bpy.data.lights.new(name,'AREA'))
        scene.collection.objects.link(light); light.location = location
        light.rotation_euler = (Vector((0,0,.1))-light.location).to_track_quat('-Z','Y').to_euler()
        light.data.energy = energy; light.data.shape = 'DISK'; light.data.size = size
    camera = bpy.data.objects.new('review camera', bpy.data.cameras.new('review camera'))
    scene.collection.objects.link(camera); scene.camera = camera; camera.data.type = 'ORTHO'
    return camera


def render_view(camera, path, target, offset, span):
    scene = bpy.context.scene
    camera.location = Vector(target)+Vector(offset)
    camera.rotation_euler = (Vector(target)-camera.location).to_track_quat('-Z','Y').to_euler()
    camera.data.ortho_scale = span
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path); parser.add_argument('output_dir', type=Path)
    parser.add_argument('--head-end', choices=('min','max'), required=True)
    parser.add_argument('--axis', choices=('x','y'))
    parser.add_argument('--length', type=float, default=4.8)
    parser.add_argument('--head-fraction', type=float, default=.12)
    parser.add_argument('--max-texture', type=int, default=2048)
    parser.add_argument('--expected-sha256'); parser.add_argument('--inspect-only', action='store_true')
    parser.add_argument('--blue-head', action='store_true', help='Candidate-only anatomical blue-green head texture mask')
    parser.add_argument('--skip-render', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    root = Path(__file__).resolve().parents[2]
    args.input = args.input.resolve(); args.output_dir = args.output_dir.resolve()
    if not args.input.is_relative_to(root/'raw'):
        raise ValueError('Only immutable raw inputs are accepted')
    if args.output_dir.parent != root/'raw'/'_build' or not args.output_dir.name.startswith('bashe-'):
        raise ValueError('Outputs must use a unique raw/_build/bashe-* directory')
    if args.output_dir.exists():
        raise ValueError('Refusing to overwrite an existing candidate directory')
    if not (.06 <= args.head_fraction <= .20 and 1 <= args.length <= 10):
        raise ValueError('Review head fraction / size before rigging')
    checksum = digest(args.input)
    if args.expected_sha256 and checksum != args.expected_sha256:
        raise ValueError('Source checksum mismatch')
    args.output_dir.mkdir(parents=True)
    meshes, orientation = import_source(args)
    centers, fitted, lower, sections, ymin, length = measure(meshes, args.head_fraction)
    report = {'candidate_only': True, 'input': str(args.input), 'input_sha256': checksum,
              'orientation': orientation, 'head_fraction': args.head_fraction,
              'head_blender': list(centers[0]), 'tail_blender': list(centers[-1]),
              'centerline_blender': [list(p) for p in centers],
              'ground_pose_centerline_blender': [list(p) for p in fitted],
              'native_section_lower_envelope': lower, 'actions': {}, 'images': [],
              'limitations': ['Anatomy and palette require image review; numeric checks do not approve this asset.',
                              'In-place ground slither; forward locomotion is outside this offline rig.',
                              'No production Stage, readiness flag, metadata or public asset is changed.']}
    if args.blue_head:
        report['head_palette_correction'] = blue_head_texture(meshes,ymin,length)
    arm = None
    if not args.inspect_only:
        arm = build_rig(meshes, centers)
        for name, seconds in [('idle',4.8),('walk',3.2),('special',4.8)]:
            _, report['actions'][name] = animate(arm, meshes, centers, fitted, name, seconds)
        for pb in arm.pose.bones: pb.matrix_basis.identity()
        arm.animation_data.action = None
        scene = bpy.context.scene; scene.render.fps = FPS; scene.frame_set(0)
        bpy.ops.object.select_all(action='DESELECT')
        arm.select_set(True)
        for obj in meshes: obj.select_set(True)
        output = args.output_dir/'body.glb'
        bpy.ops.export_scene.gltf(filepath=str(output), export_format='GLB', use_selection=True,
                                  export_animations=True, export_animation_mode='NLA_TRACKS',
                                  export_skins=True, export_def_bones=False,
                                  export_optimize_animation_size=False, export_force_sampling=True)
        report['output'] = str(output); report['output_sha256'] = digest(output)
        report['deform_bones'] = BONES; report['total_bones'] = len(arm.data.bones)
    if not args.skip_render:
        camera = setup_render(length)
        views = [('source_34',(0,0,.16),(length,-length*.75,length*.65),length*1.1),
                 ('source_side',(0,0,.13),(length*2,0,.4),length*1.08),
                 ('source_top',(0,0,0),(0,0,length*2),length*1.8),
                 ('source_head',centers[0]+(centers[1]-centers[0])*.4,(length*.3,-length*.35,length*.16),length*.26),
                 ('source_tail',centers[-3],(length*.4,length*.25,length*.18),length*.33)]
        for name,target,offset,span in views:
            path = args.output_dir/f'{name}.png'
            render_view(camera,path,target,offset,span); report['images'].append(str(path))
        if arm:
            for name in ('idle','walk','special'):
                arm.animation_data.action = bpy.data.actions[name]
                duration = report['actions'][name]['duration']
                for sample, fraction in enumerate((.125,.375,.625)):
                    bpy.context.scene.frame_set(round(duration*FPS*fraction))
                    path = args.output_dir/f'{name}_{sample:02}.png'
                    render_view(camera,path,(0,0,.18),(length,-length*.75,length*.65),length*1.1)
                    report['images'].append(str(path))
    if digest(args.input) != checksum:
        raise RuntimeError('Native input changed')
    (args.output_dir/'rig-review.json').write_text(json.dumps(report,indent=2)+'\n')
    print('BASHE_CANDIDATE',json.dumps({k:v for k,v in report.items() if k not in ('centerline_blender','images')},indent=2))


if __name__ == '__main__':
    main()
