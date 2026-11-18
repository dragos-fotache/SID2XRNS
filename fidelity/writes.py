# SPDX-License-Identifier: AGPL-3.0-only
"""Compare independent source execution per invocation, retaining real timing."""
import bisect
from collections import Counter
import json
from pathlib import Path
import numpy as np
from sid2xrns.trace import read_trace


def compare_capture(reference, capture, output):
    if Path(output).exists():
        raise ValueError(f'Refusing to overwrite {output}; choose a fresh output path')
    ref = json.loads(Path(reference).read_text()); trace = read_trace(capture)
    if ref['source_sha256'] != trace.header['source']['sha256']:
        raise ValueError('Different SID sources')
    for key in ('clock', 'model', 'subsong'):
        if ref['profile'][key] != trace.header['profile'][key]:
            raise ValueError(f'Different {key} configuration')
    entries = ref['play_entries']; count = min(ref['play_calls'], len(trace.calls))
    a = [[] for _ in range(count)]; b = [[] for _ in range(count)]
    for row in ref['writes']:
        call = bisect.bisect_right(entries, row['cycle']) - 1
        if 0 <= call < count: a[call].append(row)
    for row in trace.writes:
        if row['phase'] == 'play' and row['call'] < count: b[row['call']].append(row)
    faults = []; mismatched = 0; errors = []; by_register = Counter()
    for call, (left, right) in enumerate(zip(a, b)):
        x = [(r['register'], r['value']) for r in left]; y = [(r['register'], r['value']) for r in right]
        if x != y:
            mismatched += 1
            if len(faults) < 12:
                faults.append({'call': call, 'reference_count': len(x), 'capture_count': len(y),
                               'first_reference_writes': x[:32], 'first_capture_writes': y[:32]})
            continue
        for x, y in zip(left, right):
            delta = (y['cycle'] - trace.header['init_cycles']) - (x['cycle'] - entries[0])
            errors.append(delta / ref['profile']['clock_hz'])
            by_register[x['register']] += 1
    drift = [(entries[i] - entries[0] - i * ref['profile']['cycles_per_call']) / ref['profile']['clock_hz']
             for i in range(count)]
    result = {'schema': 1, 'source_sha256': ref['source_sha256'], 'calls_compared': count,
              'reference_calls': ref['play_calls'], 'capture_calls': len(trace.calls),
              'mismatched_calls': mismatched, 'mismatch_examples': faults,
              'exact_ordered_value_matches': sum(len(x) for x, y in zip(a, b) if
                  [(r['register'], r['value']) for r in x] == [(r['register'], r['value']) for r in y]),
              'matched_writes_per_register': dict(sorted(by_register.items())),
              'write_timing_capture_minus_reference_ms': {'min': min(errors, default=0) * 1000,
                 'max': max(errors, default=0) * 1000, 'median': float(np.median(errors)) * 1000 if errors else None},
              'independent_driver_vs_fixed_call_ms': {'min': min(drift, default=0) * 1000,
                                                       'max': max(drift, default=0) * 1000},
              'independence': ref['reference']['independence'],
              'scope': 'Play-phase writes only; VICE driver/init writes retained in reference. No timing warp or init-equivalence claim.'}
    with Path(output).open('x') as stream: stream.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    return result
