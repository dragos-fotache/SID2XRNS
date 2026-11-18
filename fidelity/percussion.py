# SPDX-License-Identifier: AGPL-3.0-only
"""Focused percussion report using actual non-mutating ENV3 observations."""
import json
import os
from pathlib import Path
import numpy as np
from .target import first_playback
from .reference import digest


def analyze(metadata, reference, source_envelopes, output, start=59.75, length=6):
    meta = json.loads(Path(metadata).read_text()); ref = json.loads(Path(reference).read_text())
    trace = json.loads(Path(meta['trace']).read_text())
    if trace['overflow']: raise ValueError('Envelope capture overflow')
    first, end = first_playback(trace['blocks'])
    b = trace['blocks'][first]; origin = b['sample']; offset = b['ppq'] * .48
    last_sample = trace['blocks'][end - 1]['sample'] + trace['blocks'][end - 1]['size']
    observed = [((e[0] - origin) / trace['sample_rate'] + offset, e[3], e[4])
                for e in trace['events'] if e[2] == 4 and origin <= e[0] <= last_sample]
    if not observed: raise ValueError('No actual ENV3 readback was captured')
    observed = np.asarray(observed)
    source = np.loadtxt(source_envelopes); source[:, 0] /= ref['profile']['target_clock_hz']
    gate = 0; onsets = []
    for row in ref['writes']:
        if row['register'] == 18:
            when = (row['cycle'] - ref['first_play_cycle']) / ref['profile']['clock_hz']
            if row['value'] & 1 and not gate & 1 and start <= when < start + length:
                onsets.append(when)
            gate = row['value']
    rows = []
    for when in onsets:
        x = source[(source[:, 0] >= when) & (source[:, 0] < when + .09)]
        y = observed[(observed[:, 0] >= when) & (observed[:, 0] < when + .09)]
        if not len(x) or not len(y): raise ValueError('Incomplete percussion envelope window')
        a = x[np.argmax(x[:, 3])]; b = y[np.argmax(y[:, 1])]
        rows.append({'gate_source_seconds': when, 'clip_seconds': when - start,
                     'controlled_source_peak_seconds': float(a[0]), 'actual_host_peak_seconds': float(b[0]),
                     'peak_difference_ms': float((b[0] - a[0]) * 1000),
                     'source_peak_env3': int(a[3]), 'actual_peak_env3': int(b[1])})
    hz = ref['profile']['target_clock_hz']
    first_clock = observed[0]; last_clock = observed[-1]
    core_hz = (last_clock[2] - first_clock[2]) / (last_clock[0] - first_clock[0])
    result = {'schema': 1, 'pid': trace['pid'], 'requested_quantum': meta['process']['requested_quantum'],
              'window_source_seconds': [start, start + length], 'events': rows,
              'large_peak_deviations': [r for r in rows if abs(r['peak_difference_ms']) > 10],
              'observed_core_cycles_per_audio_second': float(core_hz), 'nominal_clock_hz': hz,
              'source_envelopes_sha256': digest(source_envelopes), 'actual_trace_sha256': digest(meta['trace']),
              'method': 'Actual processor ENV3 peek at chunks <=48 output samples; source envelope uses independent VICE writes in the pinned core with controlled initialization. No phase-fitting or time-warping.',
              'limits': 'Envelope peak is not the audible onset. Controlled core initialization and effective resampler clock remain confounds; source VICE audio and user listening are separate evidence.'}
    output = Path(output)
    with output.open('x') as stream: stream.write(json.dumps(result, indent=2) + '\n')
    os.environ.setdefault('MPLCONFIGDIR', str(output.parent.resolve() / '.matplotlib-cache'))
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), constrained_layout=True)
    for axis, duration in zip(axes, (length, 1)):
        x = source[(source[:, 0] >= start) & (source[:, 0] < start + duration)]
        y = observed[(observed[:, 0] >= start) & (observed[:, 0] < start + duration)]
        axis.plot(x[:, 0] - start, x[:, 3], label='Independent writes, controlled core')
        axis.plot(y[:, 0] - start, y[:, 1], label='Actual Renoise ENV3', alpha=.8)
        axis.set(xlabel='Seconds within posted excerpt', ylabel='ENV3 (0–255)',
                 title='Percussion envelope timing; peaks are not identical to audible onsets')
        axis.legend()
    fig.savefig(output.with_suffix('.png'), dpi=150); plt.close(fig)
    print(json.dumps({k: result[k] for k in ('large_peak_deviations', 'observed_core_cycles_per_audio_second')}, indent=2))
    return result
