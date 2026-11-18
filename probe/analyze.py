#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Measure delivered host events and physical SID writes against the fixture."""
import argparse
import bisect
import json
import math
from pathlib import Path
import struct
import wave


def verify_register_replay(blocks, events):
    starts = [b['sample'] for b in blocks]
    grouped = {}
    for event in events:
        if event[2] in (2, 3):
            grouped.setdefault(bisect.bisect_right(starts, event[0]) - 1, []).append(event)
    registers = list(blocks[0]['registers'])
    for i, block in enumerate(blocks[1:], 1):
        for sample, offset, kind, address, value, _ in grouped.get(i, []):
            assert 0 <= offset < block['size'] and sample == block['sample'] + offset
            if kind == 3: registers = [0] * 25
            else:
                assert 0 <= address < 25 and 0 <= value <= 255
                registers[address] = value
        assert registers == block['registers'], ('Physical-write replay differs from engine registers', i)
    return len(blocks) - 1


def analyze(metadata, expected_file, output):
    meta = json.loads(metadata.read_text())
    trace_path = Path(meta['trace'])
    trace = json.loads(trace_path.read_text())
    expected = json.loads(expected_file.read_text())
    assert trace['overflow'] == 0, 'Trace storage overflow; measurements are invalid'
    host = meta['host_state']
    assert host['pid'] == trace['pid'] == meta['process']['pid']
    assert [i['alias'] for i in host['instruments']] == [0, 1, 1]
    assert [i['channel'] for i in host['instruments']] == [1, 2, 3]
    names = [s['name'] for s in expected['bindings']]
    assert [p['name'] for p in host['instruments'][0]['parameters'][:67]] == names
    assert host['instruments'][0]['parameters'][-1]['name'] == 'Capture'
    rate = trace['sample_rate']
    blocks = trace['blocks']; starts = [b['sample'] for b in blocks]
    replay_blocks = verify_register_replay(blocks, trace['events'])
    playing = [b for b in blocks if b['playing']]
    assert playing and all(b['ppq'] >= 0 for b in playing)
    specs = {s['id']: (i, s) for i, s in enumerate(expected['bindings'])}
    def time_of(block): return block['ppq'] * 60 / 125
    def block_for(sample):
        b = blocks[bisect.bisect_right(starts, sample) - 1]
        assert b['sample'] <= sample < b['sample'] + b['size']
        return b
    midi = []
    for sample, offset, kind, status, key, velocity in trace['events']:
        b = block_for(sample)
        if kind == 1 and b['playing'] and status & 0xf0 in (0x80, 0x90):
            midi.append({'voice': status & 15, 'note': key if status & 0xf0 == 0x90 and velocity else None, 'key': key,
                         'seconds': time_of(b) + offset / rate, 'offset': offset, 'sample': sample})
    wanted_midi = []; held = [None] * 3
    for event in sorted(expected['notes'], key=lambda n: (n['seconds'], n['voice'])):
        v, note = event['voice'], event['note']
        if note is not None and held[v] is not None:
            wanted_midi.append({**event, 'note': None, 'key': held[v], 'implicit_replacement_off': True})
        wanted_midi.append({**event, 'key': note if note is not None else held[v]})
        held[v] = note
    assert len(midi) == len(wanted_midi), (len(midi), len(wanted_midi))
    note_results = []
    for actual, wanted in zip(sorted(midi, key=lambda m: (m['seconds'], m['voice'])), wanted_midi):
        assert actual['voice'] == wanted['voice'] and actual['note'] == wanted['note'] and actual['key'] == wanted['key'], (actual, wanted)
        note_results.append({**wanted, 'actual': actual['seconds'],
                             'error_ms': (actual['seconds'] - wanted['represented']) * 1000,
                             'offset': actual['offset']})
    transitions = {}
    for key, (i, spec) in specs.items():
        previous = None
        for b in playing:
            value = b['parameters'][i]
            if previous is None or abs(value - previous) > max(spec['step'] * .25, 1e-6):
                transitions.setdefault(key, []).append({'seconds': time_of(b), 'value': value,
                                                       'sample': b['sample']})
            previous = value
    # Count significant source value changes; repeated equal-valued writes are
    # not lost transitions. Associate each observed transition at most once.
    previous = dict(expected['initial']); desired = []
    for event in sorted(expected['automation'], key=lambda x: x['seconds']):
        key = event['id']
        if event['value'] != previous[key]: desired.append(event)
        previous[key] = event['value']
    matches = []; consumed = set()
    for event in desired:
        key = event['id']; _, spec = specs[key]
        candidates = [(abs(t['seconds'] - event['represented']), j, t)
                      for j, t in enumerate(transitions[key])
                      if (key, j) not in consumed and abs(t['value'] - event['value']) < max(spec['step'] * .51, 1e-5)
                      and abs(t['seconds'] - event['represented']) < .05]
        found = min(candidates, default=None)
        row = dict(event)
        if found:
            _, j, actual = found; consumed.add((key, j))
            row.update(actual=actual['seconds'], error_ms=(actual['seconds'] - event['represented']) * 1000)
        else: row.update(actual=None, error_ms=None)
        matches.append(row)
    groups = {}
    for group in sorted({r['group'] for r in matches}):
        rows = [r for r in matches if r['group'] == group]
        errors = [r['error_ms'] for r in rows if r['actual'] is not None]
        groups[group] = {'requested_changes': len(rows), 'observed_changes': len(errors),
                         'missing': len(rows) - len(errors),
                         'min_error_ms': min(errors) if errors else None,
                         'max_error_ms': max(errors) if errors else None}
    # Release pitch must reach physical SID frequency registers with no gate or
    # active note ownership. This checks hardware output, not just GUI values.
    release = []
    for event in [e for e in matches if e['group'] == 'release' and e['actual'] is not None]:
        value = event['value']; i = specs[event['id']][0]
        b = min((b for b in playing if abs(b['parameters'][i] - value) < .01 and
                 abs(time_of(b) - event['actual']) < .001), key=time_of)
        expected_freq = round(440 * 2 ** ((60 - 69 + value) / 12) * 16777216 / 985248)
        frequency = b['registers'][7] + (b['registers'][8] << 8)
        ok = frequency == expected_freq and b['notes'][1] == -1 and b['registers'][11] & 1 == 0
        release.append({'tuning': value, 'frequency': frequency, 'expected': expected_freq,
                        'gate': b['registers'][11] & 1, 'owner': b['notes'][1], 'passed': ok})
    assert release and all(r['passed'] for r in release), release
    hardware_checks = []
    for event in [e for e in matches if e['actual'] is not None]:
        key = event['id']
        b = min(playing, key=lambda b: abs(time_of(b) - event['actual']))
        r = b['registers']; wanted = event['value']; actual = None
        if key == 'filter.cutoff': actual = (r[21] & 7) | (r[22] << 3)
        elif key.startswith('voice'):
            v = int(key[5]) - 1; field = key.split('.')[1]; base = 7 * v
            if field == 'pulseWidth': actual = r[base + 2] | ((r[base + 3] & 15) << 8)
            elif field == 'release': actual = r[base + 6] & 15
            elif field in ('saw', 'pulse', 'noise', 'test'):
                actual = int(bool(r[base + 4] & {'saw': 32, 'pulse': 64, 'noise': 128, 'test': 8}[field]))
            elif field == 'tuning':
                note = [n['note'] for n in expected['notes'] if n['voice'] == v and n['note'] is not None
                        and n['represented'] <= event['actual']][-1]
                wanted = round(440 * 2 ** ((note - 69 + wanted) / 12) * 16777216 / 985248)
                actual = r[base] | (r[base + 1] << 8)
        if actual is not None:
            assert actual == wanted, (event, actual, wanted)
            hardware_checks.append({'id': key, 'seconds': event['actual'], 'actual': actual, 'expected': wanted})
    physical = []
    for sample, offset, kind, address, value, _ in trace['events']:
        b = block_for(sample)
        if b['playing'] and kind in (2, 3):
            assert 0 <= offset < b['size']
            physical.append({'seconds': time_of(b) + offset / rate, 'kind': kind,
                             'address': address, 'value': value, 'offset': offset})
    assert any(e['kind'] == 2 for e in physical), 'No physical SID writes captured'
    percussion = [e for e in physical if 2.46 <= e['seconds'] <= 2.6 and
                  e['kind'] == 2 and e['address'] in (18, 19, 20)]
    # Actual processor samples captured before the diagnostic's silent output.
    data = trace_path.with_suffix('.f32').read_bytes()
    samples = struct.unpack(f'<{len(data) // 4}f', data)
    assert len(samples) == trace['frames'] and all(math.isfinite(x) for x in samples)
    before = samples[:playing[0]['sample']]
    after_blocks = [b for b in blocks if not b['playing'] and b['sample'] > playing[-1]['sample']]
    after = samples[after_blocks[0]['sample']:] if after_blocks else ()
    result = {'rate': rate, 'pid': trace['pid'], 'requested_quantum': meta['process']['requested_quantum'],
              'actual_callback_sizes': sorted({b['size'] for b in playing}), 'overflow': trace['overflow'],
              'bindings_verified': len(names), 'note_count': len(expected['notes']), 'midi_note_count': len(midi),
              'note_max_abs_error_ms': max(abs(n['error_ms']) for n in note_results),
              'source_quantization_max_ms': max(abs(n['seconds'] - n['represented']) * 1000 for n in expected['notes'] + expected['automation']),
              'automation_groups': groups, 'release': release, 'notes': note_results,
              'automation': matches, 'physical_writes': physical, 'percussion_writes': percussion,
              'hardware_checks': len(hardware_checks),
              'register_replay_blocks_verified': replay_blocks,
              'silent_before_play': bool(before) and max(map(abs, before)) == 0,
              'silent_after_stop': bool(after) and max(map(abs, after)) == 0,
              'audio_peak': max(map(abs, samples)), 'trace': str(trace_path)}
    assert result['silent_before_play'] and result['silent_after_stop'], 'Initialization/stop leaked audio'
    assert result['note_max_abs_error_ms'] <= 1000 / rate + 1e-6, 'Note timing exceeds one output sample'
    output.write_text(json.dumps(result, indent=2) + '\n')
    with wave.open(str(output.with_suffix('.wav')), 'wb') as w:
        w.setparams((1, 2, int(rate), 0, 'NONE', 'not compressed'))
        w.writeframes(b''.join(struct.pack('<h', max(-32768, min(32767, round(x * 32767)))) for x in samples))
    summary = {k: result[k] for k in ['rate', 'requested_quantum', 'actual_callback_sizes', 'note_count',
                                     'note_max_abs_error_ms', 'automation_groups', 'silent_before_play', 'silent_after_stop', 'audio_peak']}
    print(json.dumps(summary, indent=2))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('metadata', type=Path); p.add_argument('expected', type=Path); p.add_argument('output', type=Path)
    a = p.parse_args(); analyze(a.metadata, a.expected, a.output)
