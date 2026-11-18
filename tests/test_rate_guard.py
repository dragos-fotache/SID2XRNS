# SPDX-License-Identifier: AGPL-3.0-only
import copy
from pathlib import Path
import tempfile
import unittest
from fidelity.rate_guard import guard
from sid2xrns.psid import parse
from sid2xrns.capture import capture
from sid2xrns.trace import read_trace
from sid2xrns.interpret import interpret
from tests.sid_fixtures import psid, store


class NativeEnvelopeOrderingTests(unittest.TestCase):
    def performance(self, directory):
        init = store(0xf0, 0) + store(0xd414, 0xe0) + store(0xd40e, 0x45) + store(0xd40f, 0x1d) + b'\x60'
        # Second VBI only: SR change followed 13 CPU cycles later by TEST/gate.
        actions = store(0xd414, 0xe7) + b'\x24\x00\xea\xea' + store(0xd412, 9)
        play = b'\xee\xf0\x00\xad\xf0\x00\xc9\x02\xd0' + bytes([len(actions)]) + actions + b'\x60'
        sid = parse(psid(init, play)); path = Path(directory) / 'trace.jsonl.gz'
        capture(sid, sid.profile(), 3, path); trace = read_trace(path)
        return trace, interpret(trace)

    def test_only_collapsed_rate_change_moves_before_the_same_owned_note(self):
        with tempfile.TemporaryDirectory() as directory:
            trace, performance = self.performance(directory)
            original_notes = copy.deepcopy(performance.notes)
            report = guard(performance, trace)
            self.assertEqual(len(report['edits']), 1)
            edit = report['edits'][0]
            self.assertEqual(edit['id'], 'voice3.release')
            self.assertEqual(edit['source_lead_cycles'], 13)
            self.assertEqual(performance.notes, original_notes)
            self.assertNotIn(edit['from_units'], performance.automation['voice3.release'])
            self.assertEqual(performance.automation['voice3.release'][edit['to_units']], 7)

    def test_existing_point_and_absent_note_ownership_prevent_unsafe_retiming(self):
        with tempfile.TemporaryDirectory() as directory:
            trace, performance = self.performance(directory)
            unit = next(n['units'] for n in performance.notes if n['note'] is not None)
            performance.automation['voice3.release'][unit - 1] = 3
            report = guard(performance, trace)
            self.assertFalse(report['edits']); self.assertEqual(len(report['skipped']), 1)
            self.assertEqual(performance.automation['voice3.release'][unit - 1], 3)
        with tempfile.TemporaryDirectory() as directory:
            trace, performance = self.performance(directory); performance.notes = []
            self.assertFalse(guard(performance, trace)['edits'])
