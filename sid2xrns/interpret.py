# SPDX-License-Identifier: AGPL-3.0-only
"""Turn ordered writes into real note ownership and relative sound controls."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from fractions import Fraction
import math

from .envelope import LFSR, RATE_POSITIONS

UNITS_PER_SECOND = 12800
UNITS_PER_ROW = 256
ROW_SECONDS = Fraction(UNITS_PER_ROW, UNITS_PER_SECOND)
VOICE_FIELDS = ('tuning', 'pulseWidth', 'attack', 'decay', 'sustain', 'release',
                'triangle', 'saw', 'pulse', 'noise', 'sync', 'ring', 'test')
GLOBAL_FIELDS = ('filter.cutoff', 'filter.resonance', 'filter.voice1', 'filter.voice2',
                 'filter.voice3', 'filter.external', 'filter.lowPass', 'filter.bandPass',
                 'filter.highPass', 'chip.volume', 'chip.voice3Direct')


@dataclass
class Performance:
    initial: dict
    notes: list
    automation: dict
    end_units: int
    report: dict


def controls(registers):
    r = registers
    result = {'filter.cutoff': (r[22] << 3) | (r[21] & 7), 'filter.resonance': r[23] >> 4,
              'chip.volume': r[24] & 15, 'chip.voice3Direct': int(not r[24] & 128)}
    for i, name in enumerate(('voice1', 'voice2', 'voice3', 'external')):
        result['filter.' + name] = int(bool(r[23] & (1 << i)))
    for bit, name in zip((16, 32, 64), ('lowPass', 'bandPass', 'highPass')):
        result['filter.' + name] = int(bool(r[24] & bit))
    for v in range(3):
        base = v * 7; p = f'voice{v + 1}.'
        result.update({p + 'pulseWidth': r[base + 2] | ((r[base + 3] & 15) << 8),
                       p + 'attack': r[base + 5] >> 4, p + 'decay': r[base + 5] & 15,
                       p + 'sustain': r[base + 6] >> 4, p + 'release': r[base + 6] & 15})
        for bit, field in zip((16, 32, 64, 128, 2, 4, 8), ('triangle', 'saw', 'pulse', 'noise', 'sync', 'ring', 'test')):
            result[p + field] = int(bool(r[base + 4] & bit))
    return result


def frequency(registers, voice): return registers[voice * 7] | (registers[voice * 7 + 1] << 8)


def pitch(register, clock):
    return 69 + 12 * math.log2(register * clock / (16777216 * 440)) if register else -math.inf


def release_end(notes, automation, boundary, clock):
    # From full level, the SID exponential divider takes 756 rate ticks to
    # reach zero. An interrupted attack can retain a divider of 2 at level
    # 254, adding up to 161 ticks. Allow another tick for the pipeline and
    # a full LFSR turn for a rate match missed on entry to release.
    rate_units = [
        math.ceil(Fraction((918 * (position + 1) + len(LFSR)) * UNITS_PER_SECOND, clock))
        for position in RATE_POSITIONS
    ]
    note_offs = {}
    for note in notes:
        voice = note['voice']
        if note['note'] is not None:
            note_offs[voice] = None
        elif voice in note_offs and note_offs[voice] is None:
            note_offs[voice] = note['units']
    end = boundary + UNITS_PER_ROW
    for voice, off in note_offs.items():
        if off is None:
            continue
        changes = automation[f'voice{voice + 1}.release']
        rate = changes[max(unit for unit in changes if unit <= off)]
        deadline = off + rate_units[rate] + UNITS_PER_ROW
        for unit, rate in changes.items():
            if unit <= off:
                continue
            if unit >= deadline:
                break
            # A release rate change can miss a counter match again. Allow
            # for the new rate while the voice could still be decaying.
            deadline = unit + rate_units[rate] + UNITS_PER_ROW
        end = max(end, deadline)
    return math.ceil(Fraction(end, UNITS_PER_ROW)) * UNITS_PER_ROW


def interpret(trace, gain_db=-12):
    profile = trace.header['profile']; clock = profile['clock_hz']; target_clock = profile['target_clock_hz']
    init_cycles = trace.header['init_cycles']; regs = list(trace.header['initial_registers'])
    issues = Counter(); examples = defaultdict(list)
    def issue(code, **details):
        issues[code] += 1
        if len(examples[code]) < 8: examples[code].append(details)
    def units(cycle): return round(Fraction((cycle - init_cycles) * UNITS_PER_SECOND, clock))
    def anchor(r, v, call):
        # Notes label a playable segment, rather than a transient half-written
        # frequency word. Only the anchor uses a call-end snapshot; all timed
        # sound controls still come from the ordered write stream below.
        stable = trace.calls[max(0, call)]['registers']
        f = frequency(stable, v)
        if stable[v * 7 + 4] & 0xf0 == 0x80:
            for candidate in trace.calls[max(0, call):max(0, call) + 3]:
                other = candidate['registers']
                if other[v * 7 + 4] & 0x70 and frequency(other, v):
                    f = frequency(other, v); break
        return min(119, max(0, round(pitch(f, target_clock)))) if f else 0
    groups = defaultdict(list)
    for row in trace.writes:
        if row['phase'] == 'play': groups[units(row['cycle'])].append(row)
    candidates = []
    init_gate_voices = {row['register'] // 7 for row in trace.writes
                       if row['phase'] == 'init' and row['register'] in (4, 11, 18) and row['value'] & 1}
    for v in range(3):
        if v in init_gate_voices: issue('initial-gate-history-not-replayed', voice=v)
        if regs[v * 7 + 4] & 1:
            candidates.append({'units': 0, 'voice': v, 'note': anchor(regs, v, 0), 'source': 'init-final-gate'})
    snapshots = {0: list(regs)}
    max_rounding = 0
    for unit, rows in sorted(groups.items()):
        initial_gates = [bool(regs[v * 7 + 4] & 1) for v in range(3)]
        edges = [[], [], []]
        counts = Counter()
        for row in rows:
            address, value = row['register'], row['value']
            if address in (4, 11, 18) and bool(regs[address] & 1) != bool(value & 1):
                edges[address // 7].append({'cycle': row['cycle'], 'gate': bool(value & 1)})
            if value != regs[address]: counts[address] += 1
            regs[address] = value
            max_rounding = max(max_rounding, abs(float(Fraction(unit, UNITS_PER_SECOND) - Fraction(row['cycle'] - init_cycles, clock))))
        snapshots[unit] = list(regs)
        for address, count in counts.items():
            if count > 1: issue('same-register-quantum-collision', units=unit, register=address, changes=count)
        for v in range(3):
            final = bool(regs[v * 7 + 4] & 1)
            if not edges[v]: continue
            expected_edges = 1 if initial_gates[v] != final else (2 if final else 0)
            if len(edges[v]) > expected_edges or (len(edges[v]) > 1 and initial_gates[v] == final):
                issue('sub-quantum-gate-sequence', voice=v, units=unit, edges=edges[v], represented_edges=expected_edges)
            if final:
                candidates.append({'units': unit, 'voice': v, 'note': anchor(regs, v, rows[-1]['call']), 'source': 'captured-gate'})
            elif initial_gates[v]:
                candidates.append({'units': unit, 'voice': v, 'note': None, 'source': 'captured-gate'})
    # One physical note column per voice. Keep the final event in a row and
    # report every reduced row; never pretend a hidden manual gate did the work.
    cells = defaultdict(list)
    for event in candidates: cells[(event['voice'], event['units'] // UNITS_PER_ROW)].append(event)
    notes = []
    for (v, row), events in sorted(cells.items(), key=lambda p: (p[0][1], p[0][0])):
        if len(events) > 1: issue('note-row-collision', voice=v, row=row, dropped=events[:-1], retained=events[-1])
        notes.append(events[-1])
    duration = Fraction(trace.footer['end_cycle'] - init_cycles, clock)
    boundary = math.ceil(duration / ROW_SECONDS) * UNITS_PER_ROW
    held = [False] * 3
    for event in sorted(notes, key=lambda n: (n['units'], n['voice'])): held[event['voice']] = event['note'] is not None
    for v, gate in enumerate(held):
        if gate: notes.append({'units': boundary, 'voice': v, 'note': None, 'source': 'capture-boundary'})
    notes.sort(key=lambda n: (n['units'], n['voice']))
    by_time = defaultdict(list)
    for note in notes: by_time[note['units']].append(note)
    patch = {'output.gainDb': gain_db, 'midi.mode': 0, 'midi.layeredChannel': 1,
             'chip.model': int(profile['model'] == '8580'), 'chip.clock': int(profile['clock'] == 'ntsc')}
    for v in range(3):
        patch.update({f'voice{v + 1}.midiChannel': v + 1, f'voice{v + 1}.source': 0,
                      f'voice{v + 1}.manualGate': 0, f'voice{v + 1}.frequency': frequency(trace.header['initial_registers'], v)})
    current = list(trace.header['initial_registers']); references = [None] * 3
    initial_controls = controls(current)
    initial_controls.update({f'voice{v + 1}.tuning': 0 for v in range(3)})
    automation = {k: {0: value} for k, value in initial_controls.items()}
    previous = dict(initial_controls); max_register_error = 0; frequency_checks = 0
    last_unowned = [None] * 3; last_clipped = [None] * 3
    for unit in sorted(set(snapshots) | set(by_time)):
        current = snapshots.get(unit, current)
        for note in by_time[unit]:
            if note['note'] is not None: references[note['voice']] = note['note']
        values = controls(current)
        for v in range(3):
            f = frequency(current, v); reference = references[v]; key = f'voice{v + 1}.tuning'
            if reference is None:
                values[key] = 0
                if f and last_unowned[v] != f:
                    issue('frequency-before-note-ownership', voice=v, units=unit, register=f)
                last_unowned[v] = f
                continue
            wanted = pitch(f, target_clock) - reference
            if not math.isfinite(wanted) or not -96 <= wanted <= 96:
                if last_clipped[v] != (f, reference):
                    issue('zero-frequency-not-representable' if not f else 'relative-pitch-out-of-range',
                          voice=v, units=unit, register=f, reference=reference)
                last_clipped[v] = (f, reference)
            else: last_clipped[v] = None
            tuning = round(max(-96, min(96, wanted)), 2)
            values[key] = tuning
            reconstructed = min(65535, max(0, round(440 * 2 ** ((reference - 69 + tuning) / 12) * 16777216 / target_clock)))
            frequency_checks += 1; max_register_error = max(max_register_error, abs(reconstructed - f))
        for key, value in values.items():
            if value != previous[key]: automation[key][unit] = value
        previous = values
        if unit == 0: patch.update(values)
    patch = {**initial_controls, **patch}
    # Ensure time-zero values agree between the saved patch and native envelopes.
    for key in automation: automation[key][0] = patch[key]
    risks = 0
    for key, points in automation.items():
        previous_unit = None
        for unit in sorted(points):
            if previous_unit is not None and Fraction(unit - previous_unit, UNITS_PER_SECOND) < Fraction(16, 48000): risks += 1
            previous_unit = unit
    end_units = release_end(notes, automation, boundary, target_clock)
    report = {'source': trace.header['source'], 'profile': profile,
              'boundary': trace.header['boundary'], 'play_calls': len(trace.calls),
              'note_anchor_policy': 'nearest call-end frequency; noise-only attacks prefer a tonal snapshot within three calls',
              'capture_seconds': float(duration), 'source_writes': len(trace.writes),
              'capture_execution': {'init_cycles': init_cycles, 'instructions': trace.footer.get('instructions'),
                                    'sid_bus_reads': trace.footer.get('sid_bus_reads', {})},
              'play_writes': sum(r['phase'] == 'play' for r in trace.writes),
              'notes_on': [sum(n['voice'] == v and n['note'] is not None for n in notes) for v in range(3)],
              'notes_off': [sum(n['voice'] == v and n['note'] is None for n in notes) for v in range(3)],
              'synthetic_boundary_note_offs': sum(n['source'] == 'capture-boundary' for n in notes),
              'boundary_padding_seconds': float(Fraction(boundary, UNITS_PER_SECOND) - duration),
              'release_tail_rows_added': (end_units - boundary) // UNITS_PER_ROW - 1,
              'song_seconds': end_units / UNITS_PER_SECOND,
              'row_seconds': float(ROW_SECONDS), 'source_time_rounding_max_seconds': max_rounding,
              'automation_points': sum(len(p) for p in automation.values()),
              'frequency_mapping_checks': frequency_checks, 'frequency_mapping_max_register_error': max_register_error,
              'controls_closer_than_measured_333us': risks,
              'issues': dict(issues), 'issue_examples': dict(examples),
              'limitations': ['Instruction timing is not a full C64 or bus-cycle capture',
                  'Native automation cannot preserve arbitrary SID write ordering or unchanged-write side effects',
                  'Same-row note events use the final event and report reductions',
                  'Captured window is an explicit development budget; no intended song ending is inferred',
                  'No source-audio fidelity comparison or listening approval is implied']}
    return Performance(patch, notes, automation, end_units, report)
