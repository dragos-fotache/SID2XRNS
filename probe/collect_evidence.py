#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Retain compact raw traces, inputs and measured results after a host run."""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
from analyze import analyze
from host import ROOT, WORK


def collect():
    evidence = ROOT / 'evidence'; evidence.mkdir(exist_ok=True)
    runs = [('native-1024', 'measured1024-first', 'native-timing-probe'),
            ('restart-1024', 'measured1024-restart', 'native-timing-probe'),
            ('recall-1024', 'recall1024', 'native-timing-probe'),
            ('native-256', 'measured256', 'native-timing-probe'),
            ('stress-1024', 'subms1024', 'native-timing-subms-probe'),
            ('stress-256', 'subms256', 'native-timing-subms-probe'),
            ('note-edit-256', 'octave256', 'native-timing-octave-probe')]
    summary = {'date': '2026-11-17', 'scope': 'Synthetic native XRNS; actual Renoise 3.5.4 Demo on Linux, 48 kHz',
               'listening': 'Not assessed; recordings retained for user audition', 'runs': {}}
    signatures = {}
    for label, capture, fixture in runs:
        metadata = WORK / (capture + '.json')
        expected = WORK / (fixture + '.expected.json')
        result_file = WORK / (label + '-verified.json')
        result = analyze(metadata, expected, result_file)
        meta = json.loads(metadata.read_text())
        trace = Path(meta['trace']).read_bytes()
        for suffix, data in [('trace.json', trace), ('metadata.json', metadata.read_bytes()),
                             ('expected.json', expected.read_bytes()), ('results.json', result_file.read_bytes())]:
            (evidence / (label + '.' + suffix + '.gz')).write_bytes(gzip.compress(data, mtime=0))
        summary['runs'][label] = {k: result[k] for k in ['rate', 'pid', 'requested_quantum', 'actual_callback_sizes',
            'overflow', 'bindings_verified', 'note_count', 'midi_note_count', 'note_max_abs_error_ms',
            'source_quantization_max_ms', 'automation_groups', 'hardware_checks', 'register_replay_blocks_verified',
            'silent_before_play', 'silent_after_stop', 'audio_peak']}
        summary['runs'][label]['trace_sha256'] = hashlib.sha256(trace).hexdigest()
        signatures[label] = [(round(e['seconds'] * result['rate']), e['kind'], e['address'], e['value'])
                             for e in result['physical_writes'] if .499 <= e['seconds'] <= 3.401]
    summary['physical_write_timeline_equal'] = {
        label: signatures[label] == signatures['native-1024']
        for label in ['native-256', 'restart-1024', 'recall-1024']}
    assert all(summary['physical_write_timeline_equal'].values())
    summary['stress_write_timeline_equal_across_buffers'] = signatures['stress-1024'] == signatures['stress-256']
    assert summary['stress_write_timeline_equal_across_buffers']
    for name in ['note-edit-check', 'installed-product-check', 'installed-product-recall-check']:
        data = json.loads((WORK / (name + '.json')).read_text())
        summary[name] = data
    module = WORK / 'build/SIDXRNSTimingProbe_artefacts/Release/VST3/SID XRNS Timing Probe.vst3/Contents/x86_64-linux/SID XRNS Timing Probe.so'
    summary['probe_module_sha256'] = hashlib.sha256(module.read_bytes()).hexdigest()
    summary['source_lock_sha256'] = hashlib.sha256((ROOT / 'docs/source-lock.json').read_bytes()).hexdigest()
    summary['installed_module_unchanged'] = summary['installed-product-check']['installed_module_sha256'] == summary['installed-product-recall-check']['installed_module_sha256'] == 'fbc5cd5947cfa960ae3b95e31c73c11337124448220b597aca5fe597f27e5f72'
    assert summary['installed_module_unchanged']
    shutil.copy(WORK / 'installed-product.wav', evidence / 'installed-product.wav')
    (evidence / 'timing-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(evidence.iterdir()) if p.name != 'SHA256SUMS.json'}
    (evidence / 'SHA256SUMS.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Retained', len(runs), 'host captures; physical write timelines match across buffers/restart/recall')


if __name__ == '__main__': collect()
