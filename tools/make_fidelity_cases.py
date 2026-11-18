#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Original known-event SID plus deliberately damaged native exports."""
import copy
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.sid_fixtures import psid, store
from sid2xrns.psid import read
from sid2xrns.capture import capture
from sid2xrns.trace import read_trace
from sid2xrns.interpret import interpret
from sid2xrns.xrns import write_song

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    init = store(0x00f0, 0) + store(0xd418, 31)
    for base in (0xd400, 0xd407, 0xd40e):
        init += store(base + 5, 0x28) + store(base + 6, 0xcf)
    init += store(0xd409, 0) + store(0xd40a, 8) + store(0xd417, 0x32) + store(0xd416, 0xa0) + b'\x60'
    def freq(base, value): return store(base, value & 255) + store(base + 1, value >> 8)
    actions = {
        1: freq(0xd400, 7493) + store(0xd404, 0x21) + freq(0xd407, 2228) + store(0xd40b, 0x41),
        26: store(0xd404, 0x20),
        51: freq(0xd400, 10002),
        76: freq(0xd400, 11900) + store(0xd416, 0x38),
        101: freq(0xd400, 5613) + store(0xd404, 0x21) + store(0xd40b, 0x40),
        126: store(0xd404, 0x20) + freq(0xd40e, 16000) + store(0xd412, 0x81),
        151: store(0xd412, 0x80),
        176: freq(0xd40e, 6301) + store(0xd412, 0x11) + store(0xd417, 0x74),
        201: store(0xd412, 0x10),
        226: store(0xd418, 24),
    }
    # Absolute jumps avoid branch-distance limits; all programs are original.
    code = bytearray(b'\xee\xf0\x00\xad\xf0\x00'); jumps = []
    for call in actions:
        code.extend([0xc9, call, 0xd0, 3, 0x4c, 0, 0]); jumps.append(len(code) - 2)
    code.append(0x60)
    for operand, action in zip(jumps, actions.values()):
        address = 0x1000 + len(init) + len(code)
        code[operand:operand + 2] = address.to_bytes(2, 'little')
        code.extend(action + b'\x60')
    return psid(init, bytes(code))


def make(output):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    sid_path = output / 'fidelity.sid'; sid_path.write_bytes(fixture())
    sid = read(sid_path); trace_path = output / 'fidelity.capture.jsonl.gz'
    capture(sid, sid.profile(), 240, trace_path)
    performance = interpret(read_trace(trace_path))
    variants = {'correct': performance}
    # Faults alter exported notes/controls; no source/reference or capture data
    # is changed. They are audible in real Renoise, not fabricated recordings.
    p = copy.deepcopy(performance)
    points = p.automation['voice1.tuning']
    release = next(n['units'] for n in p.notes if n['voice'] == 0 and n['note'] is None)
    resume = next(n['units'] for n in p.notes if n['voice'] == 0 and n['note'] is not None and n['units'] > release)
    at_release = points[max(k for k in points if k <= release)]
    for key in list(points):
        if release < key < resume: points[key] = at_release
    variants['frozen-release'] = p
    p = copy.deepcopy(performance)
    points = p.automation['voice1.tuning']
    keys = [k for k in points if 12000 < k < 18000]
    for key in keys:
        points[key] = points[max(k for k in points if k < 12000)]
    variants['missing-arp-step'] = p
    p = copy.deepcopy(performance)
    for note in p.notes:
        if note['voice'] == 2 and note['note'] is not None: note['units'] += 256
    variants['delayed-attacks'] = p
    p = copy.deepcopy(performance)
    for field, value in (('saw', 0), ('triangle', 1)):
        p.initial['voice1.' + field] = value
        p.automation['voice1.' + field] = {k: value for k in p.automation['voice1.' + field]}
    variants['changed-waveform'] = p
    p = copy.deepcopy(performance)
    p.initial['filter.cutoff'] = 80
    p.automation['filter.cutoff'] = {k: 80 for k in p.automation['filter.cutoff']}
    variants['changed-filter'] = p
    p = copy.deepcopy(performance)
    for note in p.notes:
        if note['voice'] == 1 and note['note'] is not None: note['note'] += 12
    variants['octave-edit'] = p
    for name, variant in variants.items():
        for diagnostic in (False, True):
            write_song(variant, output / (name + ('-probe' if diagnostic else '') + '.xrns'), diagnostic)
    manifest = {'play_calls': 240, 'duration_seconds': 240 * 19656 / 985248,
                'variants': list(variants), 'release_units': release, 'resume_units': resume,
                'faults_applied_to': 'native musical notes/automation only'}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__': make(sys.argv[1])
