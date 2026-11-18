# SID2XRNS

An offline Linux CLI that captures a bounded PSID playback window and exports an
editable Renoise `.xrns` song using one SIDSynth instance and two aliases.
Notes own pitch and gate; native automation carries sound controls and relative
pitch through releases. CLI **0.4.0** carries note-owned source envelope timing
and adds rows for SID release tails after the capture cutoff. All 80 schema-4
parameters are initialized. Playback requires **SIDSynth 0.6.0**.

```sh
./bin/sid2xrns inspect /path/to/tune.sid
./bin/sid2xrns convert /path/to/tune.sid --subsong 1 --play-calls 1200
./bin/sid2xrns convert /path/to/tune.sid --subsong 1 --hvsc-db /path/to/Songlengths.md5 -o /path/to/tune.xrns
```

Conversion needs Python and the included pinned CPU subset. It does not require
Renoise, SIDSynth or a compiler to run. SIDSynth is required for playback. The
ordered capture and a report are retained beside every converted song.
Without `-o`, `convert` writes `tune.xrns` in the current directory for an
input named `tune.sid`. Separate `capture` and `export` commands can reuse the
same trace.

The initial scope is single-SID, directly callable RAM PSID/VBI players. CLI
0.2.1 also handles packed initialization and SID write-only bus reads used by
Turrican 3; see [the regression](docs/TURRICAN.md). ROM, OSC3/ENV3/paddle reads,
non-SID I/O, CIA timing, interrupt players and other unsupported behavior fail
explicitly. Set the capture window in play calls or supply a local
`Songlengths.md5` to use the selected subsong's HVSC duration. Repeats inside
that window are preserved. Use bare `--hvsc-db` if `Songlengths.md5` is in
the directory you run the command from.
[Download the standalone HVSC database](https://hvsc.de/download/C64Music/DOCUMENTS/Songlengths.md5).

Read [CLI usage and limits](docs/CLI.md), [current status](docs/STATUS.md) and
[the plan](docs/PLAN.md). An [original SID/XRNS example](examples/README.md) is
included. The [native timing experiment](docs/TIMING.md) documents actual Renoise
timing limits. Tests confirm real note editing/ownership and release pitch;
the [independent comparison milestone](docs/COMPARISON.md) now provides a pinned
VICE reference, actual full-window Alibi recordings, fault checks and listening
clips. It reproduces off percussion: a reported envelope peak is about 33 ms
early in the old export. The [robust envelope correction](docs/ENVELOPE_TIMING.md)
now supplies source-derived counter/pipeline cues; the user confirms the reported
passage sounds fixed. `--envelope-timing legacy` retains schema-3 exports.

Original code is AGPL-3.0-only. The CLI vendors a MIT-licensed ChiptuneSAK subset
at a pinned commit. Dependency licenses and hashes are in
[third-party notices](third_party/NOTICES.md) and
[the runtime lock](docs/runtime-lock.json). JUCE is used by the optional
diagnostic probe; pinned libresidfp also serves its controlled-core comparison
renderer. The converter includes a GPL-licensed Python port of its pinned
envelope semantics; no libresidfp binary is a converter runtime dependency.
The optional `bin/sid2xrns-compare` analysis tool additionally uses the pinned
installed VICE/NumPy/SciPy/Matplotlib environment in
[reference-lock.json](docs/reference-lock.json); these analysis packages are separate from converter runtime.
