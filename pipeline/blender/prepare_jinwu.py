"""Offline two-foot Wu from the already verified Jingwei Extreme-High master.
The source says 烏, without three feet or gold. Corvid proportions, charcoal
colour, eyes and two-foot arrangement are explicit inference. No new generation,
remeshing, simplification, negative scale or added solar sphere.
Input: normalized Blender +Z-up, forward -Y. Outputs model and four views.
"""
import argparse
import math
import sys
from pathlib import Path
import bpy
import numpy as np
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from turnaround import load,render_views,setup_render


def smooth(a,b,x):
    t=np.clip((x-a)/(b-a),0,1);return t*t*(3-2*t)


def shape(p):
    x,y,z=p.T;q=p.copy()
    breast=(1-smooth(.20,.32,abs(x)))*smooth(.34,.48,z)*(1-smooth(.70,.82,z))
    q[:,0]*=1+.18*breast
    q[:,1]-=.025*breast
    wing=smooth(.22,.38,abs(x));q[:,0]*=1-.08*wing
    # A stronger, moderately long corvid bill rather than the fowl's short beak.
    bill=(y<-.405)&(z>.84)
    q[bill,1]=-.405+(y[bill]+.405)*.78
    head=smooth(.78,.87,z);q[:,0]*=1+.10*head
    # Shorter lower legs and lower neck give a low, forward corvid stance.
    q[:,2]-=.0608*smooth(0,.38,z)+.035*smooth(.69,.86,z)
    tail=smooth(.17,.30,y)*(1-smooth(.48,.58,z))
    dy,dz=y-.18,z-.50;angle=math.radians(22)
    ty=.18+.94*(math.cos(angle)*dy-math.sin(angle)*dz)
    tz=.4392+.94*(math.sin(angle)*dy+math.cos(angle)*dz)
    q[:,1]=q[:,1]*(1-tail)+ty*tail
    q[:,2]=q[:,2]*(1-tail)+tz*tail
    q[:,0]*=1+.16*tail
    return q


def proportions(obj):
    p=np.array([v.co[:] for v in obj.data.vertices]);q=shape(p)
    jac=np.empty((len(p),3,3))
    for axis in range(3):
        d=np.zeros(3);d[axis]=1e-5;jac[:,:,axis]=(shape(p+d)-shape(p-d))/(2e-5)
    inv=np.linalg.inv(jac);n=np.array([v.vector[:] for v in obj.data.corner_normals]);ids=np.array([v.vertex_index for v in obj.data.loops])
    n=np.einsum('ni,nij->nj',n,inv[ids]);length=np.linalg.norm(n,axis=1)
    n[length<1e-8]=[0,0,1];n/=np.maximum(np.linalg.norm(n,axis=1),1e-8)[:,None]
    assert np.isfinite(q).all() and np.isfinite(n).all()
    for v,co in zip(obj.data.vertices,q):v.co=co
    obj.data.normals_split_custom_set(n.tolist());obj.data.update()


def paint(obj):
    for mat in obj.data.materials:
        mat.name='JinwuCharcoalFeathers'
        shader=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
        image=shader.inputs['Base Color'].links[0].from_node.image
        w,h=image.size;px=np.empty(w*h*4,dtype=np.float32);image.pixels.foreach_get(px)
        rgba=px.reshape(h,w,4);old=rgba[:,:,:3].copy();brightness=old.max(axis=2)
        # Retain original UV feather relief and dark eyes; remove white bill,
        # red feet and contrasting brow. Colour never implies source anatomy.
        # Keep feather midtones above the ink shader's solid-ink floor so
        # the black bird still has readable eyes, bill and layered feathers.
        rgb=np.array([.30,.33,.36])*(.65+1.2*brightness[...,None])
        red=(old[:,:,0]>old[:,:,1]*1.30)&(old[:,:,0]>old[:,:,2]*1.30)
        rgb[red]=(np.array([.26,.275,.29])*(.65+.55*brightness[...,None]))[red]
        white=(old.min(axis=2)>.55)&(old.max(axis=2)-old.min(axis=2)<.23)
        rgb[white]=(np.array([.25,.27,.29])*(.8+.2*brightness[...,None]))[white]
        eyes=brightness<.055;rgb[eyes]=old[eyes]*.8
        rgba[:,:,:3]=rgb;image.pixels.foreach_set(rgba.ravel());image.update();image.file_format='PNG';image.pack()
        shader.inputs['Roughness'].default_value=.84


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source');p.add_argument('output');p.add_argument('views');a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
    obj=load(a.source);obj.data.calc_loop_triangles();print('VERIFIED_HIGH_NORMALIZED',len(obj.data.loop_triangles),'triangles')
    proportions(obj);paint(obj);obj.name='jinwu'
    Path(a.output).parent.mkdir(parents=True,exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output,export_format='GLB',use_selection=True,export_animations=False)
    Path(a.views).mkdir(parents=True,exist_ok=True);render_views(obj,setup_render(1024),a.views)


if __name__=='__main__':main()
