# SPDX-License-Identifier: AGPL-3.0-only
"""Experimental native quantization guard; tested outside the converter first."""
from fractions import Fraction


def guard(performance, trace):
    hz = trace.header['profile']['clock_hz']; origin = trace.header['init_cycles']
    registers = list(trace.header['initial_registers']); changed = {}
    notes = {(n['voice'], n['units']) for n in performance.notes if n['note'] is not None}
    edits = []; skipped = []
    for row in trace.writes:
        if row['phase'] != 'play': continue
        reg, value, cycle = row['register'], row['value'], row['cycle']
        old = registers[reg]; registers[reg] = value
        voice, offset = divmod(reg, 7)
        if reg < 21 and offset in (5, 6) and value != old:
            changed[(voice, offset)] = (cycle, value, old)
        if reg >= 21 or offset != 4 or not value & 1 or old & 1: continue
        unit = round(Fraction((cycle - origin) * 12800, hz))
        if (voice, unit) not in notes: continue
        for rate_offset, names in ((5, ('attack', 'decay')), (6, ('sustain', 'release'))):
            recent = changed.get((voice, rate_offset))
            if not recent: continue
            rate_cycle, rate_value, old_value = recent
            if not 0 < cycle - rate_cycle <= hz / 12800: continue
            rate_unit = round(Fraction((rate_cycle - origin) * 12800, hz))
            if rate_unit != unit: continue
            for shift, name in zip((4, 0), names):
                desired, previous = (rate_value >> shift) & 15, (old_value >> shift) & 15
                if desired == previous: continue
                key = f'voice{voice + 1}.{name}'; points = performance.automation[key]
                if unit <= 1 or points.get(unit) != desired or (unit - 1 in points and points[unit - 1] != desired):
                    skipped.append({'id': key, 'units': unit, 'reason': 'initial boundary, collision or ambiguous final value'})
                    continue
                del points[unit]; points[unit - 1] = desired
                edits.append({'id': key, 'from_units': unit, 'to_units': unit - 1,
                              'source_lead_cycles': cycle - rate_cycle,
                              'source_seconds': (rate_cycle - origin) / hz})
    return {'policy': 'Experimental one-unit lead only when a changed ADSR field precedes a retained gate-on but rounds to its same native unit',
            'unit_seconds': 1 / 12800, 'notes_changed': False, 'edits': edits, 'skipped': skipped}
