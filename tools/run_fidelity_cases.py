#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Measure real private-host exports and deliberate faults with PID/path guards."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / 'probe')]
from host import WORK, call, capture
from fidelity.target import analyze_target
from fidelity.audio import compare_files


def load(name):
    state = call('inspect'); process = json.loads((WORK / 'process.json').read_text())
    assert state['pid'] == process['pid'] and Path(state['file']).parent == WORK
    call('load', name=name)
    for _ in range(100):
        time.sleep(.1)
        state = call('inspect')
        if Path(state['file']).name == name and not state['playing']: return state
    raise RuntimeError('Private scratch song did not finish loading')


def run(label, names):
    directory = WORK / 'fidelity' / label
    directory.mkdir(parents=True, exist_ok=False)
    manifest = []
    for name in names:
        stem = 'fidelity-' + name
        state = load(stem + '-probe.xrns')
        assert [i['alias'] for i in state['instruments']] == [0, 1, 1]
        assert [i['channel'] for i in state['instruments']] == [1, 2, 3]
        assert len(state['instruments'][0]['parameters']) in (68, 81)
        take = label + '-' + name
        capture(argparse.Namespace(name=take, seconds=5.1))
        report = analyze_target(WORK / (take + '.json'), WORK / 'fidelity/cases-reference/reference.json', directory / (name + '.json'))
        manifest.append({'name': name, 'metadata': str(WORK / (take + '.json')),
                         'report': str(directory / (name + '.json')), 'audio': report['audio']})
        print(f'Completed real-host case: {label}/{name}', flush=True)
    (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True)
    parser.add_argument('--cases', nargs='+', default=['correct', 'frozen-release', 'missing-arp-step',
                        'delayed-attacks', 'changed-waveform', 'changed-filter', 'octave-edit'])
    args = parser.parse_args(); run(args.label, args.cases)
