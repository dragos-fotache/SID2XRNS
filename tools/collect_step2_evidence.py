#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Retain step-2 evidence without copying the original Alibi SID or music files."""
import gzip
import hashlib
import json
from pathlib import Path
import platform
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'probe')]
from analyze import verify_register_replay
from sid2xrns import __version__
from sid2xrns.trace import read_trace
from sid2xrns.xrns import verify_assets


def collect():
    work = ROOT / 'work'; output = ROOT / 'evidence/step2'; output.mkdir(exist_ok=True)
    tests = (work / 'step2-tests-final.log').read_text()
    count = re.search(r'Ran (\d+) tests', tests)
    assert count and tests.rstrip().endswith('OK'), 'A passing test run is required'
    summary = {'date': '2026-11-17', 'cli_version': __version__, 'python': platform.python_version(),
               'automated_tests': int(count.group(1)), 'listening': 'not assessed', 'independent_source_audio_comparison': False}
    names = ['cli-synthetic-host-check', 'step2-alibi-window-check', 'step2-alibi-product-check',
             'step2-alibi-recall-check', 'step2-full-container-check', 'step2-full-window-product-check']
    for name in names:
        raw = (work / (name + '.json')).read_bytes()
        (output / (name + '.json')).write_bytes(raw); summary[name] = json.loads(raw)
    meta = json.loads((work / 'cli-synthetic-host.json').read_text())
    trace = Path(meta['trace']).read_bytes(); parsed = json.loads(trace)
    summary['synthetic_register_replay_blocks'] = verify_register_replay(parsed['blocks'], parsed['events'])
    (output / 'synthetic-host.trace.json.gz').write_bytes(gzip.compress(trace, mtime=0))
    (output / 'synthetic-host.metadata.json.gz').write_bytes(gzip.compress(json.dumps(meta).encode(), mtime=0))
    capture = read_trace(ROOT / 'examples/cli-performance.capture.jsonl.gz')
    assert len(capture.calls) == 520
    summary['example_capture_calls'] = len(capture.calls)
    full = json.loads((work / 'alibi-cli-window.report.json').read_text())
    (output / 'alibi-window.report.json').write_text(json.dumps(full, indent=2) + '\n')
    summary['full_window'] = {k: full[k] for k in ['play_calls', 'capture_seconds', 'source_writes', 'patterns',
        'notes_on', 'issues', 'frequency_mapping_max_register_error', 'controls_closer_than_measured_333us']}
    for name in ['step2-alibi-product-check', 'step2-alibi-recall-check', 'step2-full-window-product-check']:
        assert summary[name]['installed_module_sha256'] == 'fbc5cd5947cfa960ae3b95e31c73c11337124448220b597aca5fe597f27e5f72'
    summary['runtime_bindings_verified'] = len(verify_assets())
    summary['source_hashes'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                               for folder in ['sid2xrns', 'tests', 'tools'] for p in sorted((ROOT / folder).rglob('*.py'))}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    files = list(output.iterdir()) + list((ROOT / 'examples').glob('*')) + [ROOT / 'fixtures/cli-performance.sid']
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(files) if p.is_file() and p.name != 'SHA256SUMS.json'}
    (output / 'SHA256SUMS.json').write_text(json.dumps(hashes, indent=2) + '\n')
    print(json.dumps({'evidence_files': len(hashes), 'tests': summary['automated_tests'],
                      'full_window': summary['full_window']}, indent=2))


if __name__ == '__main__': collect()
