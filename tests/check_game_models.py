"""Read-only integration check against user-supplied game dumps or ISOs."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import dds3tool as archive
from model_preview import decode_model


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources',nargs='+')
    args=parser.parse_args()
    failures=0
    for source in args.sources:
        game=archive.GameSource(source)
        passed=0
        for entry in game.files:
            if not entry.path.lower().startswith('model/devil/') or not entry.path.lower().endswith('.pb'):
                continue
            try:
                model=decode_model(game.read(entry),entry.path)
                assert model['nodes'], 'No skeleton'
                for mesh in model['meshes']:
                    n=len(mesh['influences'][0]['positions'])
                    for i in range(n):
                        weight=sum(inf['positions'][i][3] for inf in mesh['influences'])
                        assert abs(weight-1)<.02, f'Skin weights sum to {weight}'
                passed+=1
            except Exception as exc:
                failures+=1;print(f'FAIL {entry.path}: {exc}',flush=True)
        print(f'{source}: {passed} passed',flush=True)
    return bool(failures)


if __name__=='__main__':sys.exit(main())
