# SPDX-License-Identifier: AGPL-3.0-only
import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from fidelity.audio import compare_arrays
from fidelity.reference import parse_dump, monitor_rows
from fidelity.target import states_at, fields, first_playback
from fidelity.writes import compare_capture


class FidelityTests(unittest.TestCase):
    def audio(self):
        rate = 12000; t = np.arange(rate * 5) / rate
        frequency = np.select([t < 1, t < 2, t < 3, t < 4], [220, 330, 440, 550], 660)
        envelope = np.minimum((t % .5) * 30, 1) * np.exp(-(t % .5) * 2)
        phase = np.cumsum(frequency) * 2 * np.pi / rate
        return rate, envelope * np.sin(phase)

    def test_constant_recording_latency_and_gain_are_reported(self):
        rate, x = self.audio(); delay = round(.123 * rate)
        report, _, _ = compare_arrays(x, np.r_[np.zeros(delay), x * .25], rate)
        self.assertLessEqual(abs(report['alignment']['result_offset_samples'] - delay), rate / 1000)
        self.assertAlmostEqual(report['levels']['result_minus_reference_db'], -12.0412, places=3)
        self.assertLess(report['level_matched_nrmse'], 1e-9)
        self.assertEqual(report['coverage']['fraction'], 1)

    def test_checker_detects_missing_step_frozen_release_delay_waveform_filter(self):
        rate, x = self.audio(); t = np.arange(len(x)) / rate
        from scipy.signal import butter, sosfilt
        missing = x.copy(); missing[rate:2 * rate] = x[:rate]
        frozen = x.copy(); frozen[rate:3 * rate] = np.tile(x[:rate], 2)
        delayed = x.copy(); start = 3 * rate; offset = round(.02 * rate)
        delayed[start:start + offset] = 0; delayed[start + offset:4 * rate] = x[start:4 * rate - offset]
        waveform = np.sign(x) * np.abs(x).max() * .7
        filtered = sosfilt(butter(4, 300, fs=rate, output='sos'), x)
        for name, y in [('missing', missing), ('frozen', frozen), ('delayed', delayed), ('waveform', waveform), ('filter', filtered)]:
            with self.subTest(name=name):
                report, _, _ = compare_arrays(x, y, rate, maximum=.05)
                self.assertGreater(max(r['spectral_distance'] for r in report['windows']), .08)
        report, _, _ = compare_arrays(x, delayed, rate, maximum=.05)
        self.assertLessEqual(abs(report['alignment']['result_offset_seconds']), .001)
        self.assertGreater(report['worst_windows'][0]['seconds'], 2.5)

    def test_short_result_reports_missing_coverage_without_hiding_it(self):
        rate, x = self.audio()
        report, _, _ = compare_arrays(x, x[:3 * rate], rate, maximum=.05)
        self.assertAlmostEqual(report['coverage']['fraction'], .6)

    def test_silence_nonfinite_and_excess_alignment_are_rejected(self):
        rate, x = self.audio()
        for y, bound in [(x * 0, 1), (x * float('nan'), 1), (x, 20)]:
            with self.assertRaises(ValueError): compare_arrays(x, y, rate, bound)

    def test_dump_clock_and_physical_order_are_checked(self):
        stores = [{'cycle': 70, 'address': 0xd400}, {'cycle': 76, 'address': 0xd401}]
        rows, offset = parse_dump('6 0 52\n6 1 18\n', stores)
        self.assertEqual(offset, 64); self.assertEqual(rows[-1]['value'], 18)
        for text in ('6 0 52\n7 1 18\n', '6 0 52\n6 2 18\n', '6 0 52\n'):
            with self.assertRaises(ValueError): parse_dump(text, stores)

    def test_register_state_grid_preserves_reset_and_sid_bit_widths(self):
        r = states_at([(0, 2, 52), (0, 3, 250), (.1, 21, 255), (.1, 22, 1), (.2, None, 0)], [0, .1, .2])
        mapped = fields(r)
        self.assertEqual(list(mapped['voice1.pulseWidth']), [0xa34, 0xa34, 0])
        self.assertEqual(list(mapped['filter.cutoff']), [0, 15, 0])

    def test_host_wraparound_is_split_before_reference_comparison(self):
        blocks = [{'playing': False, 'ppq': 0}, {'playing': True, 'ppq': 0},
                  {'playing': True, 'ppq': 1}, {'playing': True, 'ppq': 0},
                  {'playing': True, 'ppq': .1}]
        self.assertEqual(first_playback(blocks), (1, 3))
        with self.assertRaises(ValueError):
            states_at([(0, 0, 1), (1, 0, 2), (0, 0, 3)], [.5])

    def test_independent_write_comparison_detects_known_changed_value(self):
        from sid2xrns.trace import read_trace
        root = Path(__file__).resolve().parents[1]
        trace = read_trace(root / 'examples/cli-performance.capture.jsonl.gz')
        ref = {'source_sha256': trace.header['source']['sha256'], 'profile': trace.header['profile'],
               'play_calls': len(trace.calls), 'play_entries': [r['start_cycle'] for r in trace.calls] + [trace.footer['end_cycle']],
               'writes': [r for r in trace.writes if r['phase'] == 'play'], 'reference': {'independence': 'synthetic oracle'}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'reference.json'; output = Path(directory) / 'out.json'
            path.write_text(json.dumps(ref))
            self.assertEqual(compare_capture(path, root / 'examples/cli-performance.capture.jsonl.gz', output)['mismatched_calls'], 0)
            ref['writes'] = copy.deepcopy(ref['writes']); ref['writes'][0]['value'] ^= 1
            path.write_text(json.dumps(ref))
            self.assertEqual(compare_capture(path, root / 'examples/cli-performance.capture.jsonl.gz', Path(directory) / 'fault.json')['mismatched_calls'], 1)
            with self.assertRaises(ValueError):
                compare_capture(path, root / 'examples/cli-performance.capture.jsonl.gz', output)

    def test_phase_difference_is_visible_without_claiming_a_musical_fault(self):
        rate = 12000; t = np.arange(rate * 2) / rate
        env = np.minimum(t * 10, 1) * np.exp(-t)
        x = env * np.sin(2 * np.pi * 440 * t)
        y = env * np.cos(2 * np.pi * 440 * t)
        report, _, _ = compare_arrays(x, y, rate, maximum=0)
        self.assertGreater(report['level_matched_nrmse'], 1)
        self.assertLess(max(r['spectral_distance'] for r in report['windows']), .02)

    def test_drift_is_reported_without_locally_realigning_the_output(self):
        rate, x = self.audio(); t = np.arange(len(x))
        y = np.interp(t / 1.01, t, x)
        report, _, _ = compare_arrays(x, y, rate, maximum=.1)
        offsets = [r['residual_lag_ms'] for r in report['alignment']['local_offsets_diagnostic_only']
                   if r['residual_lag_ms'] is not None]
        self.assertGreater(max(offsets) - min(offsets), 10)


if __name__ == '__main__': unittest.main()
