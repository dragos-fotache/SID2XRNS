> Current CLI: **0.4.1**. New exports default to source envelope timing and
> require **SIDSynth 0.6.0** (80 parameters, schema 4). Use
> `--envelope-timing legacy` for 67-parameter/schema-3 output. Both modes
> include the release-tail padding described below.
> See [ENVELOPE_TIMING.md](ENVELOPE_TIMING.md) for ownership, integrity checks
> and measured limits. Earlier 0.2.x examples/checkpoints below remain historical.

# SID2XRNS CLI

The Linux CLI captures a bounded PSID playback window and exports an editable
native Renoise song. The x86-64 release executable includes its runtime.
Running from source uses Python's standard library and the included pinned CPU
subset. A compatible SIDSynth is required to play the XRNS in Renoise.
Initial 0.2.x validation used the local release-pitch-corrected 0.5.1 module, SHA-256
`fbc5cd5947cfa960ae3b95e31c73c11337124448220b597aca5fe597f27e5f72`.

Run `./sid2xrns` from the extracted release. For a source checkout, run
`./bin/sid2xrns` or `python3 -m sid2xrns`. Conversion runs offline.
`--version` reports the CLI version. The commands below use the source
checkout.

## Commands

```sh
./bin/sid2xrns inspect /path/to/tune.sid
./bin/sid2xrns convert /path/to/tune.sid

# The same pipeline can be run in separate stages:
./bin/sid2xrns capture /path/to/tune.sid --subsong 1 --play-calls 1200 -o /path/to/tune.capture.jsonl.gz
./bin/sid2xrns export /path/to/tune.capture.jsonl.gz -o /path/to/tune.xrns
```

`convert` writes `tune.xrns` in the current directory when given
`/path/to/tune.sid` without `-o`. Use `-o` to choose a different destination.
Only the XRNS is written by default. Use `--trace PATH` to save the capture
or `--report PATH` to save the JSON conversion report. The standalone `export`
command saves a report beside its XRNS by default.
Parent directories must already exist. Existing outputs are protected unless
`--force` is supplied. Input and output paths must be distinct. A completed
trace saved with `--trace` is available for re-export if interpretation fails.
Errors are JSON on stderr with exit code 2. Successful commands print a JSON
summary to stdout with exit code 0.

`convert` uses `Songlengths.md5` in the shell's current directory (`pwd`) if you
omit the capture window option. `--hvsc-db PATH` selects another database,
and bare `--hvsc-db` selects `Songlengths.md5` in the current directory.
Use `--play-calls N` to set the window manually. `capture` requires a window
option. `inspect --hvsc-db` lists the tune's subsong lengths in milliseconds
without running it.

```sh
./bin/sid2xrns inspect /path/to/tune.sid --hvsc-db
./bin/sid2xrns convert /path/to/tune.sid --subsong 2 \
  --hvsc-db /path/to/Songlengths.md5 \
  --trace tune.capture.jsonl.gz --report tune.report.json
```

Lookup uses the MD5 of the complete SID file, so renaming a tune preserves the
match and changing its contents can invalidate it. For a tune or subsong missing
from the database, use `--play-calls`. The converter rounds a listed duration
up to a whole VBI play call at the execution clock. All repeats inside the
resulting window are kept. The modern database can be used directly from
an HVSC collection or downloaded separately. The lookup runs offline.
[Songlengths.md5](https://hvsc.de/download/C64Music/DOCUMENTS/Songlengths.md5) ·
[HVSC format notes](https://hvsc.de/download/C64Music/DOCUMENTS/Songlengths.faq)

At the end of the window, held target notes receive explicit synthetic OFFs at
the next row boundary. Export extends the XRNS in 20 ms rows for the longest
estimated SID release, including a release that began during capture. The
estimate uses the exported release rates and SID clock, allows for a full
envelope and a missed SID rate-counter match, and includes a row of margin.
The actual envelope may finish earlier. The tail plays with the final exported
settings and normal Renoise transport behavior.

The report gives the cutoff rounding in `boundary_padding_seconds`, the
number of rows beyond the original final row in `release_tail_rows_added`, and
the full XRNS duration in `song_seconds`. `capture_seconds` measures the SID
capture alone. For database-backed captures, both the trace header and the
report retain `hvsc.duration_ms` and `hvsc.sid_md5`. Exporting the saved trace
uses its recorded window.

`--subsong` is one-based and defaults to the file's selected song. Unknown or
ambiguous header clock/model require explicit `--clock pal|ntsc` and
`--model 6581|8580`. These options can also explicitly override the hints.
`--gain-db` sets the saved SIDSynth Output gain. The default is 0 dB.
The `--strict` option rejects reported semantic reductions and control intervals
below the measured 333-us host granularity. On rejection, the error lists the
reductions and any requested trace or report paths. Even strict mode does not
establish cycle-exact audio fidelity.

## Initial execution scope

Supported input is PSID versions 1–4, exactly one SID, RAM init and nonzero RAM
play entry points, a selected VBI-timed subsong, and routines returning with RTS
and a balanced stack. The payload must fit RAM above the CPU stack. PAL uses
985248 Hz and 19656 cycles per call. NTSC uses 1022727 Hz and 17095 cycles per
call; the target SIDSynth's 1022730-Hz NTSC clock is recorded separately.

The adapter initializes the CPU-port direction to $2F and uses the pinned thin
memory-banking model. Write-only/unmapped SID reads return the shared bus latch,
with model-specific decay and read discharge following pinned libresidfp 1.3.0.
The bus ages across initialization, play calls and idle VBI gaps. Writable SID
registers and mirrors within $D400–$D7FF share this bus. Banked-out I/O reads and
writes remain RAM operations. See [Turrican support and checks](TURRICAN.md).
ROM reads, OSC3/ENV3/paddle reads, all other I/O reads, non-SID I/O writes,
reserved/read-only SID writes and unsupported CPU-port direction changes still
fail explicitly. RSID, MUS/PlaySID-specific data, CIA-timed tunes, zero-play
interrupt players, multiple SIDs and full-machine behavior are rejected.

There is no ROM dependency. VIC stalls, DMA, interrupts, CIA timers and SID
oscillator/envelope/paddle readback are not emulated. Unimplemented CPU behavior
and routines exceeding their cycle/instruction budgets fail explicitly. Limits are 100000 play calls,
1000000 recorded SID writes, 1000000 init cycles, one VBI period per play call
and 500000 initialization instructions / 250000 instructions per play call.
Budget errors identify the phase, play-call index, PC and actual/allowed cycle
and instruction counts. The initial exporter caps songs at 1000
patterns. This is a direct-call capture profile, not a general C64 player.

The CPU is the five-module subset of ChiptuneSAK commit
`8759135b5c9c26dc9da155b006c575243ba5304a`. Only import namespaces were changed.
The retained MIT license and original/adapted file hashes are in
[third_party/chiptunesak](../third_party/chiptunesak/manifest.json). To verify or
reproduce it from an already available source tree:

```sh
python3 tools/vendor_chiptunesak.py --source /path/to/ChiptuneSAK-8759135b5c9c26dc9da155b006c575243ba5304a
```

## Capture contract and interpretation

Schema-1 JSONL starts with a header containing source hash/metadata, selected
profile, call budget, init duration and final init registers. Every SID write
has a sequence number, init/play phase, call number, call-relative instruction
cycle, absolute instruction-end cycle, original address, canonical register and
byte value. Equal-value writes and same-call reversals are retained. Call-end
snapshots permit replay checks. A completion footer contains the actual boundary,
write count/digest, execution statistics and write-only SID read counts. New
captures use execution profile `psid-direct-vbi-v2`; existing v1 captures remain
readable and exportable. Schema 1 and its ordered-write records are unchanged.
Export validates sequence, timing, register ranges, init/call snapshots and the
complete footer before writing.

Instruction-end timestamps are more informative than frame snapshots but are
not bus-cycle timestamps. Initialization write history remains in the trace;
an initial active-gate history cannot be restored as oscillator/envelope state
in a patch and is reported.

Interpretation groups ordered play writes at the validated target's 1/256-row
resolution: 20 ms per row, 0.078125 ms per point. All waveform bits, ADSR, pulse
width, sync/ring/TEST, shared filter/routing/modes, volume and voice-3 output are
mapped through stable IDs. Notes own gate/pitch on channels 1–3. The saved patch
sets all 67 parameters, MIDI sources and one-chip routing explicitly.

Note anchors use the nearest pitch from a call-end snapshot; noise-only attacks
prefer a tonal snapshot within three calls. This heuristic labels musical
segments; it does not reduce sound automation to frame snapshots. All pitch
motion is represented as relative 0.01-semitone tuning, including gate-off
release. If multiple source note events compete for one voice/row, the final
event is retained and every reduced row is reported. Sub-quantum gate sequences,
repeated-register collisions, frequency before MIDI ownership, zero frequency
and out-of-range relative tuning are also reported. No Manual-source replay is
hidden underneath note tracks.

The current MIDI tuning range cannot reach a literal zero SID frequency, and
MIDI sources cannot initialize a pre-note oscillator pitch reference. Those are
reported approximations, not silently declared equivalent behavior. The report
also counts controls closer than the host's measured 333-us granularity. Native
automation can coalesce those points and canonicalizes register-write order;
unchanged-write side effects are not recreated. See [TIMING.md](TIMING.md).

XRNS uses deterministic archives, 256-row patterns, one SIDSynth and two aliases,
Points-mode envelopes and complete time-zero/carry values at every pattern.
Sustained notes continue across boundaries without synthetic retriggers. Seeking
into a held note does not reconstruct earlier MIDI ownership. Source capture,
interpretation and writing are separate modules so later improvements can reuse
the original ordered trace.

The optional [comparison tool](COMPARISON.md) documents independent playback
and listening checks for the percussion timing defect in 0.2.1.
[Source envelope timing](ENVELOPE_TIMING.md) documents the 0.3.0 correction.
