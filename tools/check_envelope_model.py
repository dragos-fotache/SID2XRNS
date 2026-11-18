#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Compare the accelerated model to a cycle-clocked unmodified pinned core."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sid2xrns.envelope import Envelope

p=argparse.ArgumentParser(description=__doc__);p.add_argument('oracle',type=Path);a=p.parse_args()
rng=random.Random(77184); models=[Envelope() for _ in range(3)]; now=0; stimulus=[];expected=[]
for i in range(2203):
    cycles=rng.choice((0,1,2,3,4,7,rng.randrange(32768)))
    for m in models:m.clock(cycles)
    now+=cycles
    reg=rng.randrange(3)*7+rng.choice((4,5,6));value=rng.randrange(256)
    models[reg//7].write(reg%7,value);stimulus.append(f'{now} {reg} {value}\n')
    stimulus.append(f'{now} -1 0\n');expected.append([now]+[n for m in models for n in (m.env3,m.counter)])
data=''.join(stimulus).encode();r=subprocess.run([str(a.oracle.resolve())],input=data,capture_output=True,check=True)
actual=[list(map(int,line.split())) for line in r.stdout.splitlines()]
if actual!=expected:
    for i,(x,y) in enumerate(zip(actual,expected)):
        if x!=y:raise SystemExit(f'Oracle mismatch at query {i}: {x} != {y}')
    raise SystemExit('Oracle output count differs')
print(json.dumps({'queries':len(expected),'cycles':now,'mismatches':0,'stimulus_sha256':hashlib.sha256(data).hexdigest(),'oracle_sha256':hashlib.sha256(a.oracle.read_bytes()).hexdigest()},indent=2))
