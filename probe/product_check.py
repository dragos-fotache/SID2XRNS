#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Check the actual installed plugin; record only this scratch host's outputs."""
from array import array
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import time
import wave
import struct
import xml.etree.ElementTree as E
import zipfile
from host import ROOT, WORK, call
from make_fixture import read_preset


def run(name, seconds=5.5):
    if not 1 <= seconds <= 260:
        raise ValueError('Playback duration must be 1–260 seconds')
    state = call('inspect'); process = json.loads((WORK / 'process.json').read_text())
    assert state['pid'] == process['pid'] and Path(state['file']).parent == WORK
    assert [i['alias'] for i in state['instruments']] == [0, 1, 1]
    assert [i['channel'] for i in state['instruments']] == [1, 2, 3]
    path = 'Audio/Generators/VST3/ABCDEF019182FAEB5369647353796469'
    assert all(i['path'] == path for i in state['instruments'])
    with zipfile.ZipFile(state['file']) as z: song = E.fromstring(z.read('Song.xml'))
    _, chunks = read_preset(base64.b64decode(song.findtext('.//PluginDevice/ParameterChunk')))
    component = next(data for tag, data in chunks if tag == b'Comp')
    patch = E.fromstring(component[8:8 + struct.unpack_from('<I', component, 4)[0]])
    assert patch.tag == 'SIDSynthPatch' and patch.get('schemaVersion') in ('3', '4')
    suffix = '-v4' if patch.get('schemaVersion') == '4' else ''
    bindings = json.loads((ROOT / f'fixtures/sidsynth-bindings{suffix}.json').read_text())
    expected = {s['id']: float(patch.get(s['id'])) for s in bindings}
    normalized = {s['id']: (expected[s['id']] - s['minimum']) / (s['maximum'] - s['minimum']) for s in bindings}
    # With FollowAutomations enabled, Renoise reapplies time-zero native points
    # while recalling the song. These deliberately initialize the sound before
    # the first note, overriding a patch saved after later automation playback.
    overrides = []
    tracks = song.findall('./Tracks/SequencerTrack')
    for ti, track in enumerate(song.findall('./PatternPool/Patterns/Pattern/Tracks/PatternTrack')[:3]):
        devices = list(tracks[ti].find('./FilterDevices/Devices'))
        for envelope in track.findall('./Automations/Envelopes/Envelope'):
            device = devices[int(envelope.findtext('DeviceIndex'))]
            if device.tag != 'InstrumentAutomationDevice': continue
            slot = int(envelope.findtext('ParameterIndex')) - 1
            parameter = int(device.findtext(f'ParameterNumber{slot}'))
            first = envelope.findtext('./Envelope/Points/Point').split(',')
            assert int(first[0]) == 0
            key = bindings[parameter]['id']; value = float(first[1])
            if abs(normalized[key] - value) > 1e-6: overrides.append(key)
            normalized[key] = value
    parameters = state['instruments'][0]['parameters']
    # New products append metadata; old schema-3 songs retain their 67 fields.
    assert len(parameters) >= len(bindings)
    for p, spec in zip(parameters, bindings):
        assert p['name'] == spec['name']
        wanted = normalized[spec['id']]
        assert abs(p['value'] - wanted) < 1e-6, (spec['id'], p['value'], wanted)
    def objects(): return json.loads(subprocess.check_output(['pw-dump']))
    graph = objects()
    clients = {o['id'] for o in graph if o.get('type') == 'PipeWire:Interface:Client' and
               str(o.get('info', {}).get('props', {}).get('application.process.id')) == str(state['pid'])}
    nodes = {o['id'] for o in graph if o.get('type') == 'PipeWire:Interface:Node' and
             o.get('info', {}).get('props', {}).get('client.id') in clients and o.get('info', {}).get('n-output-ports') == 2}
    assert len(nodes) == 1
    sources = sorted([o for o in graph if o.get('type') == 'PipeWire:Interface:Port' and
                      o.get('info', {}).get('props', {}).get('node.id') in nodes and o['info']['direction'] == 'output'],
                     key=lambda o: o['info']['props']['port.id'])
    monitor = [(o['info']['output-port-id'], o['info']['input-port-id']) for o in graph
               if o.get('type') == 'PipeWire:Interface:Link' and o['info']['output-node-id'] in nodes]
    recorder = None
    try:
        for a, b in monitor: subprocess.run(['pw-link', '-d', str(a), str(b)], check=True)
        node_name = f"sid2xrns-product-recording-{state['pid']}"
        audio_file = WORK / (name + '.wav')
        recorder = subprocess.Popen(['pw-record', '--target', '0', '--rate', '48000', '--channels', '2',
            '--format', 's16', '--properties', json.dumps({'node.name': node_name}), '-n', str(round((seconds + 1.5) * 48000)), str(audio_file)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for _ in range(60):
            graph = objects()
            targets = {o['id'] for o in graph if o.get('type') == 'PipeWire:Interface:Node' and
                       o.get('info', {}).get('props', {}).get('node.name') == node_name}
            ports = sorted([o for o in graph if o.get('type') == 'PipeWire:Interface:Port' and
                            o.get('info', {}).get('props', {}).get('node.id') in targets and o['info']['direction'] == 'input'],
                           key=lambda o: o['info']['props']['port.name'])
            if len(ports) == 2: break
            time.sleep(.05)
        assert len(ports) == 2
        for a, b in zip(sources, ports): subprocess.run(['pw-link', str(a['id']), str(b['id'])], check=True)
        time.sleep(.25)  # Record a stopped baseline even for songs starting at row 1.
        call('play')
        remaining = seconds
        while remaining > 0:
            interval = min(30, remaining); time.sleep(interval); remaining -= interval
            print(f'Recorded {seconds - remaining:.1f}/{seconds:.1f} playback seconds', flush=True)
        call('stop')
        _, errors = recorder.communicate(timeout=7)
        assert not errors, errors.decode()
        with wave.open(str(audio_file)) as w:
            assert w.getframerate() == 48000 and w.getnchannels() == 2 and w.getsampwidth() == 2
            audio = array('h', w.readframes(w.getnframes()))
        left, right = audio[::2], audio[1::2]
        assert left == right and len(left) >= round((seconds + 1.5) * 48000) - 64
        assert 0 < max(map(abs, left)) < 32760
        assert max(map(abs, left[:12000])) == 0
        assert max(map(abs, left[-24000:])) == 0
        result = {'pid': state['pid'], 'aliases': [i['alias'] for i in state['instruments']],
                  'channels': [i['channel'] for i in state['instruments']], 'parameters_verified': len(bindings),
                  'peak': max(map(abs, left)) / 32768, 'silent_after_stop': True, 'stereo_equal': True,
                  'playback_seconds': seconds, 'recording_frames': len(left),
                  'source_ports': [p['id'] for p in sources], 'monitor_links_restored': monitor,
                  'saved_patch_values_overridden_by_time_zero_automation': overrides,
                  'installed_module_sha256': hashlib.sha256((Path.home() / '.vst3/SIDSynth.vst3/Contents/x86_64-linux/SIDSynth.so').read_bytes()).hexdigest()}
    finally:
        if recorder is not None and recorder.poll() is None:
            recorder.terminate(); recorder.wait(timeout=3)
        call('stop'); time.sleep(.1)
        for a, b in monitor: subprocess.run(['pw-link', str(a), str(b)], check=True)
    (WORK / (name + '-check.json')).write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--name',default='installed-product')
    p.add_argument('--seconds', type=float, default=5.5)
    args = p.parse_args(); run(args.name, args.seconds)
