"""Correct fresh Bifang Medium parts before the four-view HIGH gate.
Keeps source UVs: rounded avian belly, centered single leg and feathered root.
Usage: blender -b --python prepare_bifang.py -- body|leg|wing in.glb out.glb views
"""
import argparse, math, sys
from pathlib import Path
import bpy
from mathutils import Vector
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from turnaround import load, setup_render, render_views


def ease(a,b,x):
    t=max(0,min(1,(x-a)/(b-a)));return t*t*(3-2*t)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('part',choices=['body','leg','wing']);p.add_argument('input');p.add_argument('output');p.add_argument('views')
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);o=load(a.input)
    pts=[v.co for v in o.data.vertices];lo,hi=[Vector(tuple(fn(v[i] for v in pts) for i in range(3))) for fn in (min,max)]
    print('INPUT_BOUNDS',tuple(lo),tuple(hi))
    if a.part=='body':
        # The text model ends in a flat bust. Gather the lower feather skirt
        # into an oval belly, retaining the feather UV and long crane neck.
        for v in o.data.vertices:
            q=v.co;w=1-ease(.01,.31,q.z)
            rho=min(1.4,(q.x/.36)**2+((q.y-.10)/.40)**2)
            q.z+=.16*rho*w
            q.x*=1-.25*w
            q.y=.10+(q.y-.10)*(1-.18*w)
        # Slightly longer crane body, narrower than the generated bust.
        for v in o.data.vertices:v.co.x*=.86
    elif a.part=='leg':
        height=hi.z-lo.z
        for v in o.data.vertices:
            q=v.co;q*=.70/height
        # Thigh root is buried in the belly at final assembly. Replace its
        # exposed anatomical-study pink with dark feather blue, not bare flesh.
        mat=bpy.data.materials.new('Bifang feathered thigh blue');mat.diffuse_color=(.018,.19,.24,1)
        mat.use_nodes=True;mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.018,.19,.24,1)
        o.data.materials.append(mat)
        for f in o.data.polygons:
            if f.center.z>.39:f.material_index=len(o.data.materials)-1
        for v in o.data.vertices:
            q=v.co
            # Natural backward hock without straight-column silhouette.
            q.y+=.045*math.sin(math.pi*min(1,q.z/.70))
    # Feather blades retain generated thickness; never squash into planes.
    # Preserve the generated winding on non-manifold overlapping feather shells.
    o.data.update()
    for f in o.data.polygons:f.use_smooth=True
    Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.views).mkdir(parents=True,exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=a.output,export_format='GLB',export_animations=False)
    cam=setup_render(768);render_views(o,cam,a.views)

if __name__=='__main__':main()
