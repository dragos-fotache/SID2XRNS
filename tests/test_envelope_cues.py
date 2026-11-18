# SPDX-License-Identifier: AGPL-3.0-only
import copy
import random
import tempfile
from pathlib import Path
import unittest
import zipfile
import xml.etree.ElementTree as E
from sid2xrns.envelope import Envelope
from sid2xrns.envelope_cues import add_envelope_cues, CUE_FIELDS
from sid2xrns.capture import capture
from sid2xrns.psid import parse
from sid2xrns.trace import read_trace
from sid2xrns.interpret import interpret
from sid2xrns.xrns import write_song, verify_assets
from sid_fixtures import performance_sid


class EnvelopeTests(unittest.TestCase):
    def test_overlapping_pipelines_do_not_suppress_reset_or_exponential_clock(self):
        env=Envelope();env.env_pipe=2;env.exp_pipe=1;env.counter=10
        env.step()
        self.assertEqual((env.env_pipe,env.exp_pipe,env.exp),(1,0,0))
        env=Envelope();env.env_pipe=2;env.exp_pipe=0
        env.step()
        self.assertFalse(env.reset)
        self.assertEqual(env.exp_pipe,1)

    def test_fast_clock_preserves_pipeline_history(self):
        rng = random.Random(4591)
        slow = Envelope(); fast = Envelope()
        for _ in range(350):
            reg = rng.choice((4, 5, 6)); value = rng.randrange(256)
            slow.write(reg, value); fast.write(reg, value)
            cycles = rng.randrange(5000)
            for _ in range(cycles): slow.step()
            fast.clock(cycles)
            self.assertEqual(vars(slow), vars(fast))

    def test_source_cues_preserve_editable_notes_and_original_controls(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); sid=parse(performance_sid()); trace=p/'source.gz'
            capture(sid,sid.profile(),520,trace); trace=read_trace(trace)
            legacy=interpret(trace); source=add_envelope_cues(copy.deepcopy(legacy),trace)
            self.assertEqual(source.notes,legacy.notes)
            for key,points in legacy.automation.items(): self.assertEqual(source.automation[key],points)
            self.assertEqual(len(source.initial),80)
            self.assertEqual(source.initial['envelope.cueMode'],1)
            self.assertFalse(source.report['envelope_cues']['skipped'])
            for v in range(1,4):
                for field in CUE_FIELDS:
                    self.assertTrue(all(isinstance(value,int) and 0 <= value < 2**20
                                        for value in source.automation[f'voice{v}.{field}'].values()))
            a=p/'a.xrns'; b=p/'b.xrns'; write_song(source,a); write_song(source,b)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            song=E.fromstring(zipfile.ZipFile(a).read('Song.xml'))
            self.assertEqual(len(song.findall('.//PluginGenerator/PluginDevice')),1)
            self.assertEqual(len(song.find('.//PluginDevice/Parameters')),80)
            bindings=verify_assets(4)
            self.assertEqual(bindings[:67],verify_assets())
            self.assertTrue(any('envelopeState' in bindings[int(m.text)]['id']
                                for m in song.findall('.//InstrumentAutomationDevice/ParameterNumber13') if int(m.text)>=0))
