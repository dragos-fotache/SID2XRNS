# Source envelope timing — CLI 0.3.0 / SIDSynth 0.6.0

The reported Alibi percussion regression comes from the SID ADSR rate counter:
source SR/gate writes 13 CPU cycles apart can collapse onto the same native
Renoise time. A tiny ordering/phase change can move an envelope peak by roughly
33 ms. Advancing every ADSR point one unit repaired one hit and created another;
that experimental helper remains outside production conversion.

New exports default to `--envelope-timing source`. The converter models the
pinned libresidfp 1.3.0 envelope from ordered source writes and publishes complete
planned envelope timing snapshots through four native automation words per voice.
A real MIDI note binds a source epoch; subsequent snapshots require the owned
epoch and gate. Snapshots never create notes, write frequency/gate registers,
replace the SID, reset oscillator phase or reset the shared filter. Original
note rows and original sound automation are retained. Source/manual changes,
CC120, Panic, state recall and stop clear runtime bindings.

SIDSynth 0.6.0 appends 13 host-only parameters to the existing 67 IDs/indices:
`envelope.cueMode` and `voiceN.envelopeState1`–`4`. State schema 4 saves planned
metadata; it never saves live envelope/MIDI state. Old schema 1/2/3 patches
restore with cues off. The Rack layout is unchanged. See the sibling synth's
`docs/ENVELOPE_CUES.md` and `docs/STATE.md` for the binary packet contract.

Each word is an exactly representable 20-bit integer. CRC-10/ATM rejects torn
multiword updates before the core is accessed. The exporter coalesces competing
snapshots in a source burst whose events are separated by less than 16 native units
(1.25 ms), retaining
the final source state, without moving notes. Alibi merges 4976 snapshots with
a maximum span of just one unit (78.125 us). This matters because Renoise can
coalesce separate parameter streams differently at such close timestamps.
A rejected update cannot change an unowned/released voice; a later complete cue
can synchronize a real note that is still held.

## Use

```sh
./bin/sid2xrns export work/alibi-cli-window.capture.jsonl.gz \
  -o work/alibi-envelope-corrected.xrns
# Explicit backward-compatible 67-parameter/schema-3 export:
./bin/sid2xrns export work/alibi-cli-window.capture.jsonl.gz \
  --envelope-timing legacy -o work/alibi-legacy.xrns
python3 -m unittest discover -s tests -v
c++ -O2 -std=c++17 \
  -I /home/dragos/work/SIDSynth/build-clean/_deps/libresidfp-src/src \
  -I /home/dragos/work/SIDSynth/build-clean/_deps/libresidfp-build \
  tools/envelope_oracle.cpp /home/dragos/work/SIDSynth/build-clean/liblibresidfp.a \
  -o work/step4/envelope-oracle-rebuilt
python3 tools/check_envelope_model.py work/step4/envelope-oracle-rebuilt
cmake --build work/build --target SIDXRNSTimingProbe_VST3 probe_self_check --parallel 4
work/build/probe_self_check
```

Source timing requires SIDSynth 0.6.0 for playback. The standalone conversion
still needs only Python's standard library and the bundled pinned CPU subset;
no compiler, Renoise or plugin is needed to generate a song. V4 assets have a
separate `runtime-lock-v4.json`; legacy assets/lock remain immutable. The pinned
source is reproducible with `sidsynth-source-v4.patch` and `source-lock.json`;
the prior patch/lock remain available for historical evidence.

## Checks and limits

Agent automated: the Python envelope model matches 2203 randomized observable
queries across 5115269 cycles against an unmodified, cycle-clocked pinned core.
This includes overlapping envelope/exponential pipelines. The accelerated clock
also matches single-cycle stepping. Release tests cover three sample rates,
parameter-arrival invariance, real note ownership/deletion, CC120, Panic,
transport stop, schema migration/recall, all single-bit packet corruptions and
20-bit parameter precision. The actual callback guard checks allocations,
C allocation/free and pthread mutex locking with source mode enabled.

Actual Renoise, agent performed: the initial 256-frame candidate brings all 50
percussion peaks in source 59.75–65.75 s within 1.02 ms of the controlled source,
including the formerly 32.834-ms-early peak at +0.562 ms. **User listening
confirms that the three reported timing problems sound fixed.** Final validation at 48 kHz passes at both 256 and 1024 device frames: all 50
excerpt peaks remain within 1.02 ms of source; the maximum difference between
buffers is 0.667 ms. The full 239.4-s pass checks all 599 percussion peaks
within 1.27 ms, zero >10-ms jumps, zero torn packets and all 4864 original MIDI
note events (maximum native timing error 0.015625 ms). Buffer audio is not
sample-identical; native scheduling and oscillator/noise phase remain limits.

The installed product also plays the 67-s excerpt capture with all 80 effective
parameters, aliases/channels, unclipped equal stereo and silence around
transport verified. Save/reopen/playback passes. The original schema-3 example
plays with its 67 values, cue mode off and all cue words zero. A real-host
synthetic note-deletion case leaves voice 3 unowned/gated off while its source
cue automation continues. All private hosts close normally. Compact checks,
logs, hashes and preservation records are in `evidence/step4/summary.json`.

The diagnostic now checks sample-identical audio and monotonic ENV3 timestamps
at both 128- and 1024-sample callbacks. An earlier observation bug reused the
first 256-sample chunk's timestamp for subsequent chunks inside a large engine
render. That distorted old large-buffer ENV3 peak reports; it did not change
rendered audio, MIDI or physical-write timestamps. Earlier step-3 256-frame
percussion evidence remains valid. Superseded preliminary reports stay in work.

A peak is not an audible onset. This correction targets envelope timing, not
identical audio from different SID engines. Native automation quantization,
frequency-zero reductions, source-note collisions and sub-resolution controls
remain reported. Initialization uses the documented 48000-sample canonical
silent warm-up followed by final init registers, rather than complete C64
power-on/init history. Effective resampler clock quantization remains explicit.
There is no general cycle-exact C64 fidelity claim or automatic ending policy.

## Exact isolated host commands

Use fresh profile/capture names; the following create new checks. The diagnostic
song records internally and mutes its external outputs. The product song plays
through the installed plugin. The Lua helper uses `start_at(SongPos(1,1))` so a
repeat begins at source zero, even after playback selected a later pattern.

```sh
./bin/sid2xrns export work/alibi-cli-window.capture.jsonl.gz \
  --diagnostic -o work/new-envelope-probe.xrns
python3 probe/host.py launch \
  --config /home/dragos/work/SIDSynth/work/midi-import/config/Renoise/V3.5.4/Config.xml \
  --remcp /home/dragos/work/SIDSynth/work/midi-import/config/Renoise/V3.5.4/Scripts/Tools/com.renoise.ReMCP.xrnx \
  --label new-envelope-full --quantum 1024 --capture-seconds 260 \
  --song new-envelope-probe.xrns
python3 probe/host.py capture --name new-envelope-full --seconds 241
python3 tools/check_envelope_capture.py work/new-envelope-full.json \
  --source work/alibi-cli-window.capture.jsonl.gz -o work/new-envelope-check.json
python3 probe/close_host.py
```

For the 256-frame excerpt, use another fresh label, `--quantum 256`, capacity
120 and capture 67 seconds. Product launch uses `--plugin-dir work/product-plugins`
(the controlled symlink to the installed bundle), the ordinary corrected song
and `python3 probe/product_check.py --name new-product --seconds 67`.
Run the private-host commands with desktop audio/display/loopback access.
The task's actual labels/results and final installed recording clip are retained
in `evidence/step4/summary.json` and `work/step4/installed-clip.json`.
