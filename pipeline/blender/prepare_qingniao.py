"""Offline HIGH crow remodel for three red-headed, black-eyed bluebirds.
Normalize the existing jingwei-body-max HIGH master with --length 1.5 first.
Blender --background --python prepare_qingniao.py -- normalized.glb output.glb concept_dir
"""
import math
import os
import sys
import bpy
import numpy as np
from mathutils import Vector
sys.path.insert(0, os.path.dirname(__file__))
from turnaround import load, setup_render, render_views, smoothstep


def remodel(p):
    x,y,z=p
    # The text gives no species or tail count: retain ordinary paired avian anatomy.
    x*=.84
    z=z*.80 if z<.30 else z-.06
    tail=smoothstep(.20,.42,p.y)*(1-smoothstep(.48,.60,p.z))
    y-=max(0,p.y-.20)*.23*tail
    z+=.04*tail
    wing=smoothstep(.16,.26,abs(p.x))*smoothstep(.42,.58,p.z)
    extent=max(0,abs(p.x)-.16)
    x=x*(1-wing)+math.copysign(.15+extent*.13,p.x)*wing
    y+=extent*.52*wing
    z-=extent*.56*wing
    return Vector((x,y,z))


def repaint(obj,original,size=2048):
    image=next(n.image for n in obj.active_material.node_tree.nodes if n.type=='TEX_IMAGE' and n.image and 'diffuse' in n.image.name)
    image.scale(size,size)
    pixels=np.array(image.pixels[:],dtype=np.float32).reshape(size,size,4)
    out=np.ones_like(pixels)
    out[:,:,:3]=[.14,.35,.52]
    uv=obj.data.uv_layers.active.data
    obj.data.calc_loop_triangles()
    for tri in obj.data.loop_triangles:
        uvs=np.array([uv[i].uv[:] for i in tri.loops])*(size-1)
        lo=np.maximum(0,np.floor(uvs.min(axis=0)).astype(int))
        hi=np.minimum(size-1,np.ceil(uvs.max(axis=0)).astype(int))
        if np.any(hi<lo): continue
        xx,yy=np.meshgrid(np.arange(lo[0],hi[0]+1),np.arange(lo[1],hi[1]+1))
        a,b,c=uvs
        den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(den)<1e-9: continue
        wa=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/den
        wb=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/den
        wc=1-wa-wb
        mask=(wa>=-.025)&(wb>=-.025)&(wc>=-.025)
        if not mask.any(): continue
        ids=tri.vertices
        p=wa[...,None]*original[ids[0]]+wb[...,None]*original[ids[1]]+wc[...,None]*original[ids[2]]
        x,y,z=p[...,0],p[...,1],p[...,2]
        value=pixels[yy,xx,:3].max(axis=2)
        shade=np.clip(.48+.90*np.sqrt(value),.48,1.13)
        color=np.zeros_like(p)+[.16,.39,.60]
        breast=np.clip((-y-.18)/.12,0,1)*np.clip((.88-z)/.12,0,1)
        color=color*(1-breast[...,None])+np.array([.31,.57,.64])*breast[...,None]
        # 赤首 is explicit; transition position and exact cinnabar hue are inferred.
        head=np.clip((z-.85)/.09,0,1)*np.clip((.20-np.abs(x))/.06,0,1)
        color=color*(1-head[...,None])+np.array([.78,.16,.10])*head[...,None]
        bill=(y<-.50)&(z>.87)&(z<1.02)&(np.abs(x)<.09)
        color[bill]=[.34,.32,.25]
        feet=(z<.31)&(y<.14)
        color[feet]=[.43,.29,.20]
        eye=(((y+.445)/.032)**2+((z-1.025)/.026)**2<1)&(np.abs(x)>.07)
        color[eye]=[.018,.021,.022]
        glint=(((y+.457)/.006)**2+((z-1.034)/.006)**2<1)&eye
        color[glint]=[.83,.84,.75]
        out[yy[mask],xx[mask],:3]=(color*shade[...,None])[mask]
    image.pixels.foreach_set(out.ravel())
    image.pack()
    mat=obj.active_material
    bsdf=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    for socket in ['Normal','Metallic','Roughness']:
        for link in list(bsdf.inputs[socket].links): mat.node_tree.links.remove(link)
    bsdf.inputs['Roughness'].default_value=.85
    bsdf.inputs['Metallic'].default_value=0


def prepare(path):
    obj=load(path)
    original=np.array([v.co[:] for v in obj.data.vertices])
    repaint(obj,original)
    for v in obj.data.vertices: v.co=remodel(v.co.copy())
    obj.data.update()
    obj.name='qingniao_high_body'
    return obj,original


if __name__=='__main__':
    args=sys.argv[sys.argv.index('--')+1:]
    obj,_=prepare(args[0])
    bpy.ops.export_scene.gltf(filepath=args[1],export_format='GLB',export_animations=False)
    os.makedirs(args[2],exist_ok=True)
    render_views(obj,setup_render(1024),args[2])
    print('EXPORTED',args[1],'triangles',len(obj.data.loop_triangles))
