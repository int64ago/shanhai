"""Render normalized avian geometry without quadruped posture corrections.
Blender --background --python pipeline/blender/prepare_jingwei.py -- input.glb output_dir
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from turnaround import load, setup_render, render_views

args = sys.argv[sys.argv.index('--') + 1:]
obj = load(args[0])
os.makedirs(args[1], exist_ok=True)
render_views(obj, setup_render(1024), args[1], only_view=args[2] if len(args) > 2 else None)
