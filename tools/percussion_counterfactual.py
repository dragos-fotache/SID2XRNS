#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Separate actual chip-clock phase from source/target write differences."""
import argparse
import bisect
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelity.target import first_playback
from fidelity.reference import digest


def run(metadata, reference, renderer, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    meta = json.loads(Path(metadata).read_text()); ref = json.loads(Path(reference).read_text())
    trace = json.loads(Path(meta['trace']).read_text()); blocks = trace['blocks']
    if trace['overflow']: raise ValueError('Capture overflow')
    first, end = first_playback(blocks); origin = blocks[first]['sample']; starts = [b['sample'] for b in blocks]
    offset = blocks[first]['ppq'] * .48
    samples_end = blocks[end - 1]['sample'] + blocks[end - 1]['size']
    observed = []; actual = []; cycles = 0
    for sample, event_offset, kind, a, b, _ in trace['events']:
        if kind == 4:
            cycles = b
            if origin <= sample <= samples_end:
                observed.append(((sample - origin) / trace['sample_rate'] + offset, cycles, a))
        index = bisect.bisect_right(starts, sample) - 1
        if first <= index < end and kind == 2: actual.append((cycles, a, b))
        if first <= index < end and kind == 3: raise ValueError('Mid-pass reset not supported')
    observed = np.asarray(observed)
    if not len(observed): raise ValueError('Direct ENV3/cycle observations required')
    initial = blocks[max(0, first - 1)]['registers']
    source = []
    for r in ref['writes']:
        sec = (r['cycle'] - ref['first_play_cycle']) / ref['profile']['clock_hz']
        if sec <= observed[-1, 0]:
            # Independent source values/order on the measured target clock.
            cycle = round(float(np.interp(sec, np.r_[0, observed[:, 0]], np.r_[0, observed[:, 1]])))
            source.append((cycle, r['register'], r['value']))
    predictions = {}
    variants = [('actual-writes', actual), ('independent-writes-on-actual-clock', source)]
    for name, registers in [('source-control', {18}), ('source-adsr', {19, 20}),
                            ('source-sr', {20}), ('source-control-and-adsr', {18, 19, 20})]:
        combined = [(when, 1, i, register, value) for i, (when, register, value) in enumerate(actual)
                    if register not in registers]
        combined += [(when, 0, i, register, value) for i, (when, register, value) in enumerate(source)
                     if register in registers]
        variants.append((name, [(when, register, value) for when, _, _, register, value in sorted(combined)]))
    for name, rows in variants:
        timeline = output / (name + '.tsv'); envelope = output / (name + '.env.tsv')
        with timeline.open('x') as out:
            out.write(f'{ref["profile"]["model"]} 48000 {int(observed[-1, 1])} {ref["profile"]["target_clock_hz"]} 1\n')
            for register, value in enumerate(initial): out.write(f'0 {register} {value}\n')
            for when, register, value in rows:
                if when <= observed[-1, 1]: out.write(f'{when} {register} {value}\n')
        subprocess.run([str(Path(renderer).resolve()), str(timeline.resolve()),
                        str((output / (name + '.wav')).resolve()), str(envelope.resolve())], check=True)
        data = np.loadtxt(envelope)
        predictions[name] = np.column_stack((np.interp(data[:, 0], observed[:, 1], observed[:, 0]), data[:, 3]))
    modeled = predictions['actual-writes']
    residual = np.abs(np.interp(observed[:, 0], modeled[:, 0], modeled[:, 1]) - observed[:, 2])
    gate = 0; rows = []
    for r in ref['writes']:
        if r['register'] != 18: continue
        sec = (r['cycle'] - ref['first_play_cycle']) / ref['profile']['clock_hz']
        if r['value'] & 1 and not gate & 1 and 59.75 < sec < 65.75:
            row = {'gate_source_seconds': sec, 'clip_seconds': sec - 59.75}
            actual_peak = observed[(observed[:, 0] >= sec) & (observed[:, 0] < sec + .09)]
            row['actual_peak_seconds'] = float(actual_peak[np.argmax(actual_peak[:, 2]), 0])
            for name, data in predictions.items():
                selected = data[(data[:, 0] >= sec) & (data[:, 0] < sec + .09)]
                row[name + '_peak_seconds'] = float(selected[np.argmax(selected[:, 1]), 0])
            row['independent_minus_actual_peak_ms'] = 1000 * (row['independent-writes-on-actual-clock_peak_seconds'] - row['actual_peak_seconds'])
            rows.append(row)
        gate = r['value']
    result = {'schema': 1, 'renderer_sha256': digest(renderer), 'actual_trace_sha256': digest(meta['trace']),
              'actual_clock_replay_env3_mean_absolute_error': float(np.mean(residual)),
              'actual_clock_replay_env3_fraction_within_3_units': float(np.mean(residual <= 3)),
              'sampling_limit': 'Both diagnostic envelope series have <=1-ms resolution; largest per-sample differences occur on steep edges.',
              'events': rows, 'method': 'Replay actual physical writes at measured cumulative SID cycles; replay independent source writes/order at the same measured target clock, same initial registers and 48000 warm-up samples. No original SID/capture/export is modified.',
              'limits': 'Counterfactual mapped source timestamps to observed target cycle progression; this is causal isolation, not a fidelity score or correction. Raw counterfactual WAV time axes are SID cycles and are not listening artifacts.'}
    (output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('metadata', type=Path); p.add_argument('reference', type=Path)
    p.add_argument('--renderer', type=Path, required=True); p.add_argument('-o', '--output', type=Path, required=True)
    a = p.parse_args(); run(a.metadata, a.reference, a.renderer, a.output)
