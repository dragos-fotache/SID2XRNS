# Step 2 implementation checkpoint

17 November 2026. The separate CLI pipeline is implemented and exercised. Its
commands, exact profile, trace schema, reduction policies and runtime pins are
documented in [CLI.md](CLI.md).

## Implemented behavior

`inspect` parses metadata without execution. `capture` runs the selected one-based
subsong under the bounded direct-call profile and publishes a complete ordered
trace atomically. `export` validates that trace, interprets actual gate events
and relative sound changes, then writes native XRNS and a report. `convert`
composes those stages and keeps the trace before interpretation starts.

The runtime is standard-library Python plus five pinned, namespaced MIT modules.
There is no host API dependency in conversion and no network lookup. Both load
address encodings, explicit clock/model selection, subsongs, single-SID mirrors,
bounded routine execution, input/output protection and deterministic outputs
are implemented. Runtime asset verification pins the CPU files, template and
all 67 parameter bindings. The synth source, schema, IDs and installed bundle
were not changed.

## Automated and actual-host results

**Seventeen automated tests pass.** New tests exercise one-based subsongs,
embedded/explicit load addresses, same-value and reversing writes at known
instruction cycles, SID mirrors versus RAM banking, unsupported execution,
nontermination bounds, trace truncation/tampering, release pitch, channel
ownership, pattern carry values, preservation of repeated sections, deterministic
XRNS, CWD-independent execution, output protection, strict rejection and atomic
failure. The five existing step-1 tests still pass.

**Actual Renoise, automated by the agent:** the original synthetic program was
captured for 520 calls and exported through the CLI. In the real-processor probe,
all three MIDI channels receive their planned notes, maximum note error is
0.015625 ms, physical-write replay matches 314 subsequent callback snapshots,
voice 1 retunes with gate off while voice 2 remains held, and a held voice crosses
the 5.12-second pattern boundary. The included example's XRNS bytes match this
host-tested product-target export. The example retains all 520 calls, including
its natural repeated sections. It has no semantic reductions and reports four
sub-333-us control intervals.

**Alibi execution check:** an explicit **12000-call** development window captures
**239.403683 seconds**, retains **287977 ordered writes**, and matches all
**12000** preserved call-end register snapshots with **zero mismatches**. The
preserved baseline uses the same CPU family; this is a regression/continuity
check, not an independent C64 or SID-audio oracle. No source loop or intended
ending was inferred. The song has **47 patterns** and 1250/583/599 note-ons.

The Alibi report exposes **15 pre-ownership frequency changes**, **2433 zero-
frequency intervals** that the MIDI tuning path cannot represent literally,
and **2308 control intervals below the measured 333-us host granularity**.
Maximum reconstructed frequency-word difference in the intermediate mapping
check is eight register units. These are explicit limits; the export is an
editable approximation and is not claimed to improve or match the original
audio. The raw writes permit later interpretation changes without recapturing.

**Actual installed SIDSynth:** a 1200-call Alibi export opens, plays, saves,
reopens and plays again in private Renoise profiles. All 67 effective values,
one instance/two aliases, independent channels, matching stereo, nonzero
unclipped audio and silence before play/after stop pass. Recorded peak is
0.049103 of full scale. The installed module hash remains
`fbc5cd5947cfa960ae3b95e31c73c11337124448220b597aca5fe597f27e5f72`.
Only each selected private PID's outputs were recorded; its speaker links were
restored after stop. The full 47-pattern window was also opened in Renoise:
all 47 sequence entries and pattern lengths resolve, and short playback passes.
No full 239-second playback/listening pass is claimed.

No subjective listening, independent source rendering or source-versus-export
audio metric is claimed. That is step 3. The duration/end-boundary policy remains
open. There is no HVSC integration or automatic loop trimming.

## Evidence and reproduction

The original synthetic SID and complete native example are in
[fixtures](../fixtures/cli-performance.sid) and
[examples](../examples/cli-performance.xrns). Compact host and regression
results are retained in [step-2 evidence](../evidence/step2/summary.json).
Full ordered Alibi capture, generated 47-pattern song/report, short recordings,
host transcripts, logs and close records remain in ignored `work/`.
All Alibi originals under `/home/dragos/work/Alibi-Renoise/` remain read-only.

```sh
python3 -m unittest discover -s tests -v
./bin/sid2xrns convert fixtures/cli-performance.sid --play-calls 520 -o work/example.xrns
./bin/sid2xrns convert /home/dragos/work/Alibi-Renoise/Alibi.sid \
  --play-calls 12000 -o work/alibi-window.xrns
```

The next task is independent source-audio/write-trace comparison with actual
exported-song playback, including worst passages, fault injection and listening.
