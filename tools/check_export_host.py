#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Check a CLI-generated synthetic song in the real timing-probe host."""
import bisect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'probe')]
from analyze import verify_register_replay
from sid2xrns.trace import read_trace
from sid2xrns.interpret import interpret


def check(metadata, source_trace, output):
    meta = json.loads(Path(metadata).read_text()); t = json.loads(Path(meta['trace']).read_text())
    plan = interpret(read_trace(source_trace))
    assert t['overflow'] == 0
    state = meta['host_state']
    assert state['pid'] == t['pid'] == meta['process']['pid']
    assert [i['alias'] for i in state['instruments']] == [0, 1, 1]
    assert [i['channel'] for i in state['instruments']] == [1, 2, 3]
    bindings = json.loads((ROOT / 'fixtures/sidsynth-bindings.json').read_text())
    assert [p['name'] for p in state['instruments'][0]['parameters'][:67]] == [s['name'] for s in bindings]
    blocks = t['blocks']; starts = [b['sample'] for b in blocks]
    replayed = verify_register_replay(blocks, t['events'])
    playing = [b for b in blocks if b['playing']]
    def seconds(b): return b['ppq'] * .48
    def block_for(sample): return blocks[bisect.bisect_right(starts, sample) - 1]
    events = []
    for e in t['events']:
        b = block_for(e[0])
        if e[2] == 1 and b['playing'] and e[3] & 0xf0 in (0x80, 0x90):
            events.append({'seconds': seconds(b) + e[1] / t['sample_rate'], 'voice': e[3] & 15,
                           'note': e[4] if e[3] & 0xf0 == 0x90 and e[5] else None, 'key': e[4]})
    limit = seconds(playing[-1]) + playing[-1]['size'] / t['sample_rate']
    wanted = []; held = [None] * 3
    for note in plan.notes:
        s = note['units'] / 12800
        if s >= limit: continue
        v = note['voice']; key = note['note']
        if key is not None and held[v] is not None:
            wanted.append({'seconds': s, 'voice': v, 'note': None, 'key': held[v]})
        if key is not None or held[v] is not None:
            wanted.append({'seconds': s, 'voice': v, 'note': key, 'key': key if key is not None else held[v]})
        held[v] = key
    assert len(events) == len(wanted), (events, wanted)
    max_error = 0
    for a, b in zip(events, wanted):
        assert (a['voice'], a['note'], a['key']) == (b['voice'], b['note'], b['key']), (a, b)
        max_error = max(max_error, abs(a['seconds'] - b['seconds']))
    assert max_error <= 1 / t['sample_rate'] + 1e-9, max_error
    # Known original program: voice 1 retunes after OFF, while voice 2 keeps
    # its own gate and note owner. Voice 3 has its own later on/off pair.
    release = [b for b in playing if .05 < seconds(b) < .07]
    assert release
    for b in release:
        f = b['registers'][0] | (b['registers'][1] << 8)
        assert abs(f - 0x2708) <= 5 and b['notes'][0] == -1 and b['registers'][4] & 1 == 0
        assert b['notes'][1] >= 0 and b['registers'][11] & 1
    assert {e['voice'] for e in events if e['note'] is not None} == {0, 1, 2}
    crossed = [b for b in playing if 5.13 < seconds(b) < min(5.3, limit)]
    assert crossed and all(b['notes'][1] >= 0 and b['registers'][11] & 1 for b in crossed)
    result = {'pid': t['pid'], 'source_trace': str(source_trace), 'midi_messages': len(events),
              'max_note_timing_error_seconds': max_error, 'physical_register_replay_blocks': replayed,
              'aliases_channels_verified': True, 'three_voices_received_notes': True,
              'release_pitch_and_channel_isolation': True, 'sustained_voice_crosses_pattern_boundary': True,
              'passed': True}
    Path(output).write_text(json.dumps(result, indent=2) + '\n'); print(json.dumps(result, indent=2))


if __name__ == '__main__':
    if len(sys.argv) != 4: raise SystemExit('usage: check_export_host.py METADATA CAPTURE OUTPUT')
    check(*sys.argv[1:])
