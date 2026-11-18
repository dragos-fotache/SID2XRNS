#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fidelity.rate_guard import guard
from sid2xrns.trace import read_trace
from sid2xrns.interpret import interpret
from sid2xrns.xrns import write_song

trace = read_trace(sys.argv[1]); performance = interpret(trace)
result = guard(performance, trace)
output = Path(sys.argv[2])
if output.exists() or output.with_suffix('.json').exists(): raise SystemExit('Choose fresh candidate paths')
write_song(performance, output, diagnostic=True)
output.with_suffix('.json').write_text(json.dumps(result, indent=2) + '\n')
print('Moved', len(result['edits']), 'ADSR points; skipped', len(result['skipped']), '; note rows unchanged')
