"""Assemble the new two-stage HIGH fowl and single-wing masters.
Preserve their organic feather geometry and colours; bake five virtue patterns
into existing feather UVs. No chest reshaping, text planes or new anatomy.
Inputs are normalize.py outputs, Blender +Z up / head -Y.
"""
import argparse
import math
import sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix, Vector
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render


def glyph_mask(char, font):
    curve = bpy.data.curves.new('glyph', 'FONT'); curve.body = char; curve.font = font
    curve.resolution_u = 10
    text = bpy.data.objects.new('glyph', curve); bpy.context.collection.objects.link(text)
    bpy.context.view_layer.update()
    mesh = bpy.data.meshes.new_from_object(text.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    mesh.calc_loop_triangles()
    points = np.array([v.co[:2] for v in mesh.vertices])
    assert len(points) > 20, f'Font does not contain {char}'
    points = (points-points.min(axis=0))/(points.max(axis=0)-points.min(axis=0))*251+2
    mask = np.zeros((256, 256), dtype=np.float32)
    for tri in mesh.loop_triangles:
        a,b,c = points[list(tri.vertices)]
        lo = np.maximum(np.floor(np.minimum(np.minimum(a,b),c)).astype(int),0)
        hi = np.minimum(np.ceil(np.maximum(np.maximum(a,b),c)).astype(int),255)
        xx,yy = np.meshgrid(np.arange(lo[0],hi[0]+1),np.arange(lo[1],hi[1]+1))
        d = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(d)<1e-9: continue
        u = ((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/d
        v = ((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/d
        dst = mask[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
        np.maximum(dst,((u>=0)&(v>=0)&(u+v<=1)).astype(np.float32),out=dst)
    bpy.data.objects.remove(text,do_unlink=True); bpy.data.meshes.remove(mesh)
    return mask


def affine(obj, matrix):
    # Transform authored normals with inverse transpose, including reflection.
    # Reversing winding for the right wing never leaves a negative object scale.
    normals = np.array([v.normal[:] for v in obj.data.vertices])
    transform = np.array(matrix.to_3x3().inverted().transposed())
    normals = normals @ transform.T
    lengths = np.linalg.norm(normals,axis=1)
    normals[lengths<1e-8] = [0,0,1]
    normals /= np.maximum(np.linalg.norm(normals,axis=1),1e-8)[:,None]
    assert np.isfinite(normals).all()
    obj.data.transform(matrix)
    if matrix.determinant()<0: obj.data.flip_normals()
    obj.data.normals_split_custom_set_from_vertices(normals.tolist())
    obj.data.update()


def paint(obj, glyphs, wing=False):
    # Each mesh owns its image so left/right characters remain readable.
    mat = obj.data.materials[0].copy(); obj.data.materials[0] = mat
    bsdf = next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    tex = bsdf.inputs['Base Color'].links[0].from_node
    image = tex.image.copy(); tex.image = image
    w,h = image.size; pixels = np.empty(w*h*4,dtype=np.float32)
    image.pixels.foreach_get(pixels); rgba = pixels.reshape(h,w,4)
    # Rodin's photographic feather shadows otherwise cross the ink shader's
    # deep-black threshold over entire coloured feather rows. Lift their wash
    # values while preserving hue, fine relief, and the darkest eyes/claw tips.
    rgba[:,:,:3]=np.power(np.clip(rgba[:,:,:3],0,1),.60)
    uv = obj.data.uv_layers.active.data
    obj.data.calc_loop_triangles()
    hits = {c:0 for c in glyphs}
    for tri in obj.data.loop_triangles:
        xyz = np.array([obj.data.vertices[i].co[:] for i in tri.vertices])
        normal = sum((obj.data.corner_normals[i].vector for i in tri.loops),Vector())/3
        # Projection only reaches the anatomical outward side of each region.
        if wing:
            specs = [('義',0,1,(.340,-.045),(.125,.13),normal.z>.25)]
        else:
            specs = [('德',0,2,(0,.875),(.050,.038),normal.y<-.25),
                     ('仁',0,2,(0,.565),(.115,.105),normal.y<-.35),
                     ('信',0,2,(0,.355),(.100,.085),normal.y<-.35),
                     ('禮',0,1,(0,.065),(.12,.14),normal.z>.35)]
        coords = np.array([(uv[i].uv.x*(w-1),uv[i].uv.y*(h-1)) for i in tri.loops])
        lo=np.maximum(np.floor(coords.min(axis=0)).astype(int),0)
        hi=np.minimum(np.ceil(coords.max(axis=0)).astype(int),[w-1,h-1])
        if np.any(hi<lo): continue
        xx,yy=np.meshgrid(np.arange(lo[0],hi[0]+1),np.arange(lo[1],hi[1]+1));a,b,c=coords
        d=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(d)<1e-8:continue
        u=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/d
        v=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/d
        points=u[...,None]*xyz[0]+v[...,None]*xyz[1]+(1-u-v)[...,None]*xyz[2]
        dst=rgba[lo[1]:hi[1]+1,lo[0]:hi[0]+1,:3]
        for char,ax,ay,center,size,facing in specs:
            if not facing:continue
            px=points[...,ax];py=points[...,ay]
            if wing:
                px=abs(px)
                # Root is forward; top-view reading is along the feather axis.
                gx=(px-center[0])/size[0]+.5;gy=(center[1]-py)/size[1]+.5
                region=points[...,2]>.49
            else:
                gx=(px-center[0])/size[0]+.5;gy=(py-center[1])/size[1]+.5
                region=points[...,1]<-.15 if char!='禮' else points[...,2]>.47
                if char=='禮':gx=1-gx;gy=1-gy
            inside=(gx>=0)&(gx<=1)&(gy>=0)&(gy<=1)&region&(u>=-.001)&(v>=-.001)&(u+v<=1.001)
            alpha=glyphs[char][np.clip((gy*255).astype(int),0,255),np.clip((gx*255).astype(int),0,255)]*inside*.90
            # Small feather markings retain the texture's illumination, without
            # reserving a uniform circular patch or altering the body volume.
            ink=np.array([.90,.70,.30])
            shade=np.clip(dst.max(axis=2)*1.2+.3,.4,1.1)
            dst[:]=dst*(1-alpha[...,None])+ink*shade[...,None]*alpha[...,None]
            hits[char]+=int(np.count_nonzero(alpha))
    image.pixels.foreach_set(rgba.ravel());image.update();image.pack()
    print('FEATHER_GLYPHS',obj.name,hits)


def foot_planes(body):
    # Correct independent toe offsets before binding, blending along each shank.
    for sign in [1,-1]:
        points=[v.co for v in body.data.vertices if sign*v.co.x>.04 and v.co.z<.07]
        offset=min(p.z for p in points)
        for v in body.data.vertices:
            p=v.co
            if sign*p.x>.04 and p.z<.27:
                t=max(0,min(1,(p.z-.07)/.20));p.z-=offset*(1-t*t*(3-2*t))
        print('SOLE_REST_OFFSET',sign,offset)
    body.data.update()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('body');p.add_argument('wing');p.add_argument('output');p.add_argument('views')
    p.add_argument('--font',default='/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    body=load(a.body);body.name='fowl_body';foot_planes(body)
    font=bpy.data.fonts.load(a.font);glyphs={c:glyph_mask(c,font) for c in '德義禮仁信'}
    paint(body,glyphs)
    before=set(bpy.context.scene.objects);bpy.ops.import_scene.gltf(filepath=a.wing)
    wing=next(o for o in bpy.context.scene.objects if o not in before and o.type=='MESH')
    bpy.context.view_layer.objects.active=wing;wing.select_set(True)
    bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
    bpy.ops.object.transform_apply(location=True,rotation=True,scale=True)
    # Accepted HIGH's shoulder is at -Y, primaries at +Y, outer face +X.
    affine(wing,Matrix.Rotation(-math.pi/2,4,'Z'))
    points=[v.co for v in wing.data.vertices];xmin=min(v.x for v in points);xmax=max(v.x for v in points)
    base=[p for p in points if p.x<xmin+(xmax-xmin)*.075]
    root=sum(base,Vector())/len(base)
    # Source wing is in XZ with its outer surface facing -Y. Rotate that surface
    # upward, leave the natural curved feather fan extending +X and trailing +Y.
    scale=.60/(xmax-root.x)
    mount=Vector((.120,-.180,.570))
    matrix=Matrix.Translation(mount)@Matrix.Scale(scale,4)@Matrix.Rotation(-math.pi/2,4,'X')@Matrix.Translation(-root)
    affine(wing,matrix);wing.name='wing_l'
    source_material=wing.data.materials[0]
    right=wing.copy();right.data=wing.data.copy();bpy.context.collection.objects.link(right);right.name='wing_r'
    affine(right,Matrix.Diagonal((-1,1,1,1)))
    wing.data.materials[0]=source_material
    right.data.materials[0]=source_material
    paint(wing,glyphs,True);paint(right,glyphs,True)
    body.data.materials[0].name='fowl_plumage'
    wing.data.materials[0].name='flight_l'
    right.data.materials[0].name='flight_r'
    parts=[body,wing,right]
    for obj in parts:
        obj.data.calc_loop_triangles();print('HIGH_PART',obj.name,len(obj.data.loop_triangles))
    bpy.ops.object.select_all(action='DESELECT')
    for obj in parts:obj.select_set(True)
    bpy.context.view_layer.objects.active=body
    # Join for the existing single-mesh rig loader; retain named material slots
    # so body, wing and crown weights are selected by exact authored membership.
    bpy.ops.object.join();body.name='fenghuang_prepared'
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output,export_format='GLB',use_selection=True,export_animations=False)
    Path(a.views).mkdir(parents=True,exist_ok=True)
    render_views(body,setup_render(1024),a.views)


if __name__=='__main__':main()
