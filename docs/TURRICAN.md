# Turrican 3 capture support — CLI 0.2.1

Source supplied by the user: `/home/dragos/Downloads/Turrican_3.sid`, PSID v2,
24 subsongs, default **2**, PAL, either SID model. SHA-256:
`ca3f477225859e79de059b41f3ba9fdb5389f791daa6a78176eb6f487522ca4d`.
The SID and generated music are not bundled in the repository's retained
evidence. Local exports and raw traces are under ignored `work/turrican3/`.

## Changes

The default subsong unpacks its player during initialization. It needs
**279560 instructions / 933057 cycles**, exceeding the old 250000-instruction
guard. Initialization now permits **500000 instructions**, retaining its
1000000-cycle bound. Play calls keep their separate 250000-instruction and
one-VBI cycle bounds. Nonterminating routines still fail, without published
partial captures. Budget errors now include phase, call index, PC and counts.

The unpacked routine at `$E95C` executes `BIT $D418`. SID write-only readback
returns the chip's shared, decaying data-bus latch, rather than the writable
register's stored value. The only earlier SID write is `$1F` to `$D418` near
startup; the latch has expired before this read for both chip models.

`sid2xrns/sidbus.py` implements the lifetimes and read-discharge policy from
**libresidfp 1.3.0**, commit `5393471a02a505ff43aa710148b2d35289b72c31`:
[SID.cpp](https://github.com/libsidplayfp/libresidfp/blob/5393471a02a505ff43aa710148b2d35289b72c31/src/SID.cpp)
and [SID.h](https://github.com/libsidplayfp/libresidfp/blob/5393471a02a505ff43aa710148b2d35289b72c31/src/SID.h).
The 6581 bus lifetime is `$01D00` cycles; the 8580 lifetime is `$A2000`.
Reads halve the residual lifetime. All writable/unmapped SID addresses and
mirrors share one latch; banked-out I/O remains RAM. The clock is absolute
across init, play and idle gaps, at the existing instruction-end precision.
Paddle, OSC3 and ENV3 reads and unrelated I/O remain explicit failures.

No vendored CPU logic changed and no new runtime dependency was added. The
CPU remains the pinned ChiptuneSAK subset with thin C64 banking. This adds the
needed SID bus behavior, not a full C64 or sound-chip execution environment.
Source/license details are in [the notices](../third_party/NOTICES.md).

New captures identify execution profile `psid-direct-vbi-v2` and report SID bus
read counts in the footer and conversion report. Existing schema-1/v1 captures
still export; ordered write records and the saved SIDSynth patch schema stay
unchanged. Ambiguous headers still require an explicit chip-model choice.

## Automated offline checks

- **24 tests pass**, including a generated long init, bounded infinite init,
  shared read latch/mirrors, banked-out RAM, model decay through idle VBI gaps,
  read discharge, unsupported hardware and legacy export compatibility.
- `tools/check_turrican.py` exports **all 24 subsongs with both models** for
  1200 calls each: **48 passing cases**. Every capture passes ordered-write
  replay/snapshot validation and produces a native song with one plugin, two
  aliases, channels 1–3 and 67 initialized parameters. The two models' captured
  writes agree for each subsong. Max init is 933057 cycles; all play routines
  finish inside their VBI periods.
- Default subsong 2 / 8580 also exports **12000 calls / 239.403683 seconds** into
  **47 patterns**. This is an explicitly bounded window; no ending or loop
  boundary is inferred. The report retains representation and host timing risks.
- A separate ten-read check against the existing compiled pinned libresidfp
  core agrees on both models' shared latch, unmapped reads, decay and refresh.
  The reference runner is `tools/check_sidbus_reference.cpp`. This validates
  the bus policy only; it is not an independent source-audio fidelity test.
- Alibi regression: all **28777 writes / 1200 snapshots** match the previous
  capture prefix. The old v1 12000-call capture re-exports byte-identically to
  its previously generated XRNS.

Commands from `/home/dragos/work/SID2XRNS` (choose fresh destinations):

```sh
python3 -m unittest discover -s tests -v
python3 tools/check_turrican.py /home/dragos/Downloads/Turrican_3.sid \
  --output work/turrican3/matrix --play-calls 1200
./bin/sid2xrns convert /home/dragos/Downloads/Turrican_3.sid \
  --model 8580 --play-calls 12000 \
  -o work/turrican3/Turrican_3-subsong-02-window.xrns
```

Other subsongs use `--subsong 1` through `--subsong 24`; omit it to select 2.
Use `--model 6581` for the other permitted model. For conversion with an HVSC
subsong duration, pass `--hvsc-db` in place of `--play-calls`.

Optional reference build, using existing local SIDSynth build products:

```sh
c++ -std=c++17 -O2 \
  -I /home/dragos/work/SIDSynth/build-clean/_deps/libresidfp-build/realtime-src \
  -I /home/dragos/work/SIDSynth/build-clean/_deps/libresidfp-build \
  tools/check_sidbus_reference.cpp \
  /home/dragos/work/SIDSynth/build-clean/liblibresidfp.a \
  -o work/turrican3/sidbus-reference
work/turrican3/sidbus-reference
```

Retained compact results are in `evidence/turrican3/`. Full matrix captures,
songs, logs, source-audio-independent checks and recordings remain in `work/`.

## Actual Renoise checks

Renoise **3.5.4 Demo**, automated by the agent in private profile
`work/profile-turrican3`, PID **70871**, using the already installed SIDSynth
0.5.1. Both the 1200-call song and the 47-pattern window load, with all sequence
entries resolving. Short playback checks verify all 67 effective parameters,
one instance/two aliases on channels 1–3, nonzero equal stereo audio without
clipping, silence before play and after stop, and restoration of only this
private PID's output links. Peak on the initial checks is **0.06414795**.
Saved-song reopen/playback also passes. Time-zero automation restores 16 values
that differ from the patch saved after later playback. The private host was
closed normally; 21 preservation hashes confirm the input, Alibi reference,
SIDSynth source/module and normal Renoise preferences remain unchanged.

Host commands use the existing guarded runner. Songs are copied/generated as
`work/turrican3-host.xrns` and `work/turrican3-window-host.xrns`, because that
runner restricts host input to its own scratch directory.

```sh
python3 probe/host.py launch \
  --config /home/dragos/work/SIDSynth/work/midi-import/config/Renoise/V3.5.4/Config.xml \
  --remcp /home/dragos/work/SIDSynth/work/midi-import/config/Renoise/V3.5.4/Scripts/Tools/com.renoise.ReMCP.xrnx \
  --label turrican3 --quantum 1024 --song turrican3-host.xrns \
  --plugin-dir /home/dragos/work/SID2XRNS/work/product-plugins
python3 probe/product_check.py --name turrican3-product
python3 probe/host.py call save --name turrican3-recall.xrns
python3 probe/host.py call load --name turrican3-window-host.xrns
python3 probe/product_check.py --name turrican3-window-product
python3 probe/host.py call load --name turrican3-recall.xrns
python3 probe/product_check.py --name turrican3-recall-product
python3 probe/close_host.py
```

Each deferred load must complete before running the next playback check. Host
profiles/labels and output filenames must be fresh. The retained transcript and
compact checks identify the actual files/PID; no normal user host is controlled.

No full-window host playback, listening approval, source-audio comparison or
cycle-exact fidelity is claimed. The default window still reports pre-note
frequency ownership and controls closer than the measured host granularity.
These existing exporter limits remain visible. Step 3 remains independent
source/audio comparison, including listening; automatic ending selection and
loop trimming remain deferred.
