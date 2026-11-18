#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Retain measured summaries and compact raw regression context, without music."""
import bisect
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import numpy as np
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelity.audio import read_audio
from fidelity.target import first_playback

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work'
F = WORK / 'fidelity'


def read(name): return json.loads((F / name).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def collect():
    evidence = ROOT / 'evidence/step3'; evidence.mkdir(parents=True, exist_ok=True)
    sources = {name: read(name + '-source-writes.json') for name in ('synthetic', 'cases', 'alibi', 'turrican')}
    assert all(r['mismatched_calls'] == 0 for r in sources.values())
    repeat = read('reference-repeatability.json'); assert all(repeat.values())
    cross = {}
    for name in ('correct', 'frozen-release', 'missing-arp-step', 'delayed-attacks', 'changed-waveform', 'changed-filter', 'octave-edit'):
        _, a, _ = read_audio(F / 'cases1024' / (name + '.wav'))
        _, b, _ = read_audio(F / 'cases256' / (name + '.wav'))
        cross[name] = bool(np.array_equal(a, b))
    assert all(cross.values())
    _, a, _ = read_audio(F / 'cases1024/correct.wav'); _, b, _ = read_audio(F / 'cases1024-repeat/correct.wav')
    assert np.array_equal(a, b)
    faults = read('actual-fault-summary.json')
    assert all(value['worst_spectral_distance'] > .1 for label in faults.values() for value in label.values())
    # Verify actual note edits affect pitch while preserving other register fields.
    normal = read('cases256/correct.json'); edit = read('cases256/octave-edit.json')
    assert abs(edit['fields']['voice2.frequency']['max_absolute_difference'] - 2228) <= 2
    for field in normal['fields']:
        if field != 'voice2.frequency': assert normal['fields'][field] == edit['fields'][field], field
    product = json.loads((WORK / 'fidelity-alibi-product-check.json').read_text())
    assert product['playback_seconds'] == 241 and product['silent_after_stop'] and product['stereo_equal']
    assert read('alibi-audio/report.json')['coverage']['fraction'] == 1
    listening = read('percussion-listening.json'); assert listening['fidelity_approved'] is False
    closed = read('private-hosts-closed.json')
    assert all(state in ('absent', 'Z') for state in closed.values())
    actual = read('percussion-actual-env256.json')
    first = min(actual['events'], key=lambda r: abs(r['clip_seconds'] - .7))
    assert first['peak_difference_ms'] < -25
    counter = read('percussion-isolation-fields/report.json')
    assert counter['actual_clock_replay_env3_mean_absolute_error'] < 1
    assert counter['actual_clock_replay_env3_fraction_within_3_units'] > .98
    tests = (F / 'tests-final.log').read_text()
    count = int(re.search(r'Ran (\d+) tests', tests)[1]); assert tests.rstrip().endswith('OK')
    before = read('preservation-before.json')
    allowed = {str(Path('/home/dragos/work/SIDSynth') / name) for name in
               ('README.md', 'docs/STATUS.md', 'docs/PLAN.md', 'docs/EXTRACTOR_ROADMAP.md')}
    changes = [p for p, expected in before.items() if not Path(p).is_file() or sha(p) != expected]
    assert set(changes) <= allowed, changes
    preservation = {'checked_files': len(before), 'all_except_authorized_docs_preserved': True,
                    'authorized_document_changes': changes, 'installed_module_sha256': product['installed_module_sha256']}
    (evidence / 'preservation.json').write_text(json.dumps(preservation, indent=2) + '\n')
    summary = {'date': '2026-11-17', 'comparison_tool_version': '0.1.0', 'converter_version': '0.2.1',
               'automated_tests': count, 'source_write_comparisons': {name: {key: value[key] for key in
                 ('calls_compared', 'mismatched_calls', 'exact_ordered_value_matches', 'write_timing_capture_minus_reference_ms')}
                  for name, value in sources.items()},
               'independent_reference_repeatability': repeat,
               'synthetic_repeat_sample_identical': True, 'synthetic_sample_identical_across_buffers': cross,
               'actual_fault_audio': faults, 'octave_edit_changes_voice2_frequency_only': True,
               'actual_installed_product': product,
               'actual_full_window_audio_coverage': read('alibi-audio/report.json')['coverage'],
               'percussion_buffer_check': read('percussion-buffer-check.json'),
               'listening': listening, 'first_reported_percussion_envelope': first,
               'private_hosts_closed': closed,
               'observed_core_cycles_per_audio_second': actual['observed_core_cycles_per_audio_second'],
               'experimental_rate_guard': {'moved_adsr_points': len(json.loads((WORK / 'fidelity-alibi-rate-guard-probe.json').read_text())['edits']),
                   'first_reported_peak_error_ms': min(read('percussion-rate-guard256.json')['events'], key=lambda r: abs(r['clip_seconds'] - .7))['peak_difference_ms'],
                   'remaining_large_deviations': read('percussion-rate-guard256.json')['large_peak_deviations'],
                   'adopted_in_converter_or_synth': False},
               'preservation': preservation,
               'outcome': 'Comparison milestone implemented; full fidelity fails user percussion listening and focused envelope regression. No synth timing correction or installation performed.'}
    (evidence / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    for name in ('alibi-source-writes.json', 'turrican-source-writes.json', 'synthetic-source-writes.json',
                 'cases-source-writes.json', 'percussion-actual-env256.json', 'percussion-buffer-check.json',
                 'percussion-listening.json', 'actual-fault-summary.json'):
        shutil.copy(F / name, evidence / name)
    shutil.copy(F / 'percussion-rate-guard256.json', evidence / 'experimental-rate-guard.json')
    shutil.copy(F / 'private-hosts-closed.json', evidence / 'private-hosts-closed.json')
    source_files = [p for directory in ('fidelity', 'tools', 'probe', 'tests') for p in (ROOT / directory).glob('*.py')]
    source_files += [ROOT / p for p in ('probe/Probe.cpp', 'probe/SelfCheck.cpp', 'probe/CMakeLists.txt',
                     'tools/render_core_timeline.cpp', 'docs/reference-lock.json', 'fixtures/fidelity.sid')]
    (evidence / 'source-hashes.json').write_text(json.dumps({str(p.relative_to(ROOT)): sha(p) for p in sorted(source_files)}, indent=2) + '\n')
    for src, dest in [('alibi-audio/report.json', 'alibi-audio.json'), ('alibi-target-pass1.json', 'alibi-target.json'),
                      ('alibi-target256-pass1.json', 'alibi-target256.json'),
                      ('product-vs-diagnostic/report.json', 'product-vs-diagnostic.json'),
                      ('turrican-audio/report.json', 'turrican-audio.json'),
                      ('percussion-isolation-fields/report.json', 'percussion-isolation.json')]:
        shutil.copy(F / src, evidence / dest)
    shutil.copy(F / 'percussion-actual-env256.png', evidence / 'percussion-envelope.png')
    shutil.copy(F / 'alibi-audio/errors.png', evidence / 'alibi-errors.png')
    shutil.copy(F / 'tests-final.log', evidence / 'unit-tests.log')
    shutil.copy(F / 'probe-env-self-check.log', evidence / 'probe-self-check.log')
    # Compact raw context around the reported six seconds, sufficient to audit
    # control order and ENV readback without bundling an entire source tune.
    meta = json.loads((WORK / 'fidelity-alibi-env256.json').read_text()); trace = json.loads(Path(meta['trace']).read_text())
    first, end = first_playback(trace['blocks']); starts = [b['sample'] for b in trace['blocks']]
    origin = trace['blocks'][first]['sample']; raw = []
    for e in trace['events']:
        sample, offset, kind, a, b, c = e
        index = bisect.bisect_right(starts, sample) - 1
        if kind == 4: seconds = (sample - origin) / 48000
        elif first <= index < end: seconds = trace['blocks'][index]['ppq'] * .48 + offset / 48000
        else: continue
        if 59.75 <= seconds <= 65.75 and kind in (1, 2, 4): raw.append([seconds, kind, a, b, c])
    reference = read('alibi-reference/reference.json')
    compact = {'schema': 1, 'pid': trace['pid'], 'sample_rate': 48000, 'overflow': trace['overflow'],
               'source_sha256': reference['source_sha256'], 'window_source_seconds': [59.75, 65.75],
               'target_events': raw, 'event_kinds': {'1': 'MIDI bytes', '2': 'physical SID register/value',
                   '4': 'ENV3/cumulative actual SID cycles'},
               'independent_writes': [r for r in reference['writes'] if 59.75 <=
                   (r['cycle'] - reference['first_play_cycle']) / reference['profile']['clock_hz'] <= 65.75],
               'reference_first_play_cycle': reference['first_play_cycle'], 'clock_hz': reference['profile']['clock_hz']}
    (evidence / 'percussion-context.json.gz').write_bytes(gzip.compress(json.dumps(compact, separators=(',', ':')).encode(), mtime=0))
    (evidence / 'SHA256SUMS.json').write_text(json.dumps({p.name: sha(p) for p in sorted(evidence.iterdir())
             if p.name != 'SHA256SUMS.json'}, indent=2) + '\n')
    print(json.dumps({'tests': count, 'sources': len(sources), 'evidence': str(evidence),
                      'first_reported_envelope_peak_ms': summary['first_reported_percussion_envelope']['peak_difference_ms']}, indent=2))


if __name__ == '__main__': collect()
