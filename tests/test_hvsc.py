# SPDX-License-Identifier: AGPL-3.0-only
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from sid_fixtures import performance_sid
from sid2xrns.errors import ConversionError
from sid2xrns.trace import read_trace

CLI = Path(__file__).resolve().parents[1] / 'bin/sid2xrns'


class HVSCLookupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / 'Renamed.sid'
        data = performance_sid()
        self.source.write_bytes(data)
        self.sid_md5 = hashlib.md5(data).hexdigest()
        self.database = self.root / 'Songlengths.md5'

    def run_cli(self, *args):
        return subprocess.run([CLI, *args], cwd=self.root, capture_output=True, text=True)

    def write_entry(self, durations):
        # HVSC comments can name a different path. Matching is by full SID bytes.
        self.database.write_bytes(
            f'\ufeff[Database]\r\n; /DEMOS/Original.sid\r\n{self.sid_md5.upper()}={durations}\r\n'.encode()
        )

    def test_inspect_lists_lengths_in_subsong_order(self):
        self.write_entry('1:02.5 0:00.093')
        result = self.run_cli('inspect', self.source, '--hvsc-db')
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = {'sid_md5': self.sid_md5, 'song_lengths_ms': [62500, 93]}
        self.assertEqual(json.loads(result.stdout)['hvsc'], expected)

        alternate = self.database.rename(self.root / 'Alternate.md5')
        result = self.run_cli('inspect', self.source, '--hvsc-db', alternate)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['hvsc'], expected)

        result = self.run_cli('inspect', self.source, '--hvsc-db')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('Songlengths.md5', json.loads(result.stderr)['error']['message'])

    def test_capture_uses_selected_subsong_and_execution_clock(self):
        self.write_entry('0:01 0:00.099')
        for clock, calls in [('pal', 5), ('ntsc', 6)]:
            with self.subTest(clock=clock):
                trace_path = self.root / f'{clock}.jsonl'
                result = self.run_cli('capture', self.source, '--subsong', '2', '--clock', clock,
                                      '--hvsc-db', '-o', trace_path)
                self.assertEqual(result.returncode, 0, result.stderr)
                trace = read_trace(trace_path)
                self.assertEqual(trace.header['profile']['subsong'], 2)
                self.assertEqual(trace.header['init_cycles'] + calls * trace.header['profile']['cycles_per_call'],
                                 trace.footer['end_cycle'])
                self.assertEqual(len(trace.calls), calls)
                self.assertEqual(trace.header['hvsc'], {'sid_md5': self.sid_md5, 'duration_ms': 99})

        trace_path = self.root / 'ntsc.jsonl'
        rows = trace_path.read_text().splitlines()
        header = json.loads(rows[0])
        header['hvsc']['duration_ms'] = 1000
        trace_path.write_text('\n'.join([json.dumps(header), *rows[1:]]) + '\n')
        with self.assertRaisesRegex(ConversionError, 'HVSC duration does not match capture budget'):
            read_trace(trace_path)

    def test_convert_and_repeat_export_without_database(self):
        self.write_entry('0:00.1 0:04')
        song = self.root / 'converted.xrns'
        trace = song.with_suffix('.capture.jsonl.gz')
        report = song.with_suffix('.report.json')
        result = self.run_cli('convert', self.source, '--hvsc-db', '-o', song,
                              '--trace', trace, '--report', report)
        self.assertEqual(result.returncode, 0, result.stderr)
        first = json.loads(report.read_text())
        self.assertEqual(first['hvsc'], {'sid_md5': self.sid_md5, 'duration_ms': 100})
        self.assertEqual(first['profile']['subsong'], 1)
        self.assertEqual(first['play_calls'], 6)
        self.assertGreaterEqual(first['capture_seconds'], .1)
        self.assertLess(first['capture_seconds'], .12)

        self.database.unlink()
        again = self.root / 'again.xrns'
        result = self.run_cli('export', trace, '-o', again)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(song.read_bytes(), again.read_bytes())
        self.assertEqual(json.loads(again.with_suffix('.report.json').read_text())['hvsc'], first['hvsc'])

    def test_convert_uses_local_hvsc_and_saves_only_requested_outputs(self):
        self.write_entry('0:00.1 0:04')
        result = self.run_cli('convert', self.source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({path.name for path in self.root.iterdir()},
                         {'Renamed.sid', 'Songlengths.md5', 'Renamed.xrns'})

        report = self.root / 'details.json'
        duplicate = self.root / 'duplicate.xrns'
        result = self.run_cli('convert', self.source, '-o', duplicate, '--report', report)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({path.name for path in self.root.iterdir()},
                         {'Renamed.sid', 'Songlengths.md5', 'Renamed.xrns', 'duplicate.xrns', 'details.json'})
        details = json.loads(report.read_text())
        self.assertIsNone(details['trace'])
        self.assertEqual(details['play_calls'], 6)
        self.assertEqual(details['hvsc']['duration_ms'], 100)
        self.assertEqual(duplicate.read_bytes(), self.source.with_suffix('.xrns').read_bytes())

    def test_failed_lookup_never_publishes_outputs(self):
        song = self.root / 'converted.xrns'
        result = self.run_cli('convert', self.source, '-o', song)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stderr)['error']['code'], 'hvsc-database-not-found')
        self.assertFalse(song.exists())
        cases = [
            (f'[Database]\n{"a" * 32}=0:01\n', 'hvsc-tune-not-found'),
            (f'[Database]\n{self.sid_md5}=0:01\n', 'hvsc-duration-not-found'),
            (f'[Database]\n{self.sid_md5}=0:01 0:60\n', 'invalid-hvsc-database'),
            (f'[Database]\n{self.sid_md5}=0:01 120:00\n', 'invalid-play-call-budget'),
        ]
        for contents, code in cases:
            with self.subTest(code=code):
                self.database.write_text(contents)
                result = self.run_cli('convert', self.source, '--subsong', '2', '--hvsc-db', self.database, '-o', song)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(json.loads(result.stderr)['error']['code'], code)
                self.assertFalse(song.exists())
                self.assertFalse(song.with_suffix('.capture.jsonl.gz').exists())
                self.assertFalse(song.with_suffix('.report.json').exists())

    def test_force_does_not_overwrite_the_database(self):
        self.write_entry('0:01 0:04')
        original = self.database.read_bytes()
        result = self.run_cli('capture', self.source, '--hvsc-db',
                              '--force', '-o', self.database)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stderr)['error']['code'], 'output-path-conflict')
        self.assertEqual(self.database.read_bytes(), original)
