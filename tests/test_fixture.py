# SPDX-License-Identifier: AGPL-3.0-only
import base64
import gzip
import copy
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import xml.etree.ElementTree as E
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fixture', ROOT / 'probe/make_fixture.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
spec = importlib.util.spec_from_file_location('analyze', ROOT / 'probe/analyze.py')
measurement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measurement)


class NativeFixtureTests(unittest.TestCase):
    def test_measurement_detects_a_missing_physical_gate_write(self):
        trace = json.loads(gzip.decompress((ROOT / 'evidence/native-1024.trace.json.gz').read_bytes()))
        measurement.verify_register_replay(trace['blocks'], trace['events'])
        events = copy.deepcopy(trace['events'])
        index = next(i for i, e in enumerate(events) if e[2] == 2 and e[3] == 4 and e[4] & 1)
        del events[index]
        with self.assertRaises(AssertionError): measurement.verify_register_replay(trace['blocks'], events)

    def test_fractional_events_bound_the_source_quantization_error(self):
        for sample in range(48000):
            seconds = sample / 48000
            units, represented = fixture.timing(seconds)
            self.assertLessEqual(abs(seconds - represented), .02 / 512 + 1e-12)
        self.assertNotEqual(fixture.timing(.503)[0] % 256, 0)

    def test_patch_state_roundtrip_and_bad_chunk_rejection(self):
        patch = E.Element('SIDSynthPatch', schemaVersion='3', **{'voice1.source': '0'})
        xml = E.tostring(patch)
        comp = b'VC2!' + struct.pack('<I', len(xml)) + xml + b'\0private'
        header = b'VST3' + struct.pack('<I', 1) + fixture.PROBE_ID.encode()
        preset = header + struct.pack('<Q', 48 + len(comp)) + comp
        preset += b'List' + struct.pack('<I', 1) + struct.pack('<4sQQ', b'Comp', 48, len(comp))
        patch.set('voice2.tuning', '12.34')
        rebuilt = fixture.replace_patch(preset, patch, fixture.PRODUCT_ID)
        _, chunks = fixture.read_preset(rebuilt)
        self.assertIn(b'voice2.tuning="12.34"', chunks[0][1])
        self.assertTrue(chunks[0][1].endswith(b'\0private'))
        self.assertEqual(rebuilt[8:40].decode(), fixture.PRODUCT_ID)
        damaged = bytearray(rebuilt)
        struct.pack_into('<Q', damaged, 40, len(damaged) + 1)
        with self.assertRaises(ValueError): fixture.read_preset(damaged)

    def test_cyclic_alias_and_wrong_channel_are_rejected(self):
        r = E.Element('RenoiseSong'); instruments = E.SubElement(r, 'Instruments')
        for i in range(3):
            g = E.SubElement(E.SubElement(instruments, 'Instrument'), 'PluginGenerator')
            fixture.put(g, 'Channel', i); fixture.put(g, 'AliasInstrumentIndex', -1 if i == 0 else 0)
            if not i:
                fixture.put(E.SubElement(g, 'PluginDevice'), 'PluginIdentifier', fixture.PROBE_ID)
        fixture.validate_song(r)
        root_alias = r.find('./Instruments/Instrument/PluginGenerator/AliasInstrumentIndex')
        root_alias.text = '0'
        with self.assertRaises(ValueError): fixture.validate_song(r)
        root_alias.text = '-1'
        r.find('./Instruments/Instrument/PluginGenerator/Channel').text = '1'
        with self.assertRaises(ValueError): fixture.validate_song(r)

    def test_real_native_fixture_is_reproducible_and_owned_by_notes(self):
        bindings = ROOT / 'fixtures/sidsynth-bindings.json'
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / 'a.xrns', Path(d) / 'b.xrns'
            fixture.make(ROOT / 'fixtures/native-template.xrns', bindings, a)
            fixture.make(ROOT / 'fixtures/native-template.xrns', bindings, b)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            with zipfile.ZipFile(a) as z: root = E.fromstring(z.read('Song.xml'))
            fixture.validate_song(root)
            encoded = root.findtext('.//PluginDevice/ParameterChunk')
            _, chunks = fixture.read_preset(base64.b64decode(encoded))
            comp = next(data for tag, data in chunks if tag == b'Comp')
            patch = E.fromstring(comp[8:8 + struct.unpack_from('<I', comp, 4)[0]])
            for v in range(1, 4):
                self.assertEqual(patch.get(f'voice{v}.source'), '0')
                self.assertEqual(patch.get(f'voice{v}.manualGate'), '0')
            self.assertEqual(len(root.findall('.//PluginGenerator/PluginDevice')), 1)
            for track in root.findall('./Tracks/SequencerTrack'):
                self.assertEqual(track.findtext('DelayColumnIsVisible'), 'true')
            for point in root.findall('.//Automations/Envelopes/Envelope/Envelope/Points'):
                self.assertTrue(point.findtext('Point').startswith('0,'))


if __name__ == '__main__': unittest.main()
