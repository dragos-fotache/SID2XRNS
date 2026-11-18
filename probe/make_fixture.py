#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Generate a synthetic native timing song; this does not read SID music."""
import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as E
import zipfile

ROW_SECONDS = .02  # 125 BPM, 24 LPB. 256 delay/automation units per row.
LINES = 512
PRODUCT_ID = 'ABCDEF019182FAEB5369647353796469'
PROBE_ID = 'ABCDEF019182FAEB5369647353787470'


def put(parent, tag, value):
    e = parent.find(tag)
    if e is None:
        e = E.SubElement(parent, tag)
    e.text = str(value)
    return e


def timing(seconds):
    units = round(seconds / ROW_SECONDS * 256)
    return units, units * ROW_SECONDS / 256


def read_preset(data):
    if len(data) < 48 or data[:4] != b'VST3' or struct.unpack_from('<I', data, 4)[0] != 1:
        raise ValueError('Expected a VST3 version-1 preset container')
    offset = struct.unpack_from('<Q', data, 40)[0]
    if offset + 8 > len(data) or data[offset:offset + 4] != b'List':
        raise ValueError('Invalid VST3 chunk table')
    count = struct.unpack_from('<I', data, offset + 4)[0]
    if offset + 8 + count * 20 != len(data):
        raise ValueError('Unexpected VST3 chunk table size')
    chunks = []
    for i in range(count):
        tag, start, size = struct.unpack_from('<4sQQ', data, offset + 8 + i * 20)
        if start < 48 or start + size > offset:
            raise ValueError('VST3 chunk is outside the payload')
        chunks.append((tag, data[start:start + size]))
    if sum(tag == b'Comp' for tag, _ in chunks) != 1:
        raise ValueError('Expected one component chunk')
    return data[:40], chunks


def replace_patch(data, patch, identifier):
    header, chunks = read_preset(data)
    result = bytearray(header[:8] + identifier.encode('ascii') + bytes(8))
    entries = []
    for tag, chunk in chunks:
        if tag == b'Comp':
            if chunk[:4] != b'VC2!' or len(chunk) < 8:
                raise ValueError('Expected JUCE binary XML')
            size = struct.unpack_from('<I', chunk, 4)[0]
            old = E.fromstring(chunk[8:8 + size])
            if old.tag != 'SIDSynthPatch' or old.get('schemaVersion') != '3':
                raise ValueError('Expected SIDSynth schema 3')
            xml = E.tostring(patch, encoding='utf-8')
            chunk = b'VC2!' + struct.pack('<I', len(xml)) + xml + chunk[8 + size:]
        entries.append((tag, len(result), len(chunk)))
        result.extend(chunk)
    struct.pack_into('<Q', result, 40, len(result))
    result.extend(b'List' + struct.pack('<I', len(entries)))
    for entry in entries:
        result.extend(struct.pack('<4sQQ', *entry))
    read_preset(result)
    return bytes(result)


def validate_song(root):
    instruments = root.findall('./Instruments/Instrument')
    generators = [i.find('PluginGenerator') for i in instruments]
    if len(generators) != 3 or sum(g.find('PluginDevice') is not None for g in generators) != 1:
        raise ValueError('Expected exactly one plugin and two aliases')
    if [int(g.findtext('Channel')) for g in generators] != [0, 1, 2]:
        raise ValueError('Expected saved channels 0/1/2 (host channels 1/2/3)')
    if [int(g.findtext('AliasInstrumentIndex')) for g in generators] != [-1, 0, 0]:
        raise ValueError('Expected one root and two direct aliases; refusing cyclic links')
    if generators[0].findtext('./PluginDevice/PluginIdentifier') not in (PRODUCT_ID, PROBE_ID):
        raise ValueError('Unexpected plugin identity')


def make(template, bindings_file, output, product=False, submillisecond=False, octave_edit=False):
    bindings = json.loads(bindings_file.read_text())
    if len(bindings) != 67 or len({s['id'] for s in bindings}) != 67:
        raise ValueError('Expected all 67 unique parameter IDs')
    index = {s['id']: i for i, s in enumerate(bindings)}
    specs = {s['id']: s for s in bindings}
    initial = {s['id']: s['initial'] for s in bindings}
    initial.update({'output.gainDb': -18, 'midi.mode': 0, 'chip.model': 1, 'chip.clock': 0})
    for v in range(1, 4):
        initial.update({f'voice{v}.source': 0, f'voice{v}.manualGate': 0, f'voice{v}.tuning': 0,
                        f'voice{v}.midiChannel': v, f'voice{v}.attack': 0, f'voice{v}.decay': 0,
                        f'voice{v}.sustain': 12, f'voice{v}.release': 15})
    with zipfile.ZipFile(template) as z:
        root = E.fromstring(z.read('Song.xml'))
        members = {n: z.read(n) for n in z.namelist() if n != 'Song.xml'}
    instrument_list = root.find('Instruments')
    assert len(instrument_list) == 3
    plugin = instrument_list[0].find('./PluginGenerator/PluginDevice')
    assert plugin.findtext('PluginIdentifier') == PROBE_ID
    assert len(plugin.findall('./Parameters/Parameter')) == 68
    identifier = PRODUCT_ID if product else PROBE_ID
    patch = E.Element('SIDSynthPatch', schemaVersion='3', **{k: str(v) for k, v in initial.items()})
    put(plugin, 'ParameterChunk', base64.b64encode(replace_patch(
        base64.b64decode(plugin.findtext('ParameterChunk')), patch, identifier)).decode())
    put(plugin, 'PluginIdentifier', identifier)
    put(plugin, 'PluginDisplayName', 'VST3: SIDSynth: ' + ('SIDSynth' if product else 'SID XRNS Timing Probe'))
    put(plugin, 'PluginShortDisplayName', 'SIDSynth' if product else 'SID XRNS Timing Probe')
    params = plugin.find('Parameters')
    for i, s in enumerate(bindings):
        value = (initial[s['id']] - s['minimum']) / (s['maximum'] - s['minimum'])
        put(params[i], 'Value', f'{value:.12g}')
    if product: params.remove(params[-1])
    else: put(params[-1], 'Value', .5)
    for i, instrument in enumerate(instrument_list):
        put(instrument, 'Name', f'SID part {i + 1}')
        generator = instrument.find('PluginGenerator')
        put(generator, 'Channel', i)
        put(generator, 'AutoSuspend', 'false')
        if i:
            for d in list(generator):
                if d.tag == 'PluginDevice': generator.remove(d)
            put(generator, 'AliasInstrumentIndex', 0)
        else: put(generator, 'AliasInstrumentIndex', -1)
    global_data = root.find('GlobalSongData')
    for k, v in {'SongName': 'SID2XRNS native timing fixture', 'Artist': 'SIDSynth diagnostics',
                 'BeatsPerMin': 125, 'LinesPerBeat': 24, 'TicksPerLine': 16}.items():
        put(global_data, k, v)
    patterns = root.find('./PatternPool/Patterns')
    pattern = copy.deepcopy(patterns[0]); patterns.clear(); patterns.append(pattern)
    put(pattern, 'NumberOfLines', LINES)
    pattern_tracks = pattern.find('Tracks')
    for t in pattern_tracks:
        for k in ['Lines', 'Automations']:
            e = t.find(k)
            if e is not None: t.remove(e)
    sequence = root.find('./PatternSequence/SequenceEntries'); sequence.clear()
    put(E.SubElement(sequence, 'SequenceEntry'), 'Pattern', 0)
    control_template = root.find('.//InstrumentAutomationDevice')
    assert control_template is not None
    controls = []
    for i, track in enumerate(list(root.find('Tracks'))[:3]):
        put(track, 'Name', f'SID part {i + 1}')
        put(track, 'NumberOfVisibleNoteColumns', 1)
        put(track, 'NumberOfVisibleEffectColumns', 1)
        put(track, 'DelayColumnIsVisible', 'true')
        ids = [s['id'] for s in bindings if s['id'].startswith(f'voice{i + 1}.') and
               s['id'].split('.')[1] not in ('midiChannel', 'source', 'frequency', 'manualGate')]
        if i == 0:
            ids += [s['id'] for s in bindings if s['id'].startswith('filter.') or s['id'] in ('chip.volume', 'chip.voice3Direct')]
        assert len(ids) <= 35
        devices = track.find('./FilterDevices/Devices')
        for d in list(devices)[1:]: devices.remove(d)
        control = copy.deepcopy(control_template)
        put(control, 'LinkedInstrument', 0)
        put(control, 'VisiblePages', 7)
        for slot in range(35):
            key = ids[slot] if slot < len(ids) else None
            put(control, f'ParameterNumber{slot}', index[key] if key else -1)
            s = specs[key] if key else None
            value = (initial[key] - s['minimum']) / (s['maximum'] - s['minimum']) if s else 0
            put(control, f'ParameterValue{slot}/Value', value)
        devices.append(control)
        controls.append(ids)

    expected = {'row_seconds': ROW_SECONDS, 'lines': LINES, 'schema': 3,
                'template_sha256': hashlib.sha256(template.read_bytes()).hexdigest(),
                'bindings_sha256': hashlib.sha256(bindings_file.read_bytes()).hexdigest(),
                'initial': initial, 'notes': [], 'automation': [], 'bindings': bindings}
    notes = [(.5, 0, 69), (.503, 1, 60), (.507, 2, 64), (.8, 2, None), (.9, 1, None),
             (1.3, 0, None), (2.5, 2, 40), (2.52, 2, None), (2.541, 2, 42),
             (2.56, 2, None), (3.0, 0, 69), (3.2, 0, 72), (3.4, 0, None)]
    if octave_edit:
        notes[0] = (.5, 0, 81)
    track_lines = [E.SubElement(pattern_tracks[i], 'Lines') for i in range(3)]
    for seconds, voice, note in notes:
        units, represented = timing(seconds); row, delay = divmod(units, 256)
        line = E.SubElement(track_lines[voice], 'Line', index=str(row))
        col = E.SubElement(E.SubElement(line, 'NoteColumns'), 'NoteColumn')
        name = 'OFF' if note is None else ['C-', 'C#', 'D-', 'D#', 'E-', 'F-', 'F#', 'G-', 'G#', 'A-', 'A#', 'B-'][note % 12] + str(note // 12)
        put(col, 'Note', name); put(col, 'Instrument', f'{voice:02X}')
        if delay: put(col, 'Delay', f'{delay:02X}')
        expected['notes'].append({'seconds': seconds, 'represented': represented, 'voice': voice,
                                  'note': note, 'units': units})
    changes = {key: {0: value} for key, value in initial.items() if any(key in c for c in controls)}

    def change(group, seconds, key, value):
        units, represented = timing(seconds)
        changes[key][units] = value
        expected['automation'].append({'group': group, 'seconds': seconds, 'represented': represented,
                                       'id': key, 'value': value, 'units': units})

    for i in range(20):
        t = .6 + i * .02
        change('20ms', t, 'voice1.tuning', [-7, 0, 5, 12][i % 4])
        change('20ms', t, 'voice1.pulseWidth', 200 + i * 170)
        change('20ms', t, 'filter.cutoff', 100 + i * 90)
    for i, tune in enumerate([5, 9, 0, -5]):
        change('release', 1.1 + i * .02, 'voice2.tuning', tune)
    for i in range(6):
        t = 1.5 + .002 * i
        change('2ms', t, 'voice1.pulseWidth', 111 + i * 500)
        change('2ms', t, 'filter.cutoff', 123 + i * 300)
        change('2ms', t, 'voice1.saw', i % 2)
        change('2ms', t, 'voice1.pulse', 1 - i % 2)
    if submillisecond:
        for i in range(8):
            change('250us', 1.8 + i * .00025, 'voice1.pulseWidth', 701 + i * 401)
            change('250us', 1.8 + i * .00025, 'filter.cutoff', 53 + i * 251)
        change('restore', 1.82, 'voice1.pulseWidth', 2048)
        change('restore', 1.82, 'filter.cutoff', 2047)
    for t, test, noise, release in [(2.498, 1, 1, 3), (2.5, 0, 1, 3),
                                    (2.502, 0, 0, 8), (2.539, 1, 1, 2), (2.541, 0, 0, 5)]:
        change('percussion', t, 'voice3.test', test)
        change('percussion', t, 'voice3.noise', noise)
        change('percussion', t, 'voice3.saw', 1 - noise)
        change('percussion', t, 'voice3.release', release)
    for voice, ids in enumerate(controls):
        envelopes = E.SubElement(E.SubElement(pattern_tracks[voice], 'Automations'), 'Envelopes')
        for slot, key in enumerate(ids):
            outer = E.SubElement(envelopes, 'Envelope')
            put(outer, 'DeviceIndex', 1); put(outer, 'ParameterIndex', slot + 1)
            env = E.SubElement(outer, 'Envelope')
            for k, v in {'PlayMode': 'Points', 'Length': LINES * 256, 'ValueQuantum': '0.0', 'Polarity': 'Unipolar'}.items(): put(env, k, v)
            points = E.SubElement(env, 'Points'); spec = specs[key]
            for units, value in sorted(changes[key].items()):
                normalized = (value - spec['minimum']) / (spec['maximum'] - spec['minimum'])
                assert 0 <= normalized <= 1
                E.SubElement(points, 'Point').text = f'{units},{normalized:.12g},0.0'
    validate_song(root)
    # Consistent archive metadata makes regeneration byte-for-byte reproducible.
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in {'Song.xml': E.tostring(root, encoding='utf-8', xml_declaration=True), **members}.items():
            entry = zipfile.ZipInfo(name, (2026, 11, 17, 0, 0, 0)); entry.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(entry, data)
    output.with_suffix('.expected.json').write_text(json.dumps(expected, indent=2) + '\n')
    return expected


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--template', type=Path, required=True)
    p.add_argument('--bindings', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--product', action='store_true', help='Target installed SIDSynth instead of the diagnostic wrapper')
    p.add_argument('--submillisecond', action='store_true', help='Add an adversarial 250-us control burst')
    p.add_argument('--octave-edit', action='store_true', help='Raise the first voice-1 note by an octave; keep automation identical')
    a = p.parse_args()
    make(a.template, a.bindings, a.output, a.product, a.submillisecond, a.octave_edit)
