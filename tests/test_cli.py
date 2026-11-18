# SPDX-License-Identifier: AGPL-3.0-only
import base64
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile
from sid_fixtures import performance_sid, psid, store
from sid2xrns.capture import capture
from sid2xrns.errors import ConversionError
from sid2xrns.interpret import interpret
from sid2xrns.psid import parse
from sid2xrns.trace import read_trace
from sid2xrns.xrns import write_song, verify_assets

ROOT = Path(__file__).resolve().parents[1]


class CaptureTests(unittest.TestCase):
    def capture(self, data, calls=6, **profile):
        sid = parse(data)
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'capture.jsonl.gz'
        capture(sid, sid.profile(**profile), calls, path)
        return path, read_trace(path)

    def test_subsong_is_one_based_and_reaches_init_accumulator(self):
        _, a = self.capture(performance_sid(), subsong=1)
        _, b = self.capture(performance_sid(), subsong=2)
        self.assertEqual(a.header['initial_registers'][22], 0)
        self.assertEqual(b.header['initial_registers'][22], 1)
        with self.assertRaises(ConversionError): parse(performance_sid()).profile(3)

    def test_embedded_and_header_load_addresses_have_same_execution(self):
        code = store(0xd418, 15) + b'\x60'
        _, a = self.capture(psid(code, embedded_load=True))
        _, b = self.capture(psid(code, embedded_load=False))
        self.assertEqual(a.calls, b.calls)

    def test_ordered_writes_include_same_value_and_same_call_reversals(self):
        code = store(0xd404, 0x21) + store(0xd404, 0x21) + store(0xd404, 0x20) + b'\x60'
        _, trace = self.capture(psid(play=code), calls=1)
        rows = [w for w in trace.writes if w['phase'] == 'play']
        self.assertEqual([w['value'] for w in rows], [0x21, 0x21, 0x20])
        self.assertEqual([w['call_cycle'] for w in rows], [6, 12, 18])
        self.assertEqual(trace.calls[0]['registers'][4], 0x20)
        plan = interpret(trace)
        self.assertIn('sub-quantum-gate-sequence', plan.report['issues'])

    def test_sid_mirror_is_canonicalized_and_ram_under_io_is_not_a_sid_write(self):
        _, trace = self.capture(psid(play=store(0xd424, 0x21) + b'\x60'), calls=1)
        self.assertEqual(trace.writes[-1]['register'], 4)
        code = store(1, 0x34) + store(0xd404, 0x21) + b'\x60'
        _, trace = self.capture(psid(play=code), calls=1)
        self.assertEqual(len(trace.writes), 0)

    def test_write_only_sid_reads_use_shared_bus_latch_and_mirrors(self):
        # Reading volume returns the most recent SID bus byte, which was
        # written to frequency. Reading the mirror shares that same latch.
        code = store(0xd418, 0x0f) + store(0xd400, 0xa5)
        code += b'\xad\x18\xd4\x8d\x01\xd4\xad\x24\xd4\x8d\x02\xd4\x60'
        _, trace = self.capture(psid(play=code), calls=1)
        self.assertEqual(trace.calls[0]['registers'][:3], [0xa5] * 3)
        self.assertEqual(trace.calls[0]['registers'][24], 0x0f)
        self.assertEqual(trace.footer['sid_bus_reads'], {'D418': 1, 'D424': 1})

    def test_sid_bus_decay_includes_idle_time_between_play_calls(self):
        # The gap between VBI calls outlives a 6581 latch but not an 8580.
        init = store(0xd418, 0xa5) + b'\x60'
        play = b'\xad\x18\xd4\x8d\x00\xd4\x60'
        for model, second in [('6581', 0), ('8580', 0xa5)]:
            with self.subTest(model=model):
                _, trace = self.capture(psid(init, play), calls=2, model=model)
                self.assertEqual([c['registers'][0] for c in trace.calls], [0xa5, second])

    def test_banked_out_sid_reads_and_writes_remain_ram(self):
        code = store(0xd400, 0xa5) + store(1, 0x34) + store(0xd418, 0x17)
        code += b'\xad\x18\xd4\x8d\x01\xd4'  # Read/write RAM under I/O.
        code += store(1, 0x35) + b'\xad\x18\xd4\x8d\x02\xd4\x60'
        _, trace = self.capture(psid(play=code), calls=1)
        self.assertEqual(trace.calls[0]['registers'][:3], [0xa5, 0, 0xa5])
        self.assertEqual(trace.footer['sid_bus_reads'], {'D418': 1})

    def test_long_initialization_completes_and_nontermination_remains_bounded(self):
        # 256 * 256 iterations: two NOPs, DEX/BNE, then the outer INY/BNE.
        # More than 250000 instructions are necessary to reach the volume write.
        init = b'\xa0\x00\xa2\x00\xea\xea\xca\xd0\xfb\xc8\xd0\xf6'
        _, trace = self.capture(psid(init + store(0xd418, 15) + b'\x60'), calls=1)
        self.assertGreater(trace.footer['instructions'], 250000)
        self.assertEqual(trace.header['initial_registers'][24], 15)
        with self.assertRaises(ConversionError) as caught:
            self.capture(psid(init=b'\x4c\x00\x10'), calls=1)
        self.assertEqual(caught.exception.code, 'execution-budget-exceeded')
        self.assertEqual(caught.exception.details['phase'], 'init')
        self.assertGreater(caught.exception.details['cycles'], caught.exception.details['cycle_limit'])

    def test_legacy_capture_still_exports_identically(self):
        path, trace = self.capture(performance_sid())
        before = interpret(trace)
        rows = [json.loads(line) for line in gzip.decompress(path.read_bytes()).splitlines()]
        rows[0]['profile']['name'] = 'psid-direct-vbi-v1'
        rows[-1].pop('sid_bus_reads')
        path.write_bytes(gzip.compress(('\n'.join(json.dumps(r) for r in rows) + '\n').encode(), mtime=0))
        after = interpret(read_trace(path))
        a, b = path.parent / 'new.xrns', path.parent / 'legacy.xrns'
        write_song(before, a); write_song(after, b)
        self.assertEqual(a.read_bytes(), b.read_bytes())

    def test_unsupported_files_fail_with_specific_reasons(self):
        cases = [(psid(magic=b'RSID'), 'unsupported-rsid'), (psid(speed=1), 'unsupported-cia-timing'),
                 (psid(second=0x42), 'unsupported-multiple-sids'), (psid(flags=0), 'ambiguous-clock')]
        for data, code in cases:
            with self.subTest(code=code), self.assertRaises(ConversionError) as caught: parse(data).profile()
            self.assertEqual(caught.exception.code, code)
        for data in [b'PSID', performance_sid()[:120], psid()[:123]]:
            with self.assertRaises(ConversionError): parse(data)

    def test_rom_read_sid_read_io_write_and_nontermination_are_rejected(self):
        cases = [(b'\xad\x00\xe0\x60', 'unsupported-rom-read'),
                 (b'\xad\x1b\xd4\x60', 'unsupported-sid-read'),
                 (b'\xad\x19\xd4\x60', 'unsupported-sid-read'),
                 (b'\xad\x1a\xd4\x60', 'unsupported-sid-read'),
                 (b'\xad\x3c\xd4\x60', 'unsupported-sid-read'),
                 (b'\xad\x00\xdc\x60', 'unsupported-io-read'),
                 (store(0xdc04, 1) + b'\x60', 'unsupported-io-write'),
                 (b'\x00', 'unsupported-rom-read'),
                 (b'\x4c\x01\x10', 'execution-budget-exceeded')]
        for code, wanted in cases:
            with self.subTest(wanted=wanted), self.assertRaises(ConversionError) as caught:
                self.capture(psid(play=code), calls=1)
            self.assertEqual(caught.exception.code, wanted)

    def test_truncated_capture_and_tampered_write_are_rejected(self):
        path, trace = self.capture(performance_sid())
        rows = gzip.decompress(path.read_bytes()).splitlines()
        path.write_bytes(gzip.compress(b'\n'.join(rows[:-1]) + b'\n', mtime=0))
        with self.assertRaises(ConversionError): read_trace(path)
        footer = json.loads(rows[-1]); footer['end_cycle'] = float(footer['end_cycle'])
        path.write_bytes(gzip.compress(b'\n'.join(rows[:-1] + [json.dumps(footer).encode()]) + b'\n', mtime=0))
        with self.assertRaises(ConversionError): read_trace(path)
        changed = json.loads(rows[1]); changed['value'] ^= 1; rows[1] = json.dumps(changed).encode()
        path.write_bytes(gzip.compress(b'\n'.join(rows) + b'\n', mtime=0))
        with self.assertRaises(ConversionError): read_trace(path)

    def test_ownership_release_pitch_and_complete_patch_are_musical(self):
        _, trace = self.capture(performance_sid())
        plan = interpret(trace)
        self.assertEqual(len(plan.initial), 67)
        for v in range(1, 4):
            self.assertEqual(plan.initial[f'voice{v}.source'], 0)
            self.assertEqual(plan.initial[f'voice{v}.manualGate'], 0)
            self.assertEqual(plan.initial[f'voice{v}.midiChannel'], v)
        self.assertTrue(any(n['voice'] == 0 and n['note'] is None for n in plan.notes))
        self.assertTrue(any(n['voice'] == 1 and n['note'] is not None for n in plan.notes))
        off = next(n['units'] for n in plan.notes if n['voice'] == 0 and n['note'] is None)
        self.assertTrue(any(u > off and value > 4 for u, value in plan.automation['voice1.tuning'].items()))
        self.assertLessEqual(plan.report['source_time_rounding_max_seconds'], 1 / 25600)
        self.assertNotIn('note-row-collision', plan.report['issues'])

    def test_native_reproducibility_pattern_boundaries_and_carry_points(self):
        path, trace = self.capture(performance_sid(), calls=520)
        plan = interpret(trace)
        self.assertEqual(len(trace.calls), 520)
        self.assertEqual(plan.report['notes_on'], [3, 1, 3])
        a = path.parent / 'a.xrns'; b = path.parent / 'b.xrns'
        write_song(plan, a); write_song(plan, b)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        with zipfile.ZipFile(a) as z: song = E.fromstring(z.read('Song.xml'))
        self.assertGreaterEqual(len(song.findall('./PatternPool/Patterns/Pattern')), 3)
        self.assertEqual([g.findtext('AliasInstrumentIndex') for g in song.findall('./Instruments/Instrument/PluginGenerator')], ['-1', '0', '0'])
        self.assertEqual(len(song.findall('.//PluginGenerator/PluginDevice')), 1)
        for points in song.findall('.//Automations/Envelopes/Envelope/Envelope/Points'):
            self.assertTrue(points.findtext('Point').startswith('0,'))

    def test_xrns_preserves_cutoff_offs_and_reserves_the_longest_release(self):
        init = store(0xd418, 15) + store(0xd406, 0xf0) + store(0xd40d, 0xf9) + b'\x60'
        play = store(0xd401, 0x1d) + store(0xd408, 0x1d)
        play += store(0xd404, 0x21) + store(0xd40b, 0x21) + b'\x60'
        path, trace = self.capture(psid(init, play), calls=255)
        plan = interpret(trace)
        output = path.parent / 'tail.xrns'
        write_song(plan, output)
        with zipfile.ZipFile(output) as archive:
            song = E.fromstring(archive.read('Song.xml'))
        first, tail = song.findall('./PatternPool/Patterns/Pattern')
        offs = [(int(line.get('index')), line.findtext('.//Note'))
                for line in first.findall('./Tracks/PatternTrack/Lines/Line')
                if line.findtext('.//Note') == 'OFF']
        self.assertEqual(offs, [(255, 'OFF'), (255, 'OFF')])
        self.assertFalse(tail.findall('.//NoteColumn'))
        self.assertTrue(all(len(points) == 1 and points.findtext('Point').startswith('0,')
                            for points in tail.findall('.//Points')))
        added_rows = int(tail.findtext('NumberOfLines'))
        self.assertGreater((added_rows + 1) * 0.02, 0.75)
        self.assertLess((added_rows + 1) * 0.02, 1.1)
        self.assertEqual(plan.report['release_tail_rows_added'], added_rows)
        self.assertAlmostEqual(plan.report['song_seconds'], (256 + added_rows) * 0.02)
        self.assertEqual(plan.report['play_calls'], 255)

    def test_release_in_progress_can_extend_song_after_release_rate_change(self):
        init = store(0xd418, 15) + store(0xd406, 0xf5) + store(0xd401, 0x1d) + b'\x60'
        play = b'\xe6\xf0\xa5\xf0\xc9\x01\xd0\x06' + store(0xd404, 0x21) + b'\x60'
        play += b'\xc9\x02\xd0\x06' + store(0xd404, 0x20) + b'\x60'
        slow = play + b'\xc9\x03\xd0\x06' + store(0xd406, 0xf9) + b'\x60\x60'
        _, trace = self.capture(psid(init, play + b'\x60'))
        unchanged = interpret(trace)
        _, trace = self.capture(psid(init, slow))
        changed = interpret(trace)
        self.assertEqual(changed.notes, unchanged.notes)
        self.assertEqual(changed.report['synthetic_boundary_note_offs'], 0)
        self.assertGreater(changed.report['release_tail_rows_added'], 0)
        self.assertGreater(changed.report['song_seconds'] - unchanged.report['song_seconds'], 0.5)

        _, trace = self.capture(psid(init, slow), calls=60)
        expired = interpret(trace)
        self.assertEqual(expired.report['release_tail_rows_added'], 0)
        self.assertEqual(expired.report['song_seconds'], 1.22)

    def test_cli_preserves_input_and_outputs_and_is_cwd_independent(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d); source = directory / 'fixture.sid'; output = directory / 'song.xrns'
            source.write_bytes(performance_sid()); before = source.read_bytes()
            args = [sys.executable, str(ROOT / 'bin/sid2xrns'), 'convert', str(source), '--play-calls', '6', '-o', str(output)]
            result = subprocess.run(args, cwd=d, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            original = output.read_bytes()
            self.assertEqual(source.read_bytes(), before)
            result = subprocess.run(args, cwd=d, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('output-exists', result.stderr)
            self.assertEqual(output.read_bytes(), original)
            # Re-exporting the retained capture produces the same native song.
            again = directory / 'again.xrns'
            result = subprocess.run([sys.executable, str(ROOT / 'bin/sid2xrns'), 'export', str(output.with_suffix('.capture.jsonl.gz')), '-o', str(again)], cwd=d, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(original, again.read_bytes())

    def test_strict_mode_keeps_capture_and_report_without_creating_a_song(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); source = p / 'pulse.sid'; output = p / 'pulse.xrns'
            source.write_bytes(psid(play=store(0xd404, 0x21) + store(0xd404, 0x20) + b'\x60'))
            result = subprocess.run([sys.executable, str(ROOT / 'bin/sid2xrns'), 'convert', str(source),
                '--play-calls', '1', '--strict', '-o', str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stderr)['error']['code'], 'lossy-interpretation')
            self.assertFalse(output.exists())
            self.assertTrue(output.with_suffix('.capture.jsonl.gz').exists())
            report = json.loads(output.with_suffix('.report.json').read_text())
            self.assertFalse(report['exported'])
            self.assertIn('sub-quantum-gate-sequence', report['issues'])

    def test_failed_execution_has_no_partial_output_and_cannot_overwrite_source(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); source = p / 'read.sid'; output = p / 'read.capture.jsonl.gz'
            source.write_bytes(psid(play=b'\xad\x1b\xd4\x60'))
            before = source.read_bytes()
            args = [sys.executable, str(ROOT / 'bin/sid2xrns'), 'capture', str(source), '--play-calls', '1', '-o']
            result = subprocess.run(args + [str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stderr)['error']['code'], 'unsupported-sid-read')
            self.assertFalse(output.exists())
            self.assertEqual(list(p.glob('.*')), [])
            result = subprocess.run(args + [str(source), '--force'], capture_output=True, text=True)
            self.assertEqual(json.loads(result.stderr)['error']['code'], 'output-path-conflict')
            self.assertEqual(source.read_bytes(), before)


if __name__ == '__main__': unittest.main()
