# SPDX-License-Identifier: AGPL-3.0-only
"""Write editable notes and native sound automation through validated assets."""
import base64
import bisect
import copy
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile
from .errors import ConversionError
from .interpret import VOICE_FIELDS, GLOBAL_FIELDS
from .native import PRODUCT_ID, PROBE_ID, put, replace_patch, validate_song
from .storage import atomic_file

ROOT = Path(__file__).resolve().parents[1]
PATTERN_LINES = 256


def verify_assets(schema=3):
    suffix = '-v4' if schema == 4 else ''
    manifest = json.loads((ROOT / f'docs/runtime-lock{suffix}.json').read_text())
    for name, expected in manifest['files'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise ConversionError('runtime-lock-mismatch', f'Pinned runtime asset changed: {name}')
    bindings = json.loads((ROOT / f'fixtures/sidsynth-bindings{suffix}.json').read_text())
    count = 80 if schema == 4 else 67
    if len(bindings) != count or len({s['id'] for s in bindings}) != count:
        raise ConversionError('invalid-bindings', f'Expected all {count} unique SIDSynth parameter IDs')
    return bindings


def clean_text(text):
    return ''.join(c if ord(c) >= 32 or c in '\n\t\r' else '\ufffd' for c in text)


def write_song(performance, output, diagnostic=False):
    schema = performance.report.get('parameter_schema', 3)
    bindings = verify_assets(schema); specs = {s['id']: s for s in bindings}; indices = {s['id']: i for i, s in enumerate(bindings)}
    if set(performance.initial) != set(specs):
        raise ConversionError('invalid-patch', 'The initial patch must define every stable parameter once')
    def normalized(key, value):
        spec = specs[key]
        if not isinstance(value, (float, int)) or not math.isfinite(value) or not spec['minimum'] <= value <= spec['maximum']:
            raise ConversionError('invalid-parameter-value', f'Invalid value for {key}: {value}')
        return (value - spec['minimum']) / (spec['maximum'] - spec['minimum'])
    template_path = ROOT / ('fixtures/native-template-v4.xrns' if schema == 4 else 'fixtures/native-template.xrns')
    with zipfile.ZipFile(template_path) as z:
        root = E.fromstring(z.read('Song.xml'))
        members = {n: z.read(n) for n in z.namelist() if n != 'Song.xml'}
    plugin = root.find('./Instruments/Instrument/PluginGenerator/PluginDevice')
    if plugin.findtext('PluginIdentifier') != PROBE_ID:
        raise ConversionError('invalid-template', 'Expected the validated native template identity')
    patch = E.Element('SIDSynthPatch', schemaVersion=str(schema), **{s['id']: str(performance.initial[s['id']]) for s in bindings})
    identifier = PROBE_ID if diagnostic else PRODUCT_ID
    put(plugin, 'ParameterChunk', base64.b64encode(replace_patch(base64.b64decode(plugin.findtext('ParameterChunk')), patch, identifier)).decode())
    put(plugin, 'PluginIdentifier', identifier)
    name = 'SID XRNS Timing Probe' if diagnostic else 'SIDSynth'
    put(plugin, 'PluginDisplayName', 'VST3: SIDSynth: ' + name); put(plugin, 'PluginShortDisplayName', name)
    parameters = plugin.find('Parameters')
    if len(parameters) != len(bindings) + 1: raise ConversionError('invalid-template', 'Unexpected template parameter count')
    for i, spec in enumerate(bindings): put(parameters[i], 'Value', f'{normalized(spec["id"], performance.initial[spec["id"]]):.12g}')
    if diagnostic: put(parameters[-1], 'Value', .5)
    else: parameters.remove(parameters[-1])
    for v, instrument in enumerate(root.findall('./Instruments/Instrument')):
        put(instrument, 'Name', f'SID voice {v + 1}')
        generator = instrument.find('PluginGenerator')
        put(generator, 'Channel', v); put(generator, 'AutoSuspend', 'false'); put(generator, 'AliasInstrumentIndex', -1 if v == 0 else 0)
        if v:
            for d in list(generator):
                if d.tag == 'PluginDevice': generator.remove(d)
    data = root.find('GlobalSongData'); source = performance.report['source']
    for key, value in {'SongName': clean_text(source['title'] or 'SID capture'), 'Artist': clean_text(source['author']),
                       'BeatsPerMin': 125, 'LinesPerBeat': 24, 'TicksPerLine': 16,
                       'FollowAutomations': 'true', 'ShowSongCommentsAfterLoading': 'false'}.items(): put(data, key, value)
    control_template = copy.deepcopy(root.find('.//InstrumentAutomationDevice'))
    track_ids = []
    for v, track in enumerate(root.findall('./Tracks/SequencerTrack')):
        put(track, 'Name', f'SID voice {v + 1}')
        put(track, 'NumberOfVisibleNoteColumns', 1); put(track, 'NumberOfVisibleEffectColumns', 1); put(track, 'DelayColumnIsVisible', 'true')
        from .envelope_cues import CUE_FIELDS
        fields = VOICE_FIELDS + (CUE_FIELDS if schema == 4 else ())
        ids = [f'voice{v + 1}.{f}' for f in fields] + (list(GLOBAL_FIELDS) if v == 0 else [])
        if len(ids) > 35: raise ConversionError('mapping-overflow', 'Native device has only 35 control slots')
        track_ids.append(ids)
        devices = track.find('./FilterDevices/Devices')
        for d in list(devices)[1:]: devices.remove(d)
        control = copy.deepcopy(control_template); put(control, 'LinkedInstrument', 0); put(control, 'VisiblePages', math.ceil(len(ids) / 5))
        for slot in range(35):
            key = ids[slot] if slot < len(ids) else None
            put(control, f'ParameterNumber{slot}', indices[key] if key else -1)
            put(control, f'ParameterValue{slot}/Value', normalized(key, performance.initial[key]) if key else 0)
        devices.append(control)
    pool = root.find('./PatternPool/Patterns'); template = copy.deepcopy(pool[0]); pool.clear()
    sequence = root.find('./PatternSequence/SequenceEntries'); sequence.clear()
    lines = math.ceil(performance.end_units / 256)
    note_count = 0
    points = {key: sorted(values.items()) for key, values in performance.automation.items()}
    point_units = {key: [u for u, _ in values] for key, values in points.items()}
    notes_by_row = {}
    for note in performance.notes:
        cell = (note['voice'], note['units'] // 256)
        if cell in notes_by_row: raise ConversionError('unresolved-note-collision', 'Interpretation did not resolve a native note cell')
        notes_by_row[cell] = note
    count = math.ceil(lines / PATTERN_LINES)
    if count > 1000: raise ConversionError('song-too-large', 'Export exceeds the initial 1000-pattern cap')
    for pattern_index, first_row in enumerate(range(0, lines, PATTERN_LINES)):
        n = min(PATTERN_LINES, lines - first_row); lo = first_row * 256; hi = lo + n * 256
        pattern = copy.deepcopy(template); put(pattern, 'NumberOfLines', n); put(pattern, 'Name', f'Capture {pattern_index + 1:03d}')
        for ti, track in enumerate(pattern.find('Tracks')):
            for tag in ('Lines', 'Automations'):
                old = track.find(tag)
                if old is not None: track.remove(old)
            if ti >= 3: continue
            native_lines = E.SubElement(track, 'Lines')
            for row in range(first_row, first_row + n):
                note = notes_by_row.get((ti, row))
                if note is None: continue
                line = E.SubElement(native_lines, 'Line', index=str(row - first_row))
                column = E.SubElement(E.SubElement(line, 'NoteColumns'), 'NoteColumn')
                pitch = note['note']
                if pitch is not None and not 0 <= pitch <= 119: raise ConversionError('invalid-note', 'Native note is out of range')
                text = 'OFF' if pitch is None else ('C-', 'C#', 'D-', 'D#', 'E-', 'F-', 'F#', 'G-', 'G#', 'A-', 'A#', 'B-')[pitch % 12] + str(pitch // 12)
                put(column, 'Note', text); put(column, 'Instrument', f'{ti:02X}')
                if note['units'] % 256: put(column, 'Delay', f'{note["units"] % 256:02X}')
                note_count += 1
            envelopes = E.SubElement(E.SubElement(track, 'Automations'), 'Envelopes')
            for slot, key in enumerate(track_ids[ti]):
                outer = E.SubElement(envelopes, 'Envelope'); put(outer, 'DeviceIndex', 1); put(outer, 'ParameterIndex', slot + 1)
                envelope = E.SubElement(outer, 'Envelope')
                for name, value in {'PlayMode': 'Points', 'Length': n * 256, 'ValueQuantum': '0.0', 'Polarity': 'Unipolar'}.items(): put(envelope, name, value)
                p = E.SubElement(envelope, 'Points')
                start = bisect.bisect_right(point_units[key], lo) - 1
                values = {0: points[key][start][1]}
                for unit, value in points[key][start + 1:]:
                    if unit >= hi: break
                    values[unit - lo] = value
                for unit, value in sorted(values.items()):
                    E.SubElement(p, 'Point').text = f'{unit},{normalized(key, value):.12g},0.0'
        pool.append(pattern)
        entry = E.SubElement(sequence, 'SequenceEntry'); put(entry, 'Pattern', pattern_index)
        put(entry, 'IsSectionStart', 'true' if pattern_index == 0 else 'false'); put(entry, 'SectionName', 'Captured window' if pattern_index == 0 else '')
    put(root, 'SelectedTrackIndex', 0); put(root, 'SelectedInstrumentIndex', 0); put(root.find('PatternSequence'), 'CurrentPosition', 0)
    validate_song(root)
    with atomic_file(output) as temp:
        with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as z:
            for name, data in {'Song.xml': E.tostring(root, encoding='utf-8', xml_declaration=True), **members}.items():
                entry = zipfile.ZipInfo(name, (2026, 11, 17, 0, 0, 0)); entry.compress_type = zipfile.ZIP_DEFLATED
                z.writestr(entry, data)
    return {'patterns': count, 'rows': lines, 'note_cells': note_count, 'plugin_instances': 1,
            'alias_channels': [2, 3], 'patch_schema': schema, 'parameter_bindings': len(bindings),
            'template_sha256': hashlib.sha256(template_path.read_bytes()).hexdigest(),
            'diagnostic_target': diagnostic}
