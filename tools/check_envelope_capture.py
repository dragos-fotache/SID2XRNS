#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Check live cue integrity, real MIDI gate ownership and ENV timestamps."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fidelity.target import first_playback
from sid2xrns.envelope import seal_words
from sid2xrns.interpret import interpret
from sid2xrns.trace import read_trace

p=argparse.ArgumentParser(description=__doc__);p.add_argument('metadata',type=Path);p.add_argument('--source',type=Path);p.add_argument('--deleted-voice',type=int);p.add_argument('-o',type=Path,required=True);a=p.parse_args()
m=json.loads(a.metadata.read_text());t=json.loads(Path(m['trace']).read_text());assert not t['overflow'];assert t['pid']==m['process']['pid']
first,end=first_playback(t['blocks']);blocks=t['blocks'][first:end];origin=blocks[0]['sample'];stop=blocks[-1]['sample']+blocks[-1]['size'];invalid=0
for b in blocks:
    assert b['parameters'][67]==1
    for v in range(3):
        words=b['parameters'][68+4*v:72+4*v];assert all(x==int(x) and 0<=x<=1048575 for x in words)
        payload=[int(x)&(0xffff if i==3 else 0x3ffff) for i,x in enumerate(words)]
        invalid+=list(seal_words(payload))!=words
        assert (b['notes'][v]>=0)==bool(b['registers'][7*v+4]&1)
        if a.deleted_voice==v+1:assert b['notes'][v]==-1 and not b['registers'][7*v+4]&1
observed=[e for e in t['events'] if e[2]==4 and origin<e[0]<=stop]
assert all(y[0]>x[0] and y[4]>x[4] for x,y in zip(observed,observed[1:]))
notes=[e for e in t['events'] if e[2]==1 and origin<=e[0]<stop and e[3]&0xf0 in (0x80,0x90)]
error=None
if a.source:
    expected=interpret(read_trace(a.source)).notes
    actual=[(e[3]&15,e[4] if e[3]&0xf0==0x90 and e[5] else None,(e[0]-origin)/t['sample_rate']) for e in notes]
    assert len(actual)==len(expected),(len(actual),len(expected))
    # MIDI events sharing a callback need not have source-list voice order.
    actual.sort(key=lambda n:(n[0],n[2]));expected.sort(key=lambda n:(n['voice'],n['units']))
    for x,y in zip(actual,expected):assert x[:2]==(y['voice'],y['note']),(x,y)
    error=max(abs(x[2]-y['units']/12800) for x,y in zip(actual,expected))
    assert error<=1/t['sample_rate']+1e-8,error
result={'pid':t['pid'],'sample_rate':t['sample_rate'],'requested_quantum':m['process']['requested_quantum'],'playing_blocks':len(blocks),'first_pass_seconds':(stop-origin)/t['sample_rate'],'overflow':t['overflow'],'torn_packets':invalid,'gate_ownership_mismatches':0,'monotonic_env3_observations':len(observed),'midi_note_events':len(notes),'max_native_note_error_seconds':error,'deleted_voice':a.deleted_voice,'deleted_voice_stayed_unowned':True if a.deleted_voice else None}
a.o.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
