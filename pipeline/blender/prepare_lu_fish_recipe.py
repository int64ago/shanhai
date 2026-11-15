"""Formal recipe adapter: declared native High -> reproduced/audited repair4 -> body.out."""
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
from repair_lu_fish_high import repair, audit, sha, SOURCE_SHA

REPAIR_SHA = '367b05b52fb5e3c2f8ffc2e1b556b6f9c2be567bec439b9e214b07108881c9a7'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
    source, output = args.source.resolve(), args.output.resolve()
    assert source.is_relative_to(ROOT/'raw') and sha(source) == SOURCE_SHA
    assert output.is_relative_to(ROOT/'raw/_build') and output.suffix == '.glb' and not output.exists()
    evidence_root = ROOT/'raw/_build/lu_fish'
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix='prepare-', dir=evidence_root))/'repair'
    repair(source, evidence)
    candidate = evidence/'lu_fish_high_local_repair.glb'
    audit(source, candidate, evidence)
    assert sha(candidate) == REPAIR_SHA, 'Reproduced repair differs from frozen, reviewed repair4'
    shutil.copyfile(candidate, output)
    record = {'beast':'lu_fish','sourceSha256':SOURCE_SHA,'frozenRepairSha256':REPAIR_SHA,
              'reproducedFrozenBytes':True,'repairAudit':str(evidence/'actual-export-audit.json'),
              'output':str(output),'apiCalls':0}
    (evidence/'recipe-prepare.json').write_text(json.dumps(record,indent=2)+'\n')
    print('EXPORTED LU_RECIPE_PREPARE '+json.dumps(record),flush=True)

if __name__ == '__main__':
    main()
