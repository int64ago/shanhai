"""Formal body_norm.glb/body_rig.glb adapter around the reviewed native Lu rig."""
import sys
sys.dont_write_bytecode = True
import argparse
import json
from pathlib import Path
import shutil
import tempfile

TRUSTED = Path(__file__).resolve().parent
ROOT = TRUSTED.parent.parent
sys.path.insert(0, str(TRUSTED))
import rig_lu_fish_native as native


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--preview', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    source, output = args.source.resolve(), args.output.resolve()
    assert source.is_relative_to(ROOT/'raw/_build') and native.sha(source) == native.SOURCE_SHA
    assert output.is_relative_to(ROOT/'raw/_build') and output.suffix == '.glb' and not output.exists()
    evidence_root = ROOT/'raw/_build/lu_fish'
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix='rig-', dir=evidence_root))/'native'
    previous_argv = sys.argv
    try:
        sys.argv = [str(TRUSTED/'rig_lu_fish_native.py'),'--',str(source),str(evidence)]
        native.main()
    finally:
        sys.argv = previous_argv
    shutil.copyfile(evidence/'rigged.glb',output)
    if args.preview:
        preview = args.preview.resolve()
        assert preview.is_relative_to(ROOT/'raw/_build')
        shutil.copyfile(evidence/'idle-0.png',preview)
    record = {'beast':'lu_fish','sourceSha256':native.sha(source),'riggedSha256':native.sha(output),
              'nativeAudit':str(evidence/'audit.json'),'restReference':str(evidence/'rest-reference.json'),
              'output':str(output),'apiCalls':0}
    (evidence/'recipe-rig.json').write_text(json.dumps(record,indent=2)+'\n')
    print('EXPORTED LU_RECIPE_RIG '+json.dumps(record),flush=True)

if __name__ == '__main__':
    main()
