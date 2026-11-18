# SPDX-License-Identifier: AGPL-3.0-only
"""Run the pinned installed VICE, never the exporter's CPU or captured writes."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import wave

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_lock():
    lock = json.loads((ROOT / 'docs/reference-lock.json').read_text())
    for path, expected in lock['files'].items():
        if digest(path) != expected:
            raise ValueError(f'Reference lock mismatch: {path}; review before re-pinning')
    return lock


def monitor_rows(text):
    """Pair VICE checkpoint descriptions with its CPU cycle counter."""
    rows = []; pending = None
    for line in text.splitlines():
        match = re.match(r'#\d+ \(Trace\s+(store|exec) ([0-9a-f]+)\)', line, re.I)
        if match:
            pending = (match[1].lower(), int(match[2], 16))
        elif pending and line.startswith('.C:'):
            clock = re.search(r'\s(\d+)\s*$', line)
            if not clock:
                raise ValueError('Unrecognized VICE monitor cycle counter')
            rows.append({'kind': pending[0], 'address': pending[1], 'cycle': int(clock[1])})
            pending = None
    return rows


def parse_dump(text, stores):
    """Dump values are physical writes; monitor lines calibrate the sound clock."""
    rows = []; clock = 0
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 3:
            raise ValueError('Malformed VICE sound dump')
        delta, reg, value = map(int, parts)
        if delta < 0 or not 0 <= reg <= 24 or not 0 <= value <= 255:
            raise ValueError('Invalid VICE dump range')
        clock += delta
        rows.append({'cycle': clock, 'register': reg, 'value': value})
    if len(rows) != len(stores) or not rows:
        raise ValueError(f'VICE dump/monitor write count differs: {len(rows)}/{len(stores)}')
    offsets = set()
    for row, store in zip(rows, stores):
        if row['register'] != (store['address'] - 0xd400) % 32:
            raise ValueError('VICE dump/monitor register order differs')
        offsets.add(store['cycle'] - row['cycle'])
    if len(offsets) != 1:
        raise ValueError(f'VICE sound/CPU clock calibration is not constant: {offsets}')
    offset = offsets.pop()
    for row in rows:
        row['cycle'] += offset
    return rows, offset


def render(sid_path, output, calls, model=None, subsong=None):
    # Header parsing only supplies addresses/settings; VICE independently loads
    # and executes the original SID, including its own PSID driver and interrupts.
    from sid2xrns.psid import read
    lock = verify_lock(); sid_path = Path(sid_path).resolve()
    sid = read(sid_path); profile = sid.profile(subsong=subsong, model=model)
    if not 1 <= calls <= 12000:
        raise ValueError('Reference window must contain 1–12000 play calls')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Trace all SID writes to verify dump ordering/clock origin rather than
    # guessing what a store instruction wrote. Execution traces count calls.
    script = output / 'commands.mon'
    script.write_text(f'trace store d400 d7ff\ntrace exec {sid.init_address:04x}\n'
                      f'trace exec {sid.play_address:04x}\nx\n')
    period = profile['cycles_per_call']
    # Independent driver init may take longer than the direct-call profile.
    # Extra calls provide a checked crop, never a guessed song ending.
    limit = 1_100_000 + (calls + 3) * period
    base = ['/usr/bin/vsid', '-default', '-console', '-verbose', '-logtostdout',
            '-seed', '1', '-nativemonitor', '-monlog', '-moncommands', str(script),
            '-initbreak', 'reset', '-limitcycles', str(limit), '-soundrate', '48000',
            '-soundoutput', '1', '-keepenv', '-' + profile['clock'],
            '-sidenginemodel', '257' if profile['model'] == '8580' else '256',
            '-residsamp', '2', '-tune', str(profile['subsong'])]
    commands = {}
    for mode in ('dump', 'audio'):
        command = base + ['-monlogname', str(output / f'{mode}.monitor.log')]
        if mode == 'dump':
            command += ['-warp', '-soundwarpmode', '1', '-sounddev', 'dump',
                        '-soundarg', str(output / 'writes.dump')]
        else:
            command += ['-sounddev', 'alsa', '-soundarg', 'null', '-soundrecdev', 'wav',
                        '-soundrecarg', str(output / 'raw.wav')]
        command += [str(sid_path)]; commands[mode] = command
        print(f'VICE {mode}: {calls} requested calls', flush=True)
        with (output / f'{mode}.log').open('w') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=90 + calls * period / profile['clock_hz'] * 2)
        log = (output / f'{mode}.log').read_text()
        if result.returncode not in (0, 1) or 'cycle limit reached' not in log.lower():
            raise ValueError(f'VICE did not finish its bounded {mode} run; see {output / (mode + ".log")}')
        if 'buffer overflow' in log.lower() or 'sound: error' in log.lower():
            raise ValueError('VICE reference reported an audio buffer error')
    dump = monitor_rows((output / 'dump.monitor.log').read_text())
    audio = monitor_rows((output / 'audio.monitor.log').read_text())
    if dump != audio:
        raise ValueError('Independent dump/audio CPU timelines differ')
    entries = [r['cycle'] for r in dump if r['kind'] == 'exec' and r['address'] == sid.play_address]
    if len(entries) < calls + 1:
        raise ValueError('VICE did not execute the requested play-call window')
    writes, offset = parse_dump((output / 'writes.dump').read_text(), [r for r in dump if r['kind'] == 'store'])
    start, end = entries[0], entries[calls]
    # Preserve driver/init writes separately; only the explicit play window is
    # compared to the direct-call capture. IRQ/VIC scheduling remains measured.
    result = {'schema': 1, 'reference': lock, 'source_sha256': digest(sid_path), 'profile': profile,
              'play_calls': calls, 'first_play_cycle': start, 'end_cycle': end,
              'sound_clock_offset_cycles': offset, 'play_entries': entries[:calls + 1],
              'writes': [r for r in writes if start <= r['cycle'] < end],
              'initial_writes': [r for r in writes if r['cycle'] < start], 'commands': commands,
              'limitations': ['VICE reSID differs from SIDSynth libresidfp',
                              'Native PSID IRQ/VIC timing differs from fixed direct calls',
                              'Init histories and settled plugin state differ',
                              'Audio crop uses calibrated sound/CPU origin; global audio alignment is also reported']}
    with wave.open(str(output / 'raw.wav')) as wav:
        if wav.getframerate() != 48000 or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
            raise ValueError('Invalid VICE reference WAV format')
        first = round((start - offset) * 48000 / profile['clock_hz'])
        length = round((end - start) * 48000 / profile['clock_hz'])
        if wav.getnframes() < first + length:
            raise ValueError('VICE WAV is shorter than the checked capture window')
        wav.setpos(first); frames = wav.readframes(length)
    with wave.open(str(output / 'reference.wav'), 'wb') as wav:
        wav.setparams((1, 2, 48000, 0, 'NONE', 'not compressed')); wav.writeframes(frames)
    result['reference_wav_sha256'] = digest(output / 'reference.wav')
    result['dump_sha256'] = digest(output / 'writes.dump')
    (output / 'reference.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'reference': str(output / 'reference.wav'), 'writes': len(result['writes']),
                      'calls': calls, 'seconds': length / 48000}), flush=True)
    return result
