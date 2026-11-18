# SPDX-License-Identifier: AGPL-3.0-only
"""Evaluate physical host writes against the independent source timeline."""
import bisect
import json
from pathlib import Path
import numpy as np
from .reference import digest


def states_at(writes, times, initial=None):
    state = list(initial or [0] * 25)
    values = [state.copy()]; clocks = [-float('inf')]
    for when, register, value in writes:
        if when < clocks[-1]:
            raise ValueError('Nonmonotonic physical timeline; split transport restarts before comparing')
        if register is None: state = [0] * 25
        else: state[register] = value
        values.append(state.copy()); clocks.append(when)
    return np.asarray(values, dtype=np.uint8)[np.searchsorted(clocks, times, side='right') - 1]


def first_playback(blocks):
    first = next((i for i, b in enumerate(blocks) if b['playing']), None)
    if first is None: raise ValueError('Diagnostic has no playing transport pass')
    end = first + 1
    while end < len(blocks) and blocks[end]['playing'] and blocks[end]['ppq'] >= blocks[end - 1]['ppq']:
        end += 1
    return first, end


def fields(r):
    r = r.astype(np.int32)
    result = {'filter.cutoff': r[:, 21] & 7 | r[:, 22] << 3,
              'filter.resonance-routing': r[:, 23], 'chip.volume': r[:, 24] & 15,
              'filter.modes-voice3': r[:, 24] & 0xf0}
    for v in range(3):
        b = 7 * v; p = f'voice{v + 1}.'
        result[p + 'frequency'] = r[:, b] | r[:, b + 1] << 8
        result[p + 'pulseWidth'] = r[:, b + 2] | (r[:, b + 3] & 15) << 8
        result[p + 'AD'] = r[:, b + 5]; result[p + 'SR'] = r[:, b + 6]
        result[p + 'gate'] = r[:, b + 4] & 1
        result[p + 'waveform'] = r[:, b + 4] & 0xf0
        result[p + 'sync-ring-test'] = r[:, b + 4] & 14
    return result


def analyze_target(metadata, reference, output, step=.0005):
    output = Path(output)
    if output.exists() or output.with_suffix('.wav').exists():
        raise ValueError('Choose fresh target report/audio paths')
    from probe.analyze import verify_register_replay
    meta = json.loads(Path(metadata).read_text()); ref = json.loads(Path(reference).read_text())
    t = json.loads(Path(meta['trace']).read_text())
    if t['overflow']:
        raise ValueError('Target diagnostic overflowed; incomplete traces cannot establish fidelity')
    if t['pid'] != meta['process']['pid'] or t['sample_rate'] != 48000:
        raise ValueError('Target PID/rate mismatch')
    specs = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/sidsynth-bindings.json').read_text())
    if [p['name'] for p in meta['host_state']['instruments'][0]['parameters'][:67]] != [p['name'] for p in specs]:
        raise ValueError('Target parameter bindings changed')
    indices = {p['id']: i for i, p in enumerate(specs)}
    for key, value in [('chip.model', int(ref['profile']['model'] == '8580')),
                       ('chip.clock', int(ref['profile']['clock'] == 'ntsc'))]:
        if any(b['parameters'][indices[key]] != value for b in t['blocks'] if b['playing']):
            raise ValueError('Target model/clock differs from independent reference')
    replay = verify_register_replay(t['blocks'], t['events'])
    blocks = t['blocks']; starts = [b['sample'] for b in blocks]
    first_block, end_block = first_playback(blocks)
    initial_target = blocks[max(0, first_block - 1)]['registers']
    target = []
    for sample, offset, kind, a, b, _ in t['events']:
        if kind not in (2, 3): continue
        index = bisect.bisect_right(starts, sample) - 1
        block = blocks[index]
        if first_block <= index < end_block:
            seconds = block['ppq'] * .48 + offset / t['sample_rate']
            target.append((seconds, a if kind == 2 else None, b))
    duration = (ref['end_cycle'] - ref['first_play_cycle']) / ref['profile']['clock_hz']
    playing = blocks[first_block:end_block]
    available = max(b['ppq'] * .48 + b['size'] / t['sample_rate'] for b in playing)
    duration = min(duration, available)
    times = np.arange(0, duration, step)
    origin, hz = ref['first_play_cycle'], ref['profile']['clock_hz']
    source = [((r['cycle'] - origin) / hz, r['register'], r['value']) for r in ref['writes']]
    initial = [0] * 25
    for r in ref['initial_writes']: initial[r['register']] = r['value']
    x, y = fields(states_at(source, times, initial)), fields(states_at(target, times, initial_target))
    rows = {}; seconds_bins = np.zeros(int(np.ceil(duration)))
    for name, value in x.items():
        error = np.abs(y[name] - value)
        tolerance = np.maximum(1, value * .0005) if name.endswith('.frequency') else 0
        bad = error > tolerance
        seconds_bins += np.bincount(times[bad].astype(int), minlength=len(seconds_bins))[:len(seconds_bins)]
        indices = np.flatnonzero(bad)
        row = {'mismatch_fraction': float(np.mean(bad)), 'mismatch_seconds': float(np.sum(bad) * step),
               'max_absolute_difference': int(np.max(error)), 'first_mismatch_seconds': float(times[indices[0]]) if len(indices) else None}
        if name.endswith('.frequency'):
            row['source_zero_frequency_mismatch_seconds'] = float(np.sum(bad & (value == 0)) * step)
            row['source_nonzero_frequency_mismatch_seconds'] = float(np.sum(bad & (value != 0)) * step)
            row['tolerance'] = 'max(1 SID register unit, 0.05% of reference frequency word)'
        rows[name] = row
    # Save sample-aligned internal output; this is real Renoise processing, not
    # a reconstruction from the source. Product recording is compared separately.
    raw = np.fromfile(Path(meta['trace']).with_suffix('.f32'), dtype=np.float32)
    first = playing[0]['sample']
    count = min(round(duration * t['sample_rate']), len(raw) - first)
    from scipy.io import wavfile
    audio_path = Path(output).with_suffix('.wav')
    wavfile.write(audio_path, t['sample_rate'], raw[first:first + count])
    result = {'schema': 1, 'pid': t['pid'], 'sample_rate': t['sample_rate'], 'overflow': t['overflow'],
              'device_quantum_requested': meta['process']['requested_quantum'],
              'callback_sizes': sorted(set(b['size'] for b in playing)),
              'transport_pass': 'first contiguous forward-playing pass; later loops excluded',
              'physical_register_replay_blocks': replay, 'physical_writes': len(target),
              'compared_seconds': duration, 'reference_seconds': (ref['end_cycle'] - origin) / hz,
              'sampling_step_seconds': step, 'fields': rows,
              'worst_seconds': [{'seconds': int(i), 'mismatched_field_grid_cells': int(seconds_bins[i])}
                                for i in np.argsort(seconds_bins)[::-1][:12]],
              'audio': str(audio_path), 'trace_sha256': digest(meta['trace']),
              'metadata_sha256': digest(metadata), 'reference_sha256': digest(reference),
              'limitations': '0.5-ms state grid localizes reductions; does not prove all fast edges/order. Physical replay is checked separately. Audio is from the real processor in a diagnostic wrapper.'}
    Path(output).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: result[k] for k in ('pid', 'physical_writes', 'compared_seconds', 'worst_seconds')}, indent=2))
    return result
