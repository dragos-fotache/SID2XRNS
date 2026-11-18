#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Control the chip-core confound using independent VICE or real host writes."""
import argparse
import bisect
import json
from pathlib import Path
import subprocess
import sys
import math
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelity.reference import digest
from fidelity.target import first_playback


def render(reference, output, renderer, target=None):
    ref = json.loads(Path(reference).read_text()); output = Path(output)
    timeline = output.with_suffix('.writes.tsv'); provenance = output.with_suffix('.json')
    if any(p.exists() for p in (output, timeline, provenance)):
        raise ValueError('Choose fresh core-reference paths')
    hz = ref['profile']['target_clock_hz']
    duration = (ref['end_cycle'] - ref['first_play_cycle']) / ref['profile']['clock_hz']
    initial = [0] * 25
    for r in ref['initial_writes']: initial[r['register']] = r['value']
    rows = [(round((r['cycle'] - ref['first_play_cycle']) * hz / ref['profile']['clock_hz']), r['register'], r['value'])
            for r in ref['writes']]
    if target:
        meta = json.loads(Path(target).read_text()); t = json.loads(Path(meta['trace']).read_text())
        if t['overflow']: raise ValueError('Incomplete target trace')
        blocks = t['blocks']; first, end = first_playback(blocks)
        duration = min(duration, blocks[end - 1]['ppq'] * .48 + blocks[end - 1]['size'] / t['sample_rate'])
        initial = blocks[max(0, first - 1)]['registers']; starts = [b['sample'] for b in blocks]
        rows = []
        for sample, offset, kind, a, b, _ in t['events']:
            index = bisect.bisect_right(starts, sample) - 1
            if first <= index < end and kind == 2:
                seconds = blocks[index]['ppq'] * .48 + offset / t['sample_rate']
                if seconds < duration: rows.append((round(seconds * hz), a, b))
            elif first <= index < end and kind == 3:
                raise ValueError('A mid-pass chip reset requires explicit reset replay support')
    with timeline.open('x') as out:
        out.write(f'{ref["profile"]["model"]} 48000 {round(duration * hz)} {hz} 0.251188643150958\n')
        for reg, value in enumerate(initial): out.write(f'0 {reg} {value}\n')
        for when, reg, value in rows: out.write(f'{when} {reg} {value}\n')
    envelope = output.with_suffix('.envelopes.tsv')
    if envelope.exists(): raise ValueError('Choose a fresh envelope output path')
    subprocess.run([str(Path(renderer).resolve()), str(timeline.resolve()), str(output.resolve()), str(envelope.resolve())], check=True)
    # Pinned SincResampler uses two truncated 10-bit cycle/sample ratios.
    # Cycle-clocked output therefore has a known effective rate, slightly above
    # the requested 48 kHz. Convert this physical clock to the WAV time axis;
    # never fit a variable warp to reference/result similarities.
    import numpy as np
    from scipy.io import wavfile
    intermediate = 40000 + math.sqrt(40000 * hz * (48000 - 40000) / 48000)
    q1, q2 = int(hz / intermediate * 1024), int(intermediate / 48000 * 1024)
    effective_rate = hz * 1024 ** 2 / (q1 * q2)
    rate, audio = wavfile.read(output)
    expected = round(duration * 48000)
    if abs(len(audio) - duration * effective_rate) > 3:
        raise ValueError('Core resampler count does not match the pinned clock calculation')
    # Explicit uniform clock conversion with linear interpolation; envelope
    # evidence uses CPU cycles directly and is unaffected by this interpolation.
    converted = np.interp(np.arange(expected) * effective_rate / 48000, np.arange(len(audio)), audio)
    wavfile.write(output, 48000, converted.astype(np.float32))
    data = {'reference': str(reference), 'reference_sha256': digest(reference),
            'renderer_sha256': digest(renderer), 'timeline_sha256': digest(timeline), 'wav_sha256': digest(output),
            'envelopes_sha256': digest(envelope),
            'target_metadata': str(target) if target else None, 'writes': len(rows),
            'model': ref['profile']['model'], 'clock_hz': hz, 'duration_seconds': duration,
            'raw_core_effective_sample_rate': effective_rate,
            'clock_conversion': 'Fixed rate from pinned two-pass 10-bit cycle/sample ratios; linear interpolation to physical 48-kHz time. No data-fitted time warping.',
            'core': 'Pinned libresidfp 1.3.0 from sibling build/source-lock; public cycle-clock API',
            'processing': '48000 silent warm-up samples, 5-Hz DC blocker, -12-dB gain for both timelines',
            'scope': 'Controlled same-core diagnostic, not a second independent SID emulator. VICE CPU writes remain independent of exporter. Initial chip phases are controlled, not claimed to match real hardware.',
            'limitations': 'Raw core does not apply SIDSynth noise-lock recovery policy; no external input. Actual host recording remains separate.'}
    provenance.write_text(json.dumps(data, indent=2) + '\n')
    return data


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('reference', type=Path); p.add_argument('-o', '--output', type=Path, required=True)
    p.add_argument('--renderer', type=Path, required=True); p.add_argument('--target', type=Path)
    a = p.parse_args(); render(a.reference, a.output, a.renderer, a.target)
