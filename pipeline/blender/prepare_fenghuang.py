"""Offline chicken-shaped Fenghuang from the verified Jingwei Extreme-High master.
No network/generation calls or simplification. A compact bill, deep breast,
short rounded wings, raised short fan and low feather crown distinguish the
silhouette. Five virtue glyphs are baked into existing feather UVs, following
surface relief rather than floating labels. Literal glyph design is inference.
Input: normalized +Z-up, head -Y. Output: prepared GLB and four views.
"""
import argparse
import math
import sys
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from turnaround import load, render_views, setup_render


def smooth(a, b, x):
    t = np.clip((x-a)/(b-a), 0, 1)
    return t*t*(3-2*t)


def shape(p):
    x, y, z = p.T
    q = p.copy()
    breast = (1-smooth(.20, .29, abs(x)))*smooth(.32, .45, z)*(1-smooth(.73, .85, z))
    q[:, 0] *= 1+.42*breast
    wing = smooth(.20, .32, abs(x))
    q[:, 0] = np.sign(x)*(abs(q[:, 0])-.22*np.maximum(abs(x)-.22, 0)*wing)
    q[:, 1] += .045*wing
    bill = (y < -.405) & (z > .84)
    q[bill, 1] = -.405+(y[bill]+.405)*.38
    q[:, 2] = np.where(z < .40, z*.78, z-.088)
    tail = smooth(.17, .30, y)*(1-smooth(.48, .58, z))
    q[:, 0] *= 1+.35*tail
    # Rotate the native feather plane upward about the rump, rather than
    # shearing a downward tail into a thin vertical wall.
    angle = math.radians(82)
    dy, dz = y-.18, z-.50
    raised_y = .18+.68*(math.cos(angle)*dy-math.sin(angle)*dz)
    raised_z = .412+.68*(math.sin(angle)*dy+math.cos(angle)*dz)
    q[:, 1] = q[:, 1]*(1-tail)+raised_y*tail
    q[:, 2] = q[:, 2]*(1-tail)+raised_z*tail
    return q


def proportions(obj):
    p = np.array([v.co[:] for v in obj.data.vertices])
    q = shape(p)
    # Numerical Jacobian applies the inverse transpose to the authored normals,
    # including local feather-tail shear; never recompute source vertex normals.
    jac = np.empty((len(p), 3, 3))
    for axis in range(3):
        offset = np.zeros(3); offset[axis] = 1e-5
        jac[:, :, axis] = (shape(p+offset)-shape(p-offset))/(2e-5)
    inv = np.linalg.inv(jac)
    normals = np.array([n.vector[:] for n in obj.data.corner_normals])
    indices = np.array([loop.vertex_index for loop in obj.data.loops])
    normals = np.einsum('ni,nij->nj', normals, inv[indices])
    length = np.linalg.norm(normals, axis=1)
    normals[length < 1e-8] = [0, 0, 1]
    normals /= np.maximum(np.linalg.norm(normals, axis=1), 1e-8)[:, None]
    assert np.isfinite(normals).all()
    for v, point in zip(obj.data.vertices, q): v.co = point
    obj.data.normals_split_custom_set(normals.tolist()); obj.data.update()


def glyph_mask(char, font):
    curve = bpy.data.curves.new('glyph', 'FONT'); curve.body = char; curve.font = font
    curve.resolution_u = 10
    text = bpy.data.objects.new('glyph', curve); bpy.context.collection.objects.link(text)
    bpy.context.view_layer.objects.active = text
    bpy.context.view_layer.update()
    obj_mesh = bpy.data.meshes.new_from_object(text.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    obj_mesh.calc_loop_triangles()
    points = np.array([v.co[:2] for v in obj_mesh.vertices])
    assert len(points) > 20, f'Font does not contain {char}'
    points = (points-points.min(axis=0))/(points.max(axis=0)-points.min(axis=0))*251+2
    mask = np.zeros((256, 256), dtype=np.float32)
    for tri in obj_mesh.loop_triangles:
        a, b, c = points[list(tri.vertices)]
        lo = np.maximum(np.floor(np.minimum(np.minimum(a,b),c)).astype(int),0)
        hi = np.minimum(np.ceil(np.maximum(np.maximum(a,b),c)).astype(int),255)
        xx, yy = np.meshgrid(np.arange(lo[0],hi[0]+1),np.arange(lo[1],hi[1]+1))
        d = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(d)<1e-9: continue
        u = ((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/d
        v = ((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/d
        dst = mask[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
        np.maximum(dst, ((u>=0)&(v>=0)&(u+v<=1)).astype(np.float32), out=dst)
    bpy.data.objects.remove(text, do_unlink=True); bpy.data.meshes.remove(obj_mesh)
    return mask


def paint(obj, font_path):
    font = bpy.data.fonts.load(font_path)
    glyphs = {c:glyph_mask(c, font) for c in '德義禮仁信'}
    # Visibility, rather than normal thresholds, confines each wing mark to the
    # outer feather layer. Otherwise a planar projection repeats on the steep
    # hidden sides of overlapping feathers and becomes long broken streaks.
    tree = BVHTree.FromObject(obj, bpy.context.evaluated_depsgraph_get())
    dorsal = np.full((256, 512), -10.0)
    for row, yy in enumerate(np.linspace(-.15, .10, 256)):
        for col, xx in enumerate(np.linspace(-.37, .37, 512)):
            hit, _, _, _ = tree.ray_cast(Vector((xx, yy, 2)), Vector((0, 0, -1)))
            if hit is not None: dorsal[row, col] = hit.z
    shader = next(n for n in obj.data.materials[0].node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    image = shader.inputs['Base Color'].links[0].from_node.image
    w,h = image.size; px = np.empty(w*h*4,dtype=np.float32); image.pixels.foreach_get(px)
    rgba = px.reshape(h,w,4); old = rgba.copy(); uv = obj.data.uv_layers.active.data
    palette = np.array([[.68,.12,.075],[.065,.36,.31],[.82,.56,.16],[.88,.83,.66],[.065,.075,.075]])
    obj.data.calc_loop_triangles()
    for tri in obj.data.loop_triangles:
        coords = np.array([(uv[i].uv.x*(w-1),uv[i].uv.y*(h-1)) for i in tri.loops])
        lo = np.maximum(np.floor(coords.min(axis=0)).astype(int)-1,0)
        hi = np.minimum(np.ceil(coords.max(axis=0)).astype(int)+1,[w-1,h-1])
        xx,yy = np.meshgrid(np.arange(lo[0],hi[0]+1),np.arange(lo[1],hi[1]+1)); a,b,c=coords
        d=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(d)<1e-8:continue
        u=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/d
        v=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/d
        pts=np.array([obj.data.vertices[i].co[:] for i in tri.vertices])
        xyz=u[...,None]*pts[0]+v[...,None]*pts[1]+(1-u-v)[...,None]*pts[2]
        x,y,z=xyz[...,0],xyz[...,1],xyz[...,2]
        src=old[lo[1]:hi[1]+1,lo[0]:hi[0]+1,:3]; brightness=src.max(axis=2)
        shade=np.clip(.74+brightness*2,.65,1.3)[...,None]
        colour=np.zeros_like(src)+palette[1]
        front=smooth(.04,.18,-y)[...,None]
        belly=(1-smooth(.45,.52,z))[...,None]
        warm=palette[2]*(1-belly)+palette[3]*belly
        colour=colour*(1-front)+warm*front
        head=smooth(.71,.78,z)[...,None]
        colour=colour*(1-head)+palette[0]*head
        primaries=abs(x)>.35
        bands=(np.floor(abs(x)*25+y*9).astype(int)%4)
        colour[primaries]=palette[bands[primaries]]
        feet=(z<.24)&(y<.12);colour[feet]=[.51,.36,.18]
        bill=(y<-.44)&(z>.76)&(z<.94)&(abs(x)<.08);colour[bill]=palette[2]
        eye=(abs(x)>.065)&(((y+.43)/.045)**2+((z-.925)/.035)**2<1)&(brightness<.12)
        colour[eye]=palette[4]
        colour*=shade
        # Coordinates are physical feather regions. The glyph alpha is baked
        # directly into the feather UVs, with no card, badge, extruded text or decal.
        front_facing = sum(obj.data.corner_normals[i].vector.y for i in tri.loops)/3 < -.20
        outer = z >= dorsal[np.clip(((y+.15)/.25*255).astype(int),0,255),np.clip(((x+.37)/.74*511).astype(int),0,511)]-.006
        marks=[('德',x/.095+.5,(z-.995)/.080+.5,(y<-.28)&(z>.945)&front_facing,True),
               ('義',(x-np.sign(x)*.29)/.11+.5,(y+.025)/.13+.5,(abs(x)>.21)&(z>.52)&outer,True),
               ('禮',-x/.13+.5,(z-.72)/.12+.5,(abs(x)<.12)&(y>-.12)&(y<.20),True),
               ('仁',x/.13+.5,(z-.615)/.12+.5,(y<-.13)&(z>.50)&(z<.73),False),
               ('信',x/.12+.5,(z-.415)/.12+.5,(y<-.08)&(z<.51),False)]
        for char,gx,gy,region,light in marks:
            inside=(gx>=0)&(gx<=1)&(gy>=0)&(gy<=1)&region
            alpha=glyphs[char][np.clip((gy*255).astype(int),0,255),np.clip((gx*255).astype(int),0,255)]*inside
            ink=np.array([.94,.81,.46] if light else [.085,.065,.045])
            colour=colour*(1-alpha[...,None]*.94)+ink*shade*alpha[...,None]*.94
        mask=(u>=-.02)&(v>=-.02)&(u+v<=1.02)
        dst=rgba[lo[1]:hi[1]+1,lo[0]:hi[0]+1,:3];dst[mask]=np.clip(colour,0,1)[mask]
    image.pixels.foreach_set(rgba.ravel());image.update();image.file_format='PNG';image.pack()


def feather(name, root, tip, width, colour):
    root,tip=Vector(root),Vector(tip);axis=tip-root
    lateral=Vector((1,0,0));normal=axis.cross(lateral).normalized()
    verts=[];faces=[];rings=25;cross=9
    for i in range(rings):
        t=i/(rings-1);p=root+axis*t
        envelope=math.sin(math.pi*t)**.7*width+.0004
        for j in range(cross):
            s=j/(cross-1)*2-1
            verts.append(p+lateral*s*envelope+normal*(.013*(1-s*s)*math.sin(math.pi*t)))
    for i in range(rings-1):
        for j in range(cross-1):
            k=i*cross+j;faces.append((k,k+1,k+cross+1,k+cross))
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(verts,[],faces);mesh.update()
    obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj)
    mat=bpy.data.materials.new(name);mat.diffuse_color=(*colour,1);mat.use_nodes=True
    bsdf=mat.node_tree.nodes.get('Principled BSDF');bsdf.inputs['Roughness'].default_value=.8
    u,v=np.meshgrid(np.linspace(-1,1,128),np.linspace(0,1,512))
    shaft=np.exp(-(u/.045)**2)
    barbs=.045*np.cos((v+.18*abs(u))*math.tau*45)
    shade=.82+.15*(1-u*u)+barbs
    pixels=np.ones((512,128,4),dtype=np.float32)
    pixels[:,:,:3]=np.array(colour)*shade[...,None]
    pixels[:,:,:3]=pixels[:,:,:3]*(1-shaft[...,None]*.7)+np.array([.78,.59,.23])*shaft[...,None]*.7
    image=bpy.data.images.new(name,width=128,height=512)
    image.pixels.foreach_set(pixels.ravel());image.pack()
    tex=mat.node_tree.nodes.new('ShaderNodeTexImage');tex.image=image
    mat.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color'])
    mesh.materials.append(mat)
    uv=mesh.uv_layers.new()
    for face in mesh.polygons:
        face.use_smooth=True
        for loop in face.loop_indices:
            index=mesh.loops[loop].vertex_index
            uv.data[loop].uv=(index%cross/(cross-1),index//cross/(rings-1))
    return obj


def plumage(obj):
    colours=[(.68,.12,.075),(.065,.36,.31),(.82,.56,.16),(.88,.83,.66),(.065,.075,.075)]
    parts=[]
    for i in range(7):
        s=(i-3)/3
        parts.append(feather('short_fan', (s*.018,.25,.46), (s*.27,.47+.06*(1-abs(s)),.64+.12*(1-abs(s))), .055, colours[i%5]))
    for i in range(5):
        s=(i-2)/2
        parts.append(feather('low_crown',(s*.024,-.30,1.005),(s*.065,-.20,1.105+.035*(1-abs(s))),.023,colours[(i+2)%5]))
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True)
    for part in parts:part.select_set(True)
    bpy.context.view_layer.objects.active=obj;bpy.ops.object.join()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('input');p.add_argument('output');p.add_argument('views')
    p.add_argument('--font',default='/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);obj=load(a.input)
    proportions(obj);paint(obj,a.font);plumage(obj)
    obj.data.calc_loop_triangles();print('FENGHUANG_HIGH 49902 source triangles;',len(obj.data.loop_triangles),'final triangles')
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output,export_format='GLB',use_selection=True,export_animations=False)
    Path(a.views).mkdir(parents=True,exist_ok=True);render_views(obj,setup_render(1024),a.views)


if __name__=='__main__':main()
