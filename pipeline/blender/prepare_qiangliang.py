"""Unified offline recipe: bounded native body repair plus existing High serpent.

Called by build_beast.sh with explicit recipe.prepareArgs; no API requests.
The rig stage performs the body's final uniform 1.65 m normalization.
"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare_qiangliang_native as geometry
import repair_qiangliang_textures as textures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--body-in', required=True)
    parser.add_argument('--snake-in', required=True)
    parser.add_argument('--body-out', required=True)
    parser.add_argument('--snake-out', required=True)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    body_in, snake_in, body_out, snake_out = [Path(p).resolve() for p in
        (args.body_in, args.snake_in, args.body_out, args.snake_out)]
    for source in (body_in, snake_in):
        if not source.is_file():
            raise FileNotFoundError(source)
    body_out.parent.mkdir(parents=True, exist_ok=True)
    snake_out.parent.mkdir(parents=True, exist_ok=True)
    smoothed = body_out.parent / 'smoothed' / 'body.glb'
    geometry.main([str(body_in), str(smoothed)])
    textures.main([str(smoothed), str(body_out)])

    # Reproduce the reviewed mother from the original High, never public/models.
    # Runtime sizes each instance by height, so retain the original normalization
    # length of 1.0 rather than applying the instance's 0.46 m design size twice.
    argv = sys.argv
    try:
        sys.argv = ['normalize.py', '--', str(snake_in), str(snake_out), '--length', '1.0']
        runpy.run_path(str(Path(__file__).with_name('normalize.py')), run_name='__main__')
    finally:
        sys.argv = argv
    report = {
        'bodySource': str(body_in),
        'bodySourceSha256': hashlib.sha256(body_in.read_bytes()).hexdigest(),
        'snakeSource': str(snake_in),
        'snakeSourceSha256': hashlib.sha256(snake_in.read_bytes()).hexdigest(),
        'bodyOutputSha256': hashlib.sha256(body_out.read_bytes()).hexdigest(),
        'snakeOutputSha256': hashlib.sha256(snake_out.read_bytes()).hexdigest(),
        'geometry': json.loads(smoothed.with_suffix('.json').read_text()),
        'textures': json.loads(body_out.with_suffix('.json').read_text()),
        'additionalPaidCalls': 0,
    }
    body_out.with_name('prepare-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    # The unified builder removes its temporary run directory on exit.
    body_out.parent.parent.joinpath('prepare-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print('EXPORTED', body_out, snake_out, flush=True)


if __name__ == '__main__':
    main()
