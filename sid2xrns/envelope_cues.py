# SPDX-License-Identifier: AGPL-3.0-only
"""Native, note-owned envelope phase cues; never frequency or gate replay."""
from collections import defaultdict
from fractions import Fraction
from .envelope import Envelope, warm_cycles
from .errors import ConversionError

CUE_FIELDS = tuple(f'envelopeState{i}' for i in range(1, 5))


def add_envelope_cues(performance, trace):
    hz = trace.header['profile']['target_clock_hz']
    source_hz = trace.header['profile']['clock_hz']; origin = trace.header['init_cycles']
    envelopes = [Envelope() for _ in range(3)]
    for env in envelopes: env.clock(warm_cycles(hz))
    for reg, value in enumerate(trace.header['initial_registers']):
        if reg < 21: envelopes[reg // 7].write(reg % 7, value)
    groups = defaultdict(list)
    for row in trace.writes:
        if row['phase'] == 'play':
            unit = round(Fraction((row['cycle'] - origin) * 12800, source_hz))
            groups[unit].append(row)
    notes = defaultdict(list)
    for note in performance.notes:
        if note['source'] != 'capture-boundary': notes[note['units']].append(note)
    epochs = [0, 0, 0]; serials = [0, 0, 0]; count = 0; skipped = []
    performance.initial['envelope.cueMode'] = 1
    for v, env in enumerate(envelopes):
        for name, value in zip(CUE_FIELDS, env.words(0, 0, 0)):
            key = f'voice{v + 1}.{name}'
            performance.initial[key] = value; performance.automation[key] = {0: value}
    now = 0
    def clock(to):
        nonlocal now
        if to < now: raise ConversionError('envelope-clock-order', 'Envelope timeline went backwards')
        for env in envelopes: env.clock(to - now)
        now = to
    for unit in sorted(set(groups) | set(notes)):
        touched = set()
        for row in groups[unit]:
            cycle = round(Fraction((row['cycle'] - origin) * hz, source_hz))
            clock(cycle)
            reg, value = row['register'], row['value']
            if reg < 21:
                v, offset = divmod(reg, 7); env = envelopes[v]
                if offset in (5, 6) or (offset == 4 and bool(value & 1) != env.gate): touched.add(v)
                env.write(offset, value)
        clock(max(now, round(Fraction(unit * hz, 12800))))
        triggers = {}
        for note in notes[unit]:
            v = note['voice']; touched.add(v)
            if note['note'] is not None:
                epochs[v] += 1
                if epochs[v] >= 1 << 16:
                    raise ConversionError('envelope-epoch-budget', 'Envelope cue note epoch exceeds its 16-bit range')
                triggers[v] = 1
            else: triggers[v] = 2
        for v in sorted(touched):
            trigger = triggers.get(v, 0)
            if trigger and envelopes[v].gate != (trigger == 1):
                skipped.append({'voice': v, 'units': unit, 'reason': 'source gate differs from retained note event'})
                continue
            serials[v] += 1; count += 1
            for name, value in zip(CUE_FIELDS, envelopes[v].words(trigger, epochs[v], serials[v])):
                key = f'voice{v + 1}.{name}'
                performance.automation[key][unit] = value
                if unit == 0: performance.initial[key] = value
    # Publish one complete post-event snapshot for a tight source burst. Renoise
    # can coalesce neighboring parameter streams differently below its measured
    # native callback interval, producing a torn multiword packet. Keeping the
    # final state of each burst separated by <1.25 ms avoids competing updates;
    # the CRC independently rejects a partial update. Notes are never moved.
    merged = 0; maximum_span = 0
    for v in range(3):
        keys = [f'voice{v + 1}.{name}' for name in CUE_FIELDS]
        units = sorted(performance.automation[keys[0]])
        clusters = []; cluster = []
        for unit in units:
            if cluster and unit - cluster[-1] >= 16:
                clusters.append(cluster); cluster = []
            cluster.append(unit)
        if cluster: clusters.append(cluster)
        for cluster in clusters:
            removed = [u for u in cluster[:-1] if u != 0]
            if removed:
                maximum_span = max(maximum_span, cluster[-1] - cluster[0])
                for key in keys:
                    for unit in removed: del performance.automation[key][unit]
                merged += len(removed)
    performance.report['parameter_schema'] = 4
    performance.report['required_sidsynth_version'] = '0.6.0'
    performance.report['envelope_cues'] = {
        'format': 1, 'cues': count, 'skipped': skipped,
        'coalesced_cues': merged, 'maximum_coalesced_span_units': maximum_span,
        'packet_integrity': 'CRC-10/ATM; partial packets are ignored',
        'model': 'Pinned libresidfp 1.3.0 envelope, exact LFSR/pipeline event skipping',
        'initialization': '48000-sample canonical silent warm-up, then captured final init registers',
        'notes_changed': False, 'gate_or_frequency_replay': False, 'gate_only_as_ownership_check': True,
        'ownership': 'MIDI gate events bind source epochs; control/release cues require that owned epoch',
        'precision': 'Source envelope state at ordered native-unit boundary; host quantization remains, without inherited ADSR rate-counter phase drift'}
    performance.report['automation_points'] = sum(len(x) for x in performance.automation.values())
    return performance
