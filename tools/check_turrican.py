#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Offline regression against a user-supplied Turrican 3 SID; no music bundled."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as E
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sid2xrns import __version__
from sid2xrns.capture import capture
from sid2xrns.interpret import interpret
from sid2xrns.psid import read
from sid2xrns.trace import read_trace
from sid2xrns.xrns import write_song

SOURCE_SHA256 = 'ca3f477225859e79de059b41f3ba9fdb5389f791daa6a78176eb6f487522ca4d'


def check(source, directory, calls):
    sid = read(source)
    if sid.sha256 != SOURCE_SHA256:
        raise ValueError('This regression requires the documented Turrican 3 source hash')
    directory.mkdir()  # Refuse to replace any previous evidence.
    results = []
    for song in range(1, sid.songs + 1):
        previous = None
        for model in ('6581', '8580'):
            stem = directory / f'subsong-{song:02d}-{model}'
            capture_file, song_file = stem.with_suffix('.capture.jsonl.gz'), stem.with_suffix('.xrns')
            capture(sid, sid.profile(subsong=song, model=model), calls, capture_file)
            trace = read_trace(capture_file)
            plan = interpret(trace)
            exported = write_song(plan, song_file)
            with zipfile.ZipFile(song_file) as archive:
                root = E.fromstring(archive.read('Song.xml'))
            assert len(root.findall('.//PluginGenerator/PluginDevice')) == 1
            assert [g.findtext('AliasInstrumentIndex') for g in root.findall('./Instruments/Instrument/PluginGenerator')] == ['-1', '0', '0']
            assert [g.findtext('Channel') for g in root.findall('./Instruments/Instrument/PluginGenerator')] == ['0', '1', '2']
            assert len(plan.initial) == exported['parameter_bindings'] == 67
            assert len(trace.calls) == calls and sum(plan.report['notes_on']) > 0
            # Both chip models return zero at the observed post-unpack read.
            # Their capture writes should therefore agree for this source.
            signature = (trace.header['init_cycles'], trace.footer['write_sha256'])
            if previous is not None:
                assert signature == previous, (song, signature, previous)
            previous = signature
            result = {'subsong': song, 'model': model, 'init_cycles': trace.header['init_cycles'],
                      'instructions': trace.footer['instructions'], 'sid_bus_reads': trace.footer['sid_bus_reads'],
                      'writes': len(trace.writes), 'write_sha256': trace.footer['write_sha256'],
                      'longest_play_call_cycles': trace.footer['longest_play_call_cycles'],
                      'notes_on': plan.report['notes_on'], 'issues': plan.report['issues'],
                      'controls_closer_than_measured_333us': plan.report['controls_closer_than_measured_333us'],
                      'patterns': exported['patterns'], 'xrns_sha256': hashlib.sha256(song_file.read_bytes()).hexdigest()}
            results.append(result)
            print(json.dumps(result), flush=True)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == SOURCE_SHA256
    summary = {'tool_version': __version__, 'source_sha256': SOURCE_SHA256, 'play_calls_per_case': calls,
               'cases': len(results), 'passed': True, 'checks': results,
               'evidence_kind': 'automated offline capture, checked write replay and native export',
               'independent_audio_fidelity': False, 'listening': 'not assessed'}
    (directory / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sid', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='A fresh directory inside an existing parent')
    parser.add_argument('--play-calls', type=int, default=1200)
    args = parser.parse_args()
    check(args.sid, args.output, args.play_calls)
