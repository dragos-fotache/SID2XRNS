# SPDX-License-Identifier: AGPL-3.0-only
"""Versioned, checked capture boundary between execution and interpretation."""
from dataclasses import dataclass
import hashlib
import json
from .capture import MAX_CALLS, MAX_WRITES
from .errors import ConversionError
from .storage import open_text


@dataclass
class Trace:
    header: dict
    writes: list
    calls: list
    footer: dict


def read_trace(path):
    def require(condition, message):
        if not condition: raise ConversionError('invalid-trace', message)
    def integer(value, lo, hi): return type(value) is int and lo <= value <= hi
    def registers(values): return isinstance(values, list) and len(values) == 25 and all(integer(v, 0, 255) for v in values)
    header = footer = None
    writes = []; calls = []; replay = [0] * 25
    digest = hashlib.sha256(); previous_cycle = -1; init_checked = False
    try:
        with open_text(path) as stream:
            for line_no, line in enumerate(stream, 1):
                require(len(line) <= 100_000, 'Oversized trace row')
                row = json.loads(line)
                require(isinstance(row, dict) and footer is None, 'Unexpected data after footer')
                kind = row.get('type')
                if header is None:
                    require(kind == 'header' and type(row.get('schema')) is int and row['schema'] == 1, 'Expected schema-1 capture header')
                    header = row; profile = header['profile']; init = header['init_cycles']
                    clock = profile['clock']; period = profile['cycles_per_call']
                    require(profile['name'] in ('psid-direct-vbi-v1', 'psid-direct-vbi-v2'), 'Unknown execution profile')
                    require(clock in ('pal', 'ntsc') and profile['model'] in ('6581', '8580'), 'Invalid clock/model')
                    require(type(profile['clock_hz']) is int and profile['clock_hz'] == (985248 if clock == 'pal' else 1022727), 'Invalid source clock')
                    require(type(profile['target_clock_hz']) is int and profile['target_clock_hz'] == (985248 if clock == 'pal' else 1022730), 'Invalid target clock')
                    require(type(period) is int and period == (19656 if clock == 'pal' else 17095), 'Invalid VBI period')
                    require(integer(init, 1, 1_000_000) and integer(header['play_call_budget'], 1, MAX_CALLS), 'Invalid capture budget')
                    require(registers(header['initial_registers']), 'Invalid initial registers')
                    source = header['source']
                    require(source['magic'] == 'PSID' and integer(source['songs'], 1, 256) and integer(profile['subsong'], 1, source['songs']), 'Invalid source/subsong metadata')
                    require(all(isinstance(source[key], str) and len(source[key]) <= 64 for key in ('title', 'author', 'released')), 'Invalid source text metadata')
                    require(isinstance(source['sha256'], str) and len(source['sha256']) == 64 and all(c in '0123456789abcdef' for c in source['sha256']), 'Invalid source digest')
                    continue
                if kind == 'write':
                    require(len(writes) < MAX_WRITES, 'Write budget exceeded')
                    require(type(row['seq']) is int and row['seq'] == len(writes) and integer(row['cycle'], previous_cycle, 10**12), 'Write sequence/time is not monotonic')
                    require(integer(row['register'], 0, 24) and integer(row['value'], 0, 255), 'Invalid SID register/value')
                    require(integer(row['address'], 0xd400, 0xd7ff) and (row['address'] - 0xd400) % 32 == row['register'], 'Invalid SID mirror binding')
                    if row['phase'] == 'init':
                        require(not calls and not init_checked and type(row['call']) is int and row['call'] == -1 and integer(row['call_cycle'], 0, init) and row['cycle'] == row['call_cycle'], 'Invalid init timestamp')
                    else:
                        require(row['phase'] == 'play' and type(row['call']) is int and row['call'] == len(calls), 'Invalid play-call ownership')
                        if not init_checked:
                            require(replay == header['initial_registers'], 'Init snapshot does not match ordered writes'); init_checked = True
                        require(integer(row['call_cycle'], 0, period) and row['cycle'] == init + len(calls) * period + row['call_cycle'], 'Invalid play timestamp')
                    replay[row['register']] = row['value']; writes.append(row)
                    digest.update((json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n').encode())
                    previous_cycle = row['cycle']
                elif kind == 'call':
                    if not init_checked:
                        require(replay == header['initial_registers'], 'Init snapshot does not match ordered writes'); init_checked = True
                    start = init + len(calls) * period
                    require(len(calls) < header['play_call_budget'] and type(row['call']) is int and row['call'] == len(calls) and type(row['start_cycle']) is int and row['start_cycle'] == start, 'Invalid call sequence')
                    require(integer(row['end_cycle'], start + 1, start + period) and row['end_cycle'] >= previous_cycle, 'Invalid call end')
                    require(registers(row['registers']) and row['registers'] == replay, 'Call snapshot does not match write replay')
                    calls.append(row)
                elif kind == 'end':
                    require(row.get('complete') is True and type(row['play_calls']) is int and row['play_calls'] == len(calls) == header['play_call_budget'], 'Incomplete capture')
                    require(type(row['writes']) is int and row['writes'] == len(writes) and row['write_sha256'] == digest.hexdigest(), 'Write count/digest mismatch')
                    require(type(row['end_cycle']) is int and row['end_cycle'] == init + len(calls) * period, 'Invalid capture boundary')
                    footer = row
                else: require(False, 'Unknown trace row type')
    except (KeyError, TypeError, ValueError, UnicodeError, EOFError) as exc:
        raise ConversionError('invalid-trace', f'Malformed capture: {exc}') from exc
    require(header is not None and footer is not None, 'Missing header/footer')
    return Trace(header, writes, calls, footer)
