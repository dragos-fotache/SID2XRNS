#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Private-profile Renoise timing checks. No changes to the normal profile."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work'
URL = 'http://127.0.0.1:19716/mcp'


def call(operation, **args):
    payload = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
               'params': {'name': 'xrns_timing', 'arguments': {'operation': operation, **args}}}
    request = urllib.request.Request(URL, data=json.dumps(payload).encode(),
                                    headers={'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'})
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.load(response)
    if 'error' in result or result.get('result', {}).get('isError'):
        raise RuntimeError(result)
    value = json.loads(result['result']['content'][0]['text'])
    with (WORK / 'host-transcript.jsonl').open('a') as f:
        f.write(json.dumps({'time': time.time(), 'operation': operation, 'args': args, 'result': value}) + '\n')
    return value


def launch(args):
    from xml.etree import ElementTree as E
    profile = WORK / f'profile-{args.label}'
    assert not profile.exists(), 'Choose a fresh label; never overwrite a profile'
    directory = profile / 'Renoise/V3.5.4'
    directory.mkdir(parents=True)
    config = E.parse(args.config)
    # Changes apply only to this private file. JACK/PipeWire quantum is requested
    # per process, not by changing server-wide settings. Actual sizes are traced.
    config.write(directory / 'Config.xml', encoding='utf-8', xml_declaration=True)
    tool = directory / 'Scripts/Tools/com.renoise.ReMCP.xrnx'
    shutil.copytree(args.remcp, tool)
    for p in (tool / 'tools').glob('*.lua'):
        p.unlink()
    shutil.copy(ROOT / 'probe/host.lua', tool / 'tools/xrns_timing.lua')
    (tool / 'sid2xrns-root.txt').write_text(f'{WORK}\n{profile}\n')
    for p in tool.rglob('*.lua'):
        p.write_text(p.read_text().replace('19715', '19716').replace('19714', '19716'))
    trace = WORK / f'traces-{args.label}'
    trace.mkdir()
    plugin = args.plugin_dir or WORK / 'build/SIDXRNSTimingProbe_artefacts/Release/VST3'
    assert plugin.exists()
    env = dict(os.environ, XDG_CONFIG_HOME=str(profile), VST3_PATH=str(plugin), SID2XRNS_TRACE_DIR=str(trace),
               PIPEWIRE_LATENCY=f'{args.quantum}/48000', PIPEWIRE_QUANTUM=str(args.quantum),
               SID2XRNS_CAPTURE_SECONDS=str(args.capture_seconds))
    log = (WORK / f'renoise-{args.label}.log').open('w')
    process = subprocess.Popen(['renoise', *([str(WORK / args.song)] if args.song else [])], env=env,
                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    result = {'pid': process.pid, 'profile': str(profile), 'trace': str(trace), 'label': args.label,
              'requested_quantum': args.quantum}
    (WORK / 'process.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


def capture(args):
    process = json.loads((WORK / 'process.json').read_text())
    state = call('inspect')
    assert state['pid'] == process['pid']
    assert Path(state['file']).parent == WORK
    assert [i['alias'] for i in state['instruments'][:3]] == [0, 1, 1]
    assert [i['channel'] for i in state['instruments'][:3]] == [1, 2, 3]
    trace = Path(process['trace'])
    # Complete any construction/recall take before the new arm handshake.
    before_freeze = set(trace.glob('trace-*.json'))
    call('capture', value=1)
    time.sleep(.5)
    frozen = set(trace.glob('trace-*.json')) - before_freeze
    before = set(trace.glob('trace-*.json'))
    call('capture', value=.5)
    time.sleep(.25)
    call('play')
    time.sleep(args.seconds)
    call('stop')
    time.sleep(.3)
    call('capture', value=1)
    for _ in range(30):
        new = set(trace.glob('trace-*.json')) - before
        if len(new) >= 1:
            break
        time.sleep(.1)
    assert len(new) == 1, new
    files = sorted(new, key=lambda p: p.stat().st_mtime)
    (WORK / f'{args.name}.json').write_text(json.dumps({'process': process, 'trace': str(files[-1]),
        'initial_trace': str(next(iter(frozen))) if frozen else None, 'host_state': state}, indent=2) + '\n')
    print(json.dumps({'capture': args.name, 'trace': str(files[-1])}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    launch_parser = sub.add_parser('launch')
    launch_parser.add_argument('--config', type=Path, required=True)
    launch_parser.add_argument('--remcp', type=Path, required=True)
    launch_parser.add_argument('--label', required=True)
    launch_parser.add_argument('--quantum', type=int, default=1024)
    launch_parser.add_argument('--capture-seconds', type=int, choices=range(30, 261), default=30,
                               metavar='30..260', help='Preallocated diagnostic take capacity')
    launch_parser.add_argument('--song')
    launch_parser.add_argument('--plugin-dir', type=Path, help='Override the private plugin scan directory')
    c = sub.add_parser('capture')
    c.add_argument('--name', required=True)
    c.add_argument('--seconds', type=float, default=6)
    c = sub.add_parser('call')
    c.add_argument('operation')
    c.add_argument('--name')
    c.add_argument('--value', type=float)
    a = p.parse_args()
    if a.command == 'launch': launch(a)
    elif a.command == 'capture': capture(a)
    else: print(json.dumps(call(a.operation, **{k: v for k, v in {'name': a.name, 'value': a.value}.items() if v is not None}), indent=2))
