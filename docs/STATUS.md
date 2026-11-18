# Current status

Updated 18 November 2026. Project at `/home/dragos/work/SID2XRNS`.

## GitHub Actions

Build runs on push. Starting with 0.4.1, it packages a standalone Linux
x86-64 executable and a single `LICENSES.txt`, then produces the archive
checksum. Release runs manually and can publish the tested archive at the
selected commit's CLI version. The initial workflow setup is on `main` in `6c63827`.
[Release instructions](RELEASING.md).

**Local build, agent performed.** All 47 Python tests pass and actionlint
validates both updated workflows. The 0.4.1 archive builds in the pinned
Debian Bookworm container and contains exactly the executable and notices.
The extracted executable produces byte-identical XRNS output in both
envelope modes when compared with the source CLI. A fresh Debian Bookworm
container with glibc 2.36 and no Python installed also passed a conversion
from an isolated directory with networking disabled.

```sh
python3 -m unittest discover -s tests -v
bash tools/package_linux.sh work/linux-release
(cd work/linux-release && sha256sum --check SID2XRNS-0.4.1-linux-x86_64.tar.gz.sha256)
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12 .github/workflows/build.yml .github/workflows/release.yml
```

**Earlier GitHub Actions, agent performed.** The push build and the manually
dispatched release dry run both passed. They built the committed 0.3.1
converter. The dry run verified the uploaded archive's checksum.
[Build run](https://github.com/dragos-fotache/SID2XRNS/actions/runs/44270044990) ·
[Release dry run](https://github.com/dragos-fotache/SID2XRNS/actions/runs/44270070193).

```sh
gh workflow run release.yml --ref main -f dry_run=true
gh run view 44270044990 --json status,conclusion
gh run view 44270070193 --json status,conclusion
```

## Convert defaults

`convert` uses the selected subsong's duration in `Songlengths.md5` in the
current directory when no window option is given. It creates only the XRNS
by default. Use `--trace PATH` or `--report PATH` to save either file.
`export` still saves its report by default.

**Offline, agent performed.** All 49 Python tests pass. The rebuilt
standalone executable ran `sid2xrns convert Crystal_Dawn.sid` from a
temporary directory containing the tune and database. The official
database lists 215.683 seconds. The command created exactly one file, a
readable 43-pattern `Crystal_Dawn.xrns`. No playback check was run for this
CLI change.

```sh
python3 -m unittest discover -s tests -v
bash tools/package_linux.sh work/linux-release-simple-convert
```

## Export output level

`convert` and `export` now default to 0 dB SIDSynth Output. All 48 Python
tests pass, including checks of saved plugin state with the default and an
explicit gain in both commands.

**Actual Renoise, agent performed.** Using the same Turrican 3 subsong 9
capture, the recorded peak rose from 0.05875 to 0.23386 full scale
(+12.0 dB) at 48 kHz / 1024 device frames. The unity-gain export passed
the installed-plugin check in a private Renoise 3.5.4 profile, which closed
normally. [Playback check](../work/turrican-unity-gain-host-check.json)

```sh
python3 -m unittest discover -s tests -v
./bin/sid2xrns export work/hvsc-turrican3-sub9.capture.jsonl.gz \
  -o work/hvsc-turrican3-sub9-unity.xrns
```

## Step 6 — offline HVSC duration lookup implemented

Converter **0.4.0** accepts a local modern `Songlengths.md5` for
`inspect`, `capture`, and `convert`. Bare `--hvsc-db` opens
`Songlengths.md5` in the shell's current directory. An explicit path can
point to another copy. Capture uses the selected subsong's
listed duration rounded up to a whole VBI play call. The trace and report
keep the original duration and the whole-file SID MD5. Direct
`--play-calls` remains available for any supported SID, including files
without an HVSC entry. [CLI usage](CLI.md).

**Automated by the agent.** The tests cover
fractional timestamps, whole-file matching across filenames, PAL/NTSC
rounding, subsong selection, missing or invalid entries, and re-export
without the database. They exercise bare `--hvsc-db` for all three commands
from a directory outside the checkout. The official database matched Alibi
at 196 s with the bare flag from a temporary directory.
Its export captures 9,825 calls (196.011766 s) and runs 199.24 s including
release padding. Turrican 3 matched all 24 subsongs. Subsong 9 uses the
listed 4 s, captures 201 calls (4.010012 s), and exports a 5 s song.
That XRNS is byte-identical to an explicit 201-call conversion and a
bare-flag conversion from outside the checkout.

Verified that the main help and the `capture` and `convert` help pages
describe what each command produces. With no `-o`, `convert` uses the SID
basename and writes the song in the current directory.
A test verifies the names and overwrite protection when the SID is in a
different directory. A real Turrican 3 conversion with both bare `--hvsc-db`
and the default output name also produced a byte-identical XRNS.

**Actual Renoise, agent performed.** The Turrican 3 subsong 9 export played
for 5.25 s in an isolated Renoise 3.5.4 session at 48 kHz / 1024 device
frames using the installed SIDSynth. The check verified all 80 parameters,
aliases/channels, equal stereo, unclipped output and silence after stop.
The private session closed normally. Its relative plugin path failed to
load in the first session and the retry used an absolute path.
[Host check](../work/hvsc-turrican3-sub9-host-check.json).
Alibi was checked offline. Listening for these exports remains unassessed.

The [official database](https://hvsc.de/download/C64Music/DOCUMENTS/Songlengths.md5)
used for these checks is 5,205,150 bytes with SHA-256
`3f2bb5c14e3396fb20979cb017421386dc9e32162999974ad1e4f0a230dc397e`.
The local copy is `work/hvsc-songlengths.md5`.

Working commands (choose fresh output and private profile names):

```sh
python3 -m unittest discover -s tests -v
./bin/sid2xrns --help
./bin/sid2xrns capture --help
./bin/sid2xrns convert --help
./bin/sid2xrns inspect /home/dragos/work/Alibi-Renoise/Alibi.sid \
  --hvsc-db work/hvsc-songlengths.md5
./bin/sid2xrns convert /home/dragos/work/Alibi-Renoise/Alibi.sid \
  --hvsc-db work/hvsc-songlengths.md5 -o work/hvsc-alibi.xrns
./bin/sid2xrns convert usertests/Turrican_3.sid --subsong 9 --model 8580 \
  --hvsc-db work/hvsc-songlengths.md5 -o work/hvsc-turrican3-sub9.xrns
./bin/sid2xrns convert usertests/Turrican_3.sid --subsong 9 --model 8580 \
  --play-calls 201 -o work/hvsc-turrican3-sub9-manual.xrns
cmp work/hvsc-turrican3-sub9.xrns work/hvsc-turrican3-sub9-manual.xrns
python3 probe/host.py launch \
  --config /home/dragos/work/SIDSynth/work/midi-import/config/Renoise/V3.5.4/Config.xml \
  --remcp /home/dragos/work/SIDSynth/work/midi-import/config/Renoise/V3.5.4/Scripts/Tools/com.renoise.ReMCP.xrnx \
  --label hvsc-turrican3-sub9-abs --quantum 1024 \
  --plugin-dir /home/dragos/work/SID2XRNS/work/product-plugins --song hvsc-turrican3-sub9.xrns
python3 probe/product_check.py --name hvsc-turrican3-sub9-host --seconds 5.25
python3 probe/close_host.py
```

**Next concrete task.** Broaden representative-tune listening and
compatibility within the PSID/VBI scope.

## Step 5 — release-tail rows implemented

Converter **0.3.1** adds 20 ms rows after the existing cutoff to accommodate
the longest estimated release. It covers both synthetic cutoff note-offs
and releases that started during capture. The estimate uses the exported
release rates and target clock with room for SID envelope counter delays.
It can leave silence after the decay. The report gives the number of added
rows and the total song duration. Both source and legacy envelope modes
use the same policy. See [CLI usage](CLI.md).

**Automated by the agent.** All 41 Python tests pass. The new checks cover a
tail crossing a pattern boundary, two release speeds, a release rate change
after note-off, and a decay allowance that expires before the cutoff. The
Alibi re-export uses the same 12,000-call ordered capture and retains all
4,864 note cells and all 235,605 existing automation points. Its voice 3
note-off remains at 239.420 s. The new export adds 180 rows and ends at
243.040 s. The additional pattern carries the last automation values.
The working song is [alibi-release-tail.xrns](../work/alibi-release-tail.xrns).

**Actual Renoise, agent performed.** In an isolated Renoise 3.5.4 diagnostic
run at 48 kHz / 1024 device frames, a sustained voice received its OFF at
0.400 s. The SID envelope reached zero at 1.151 s and stayed at zero up to
the song wrap at 1.380 s. The private host closed normally. The trace and
measured times are in [work/release-tail-fixture-1024.json](../work/release-tail-fixture-1024.json)
and [work/release-tail-fixture-decay.json](../work/release-tail-fixture-decay.json).
The revised Alibi ending has offline structural verification. Listening and
live Alibi playback for this revision remain unassessed.

Working commands (choose fresh output and private profile names):

```sh
python3 -m unittest discover -s tests -v
./bin/sid2xrns export work/alibi-cli-window.capture.jsonl.gz -o work/alibi-release-tail.xrns
./bin/sid2xrns convert work/release-tail-fixture.sid --play-calls 20 \
  --diagnostic -o work/release-tail-fixture-probe.xrns \
  --trace work/release-tail-fixture-probe.capture.jsonl.gz
./bin/sid2xrns export work/release-tail-fixture-probe.capture.jsonl.gz \
  --envelope-timing legacy -o work/release-tail-fixture-legacy.xrns
python3 probe/host.py launch \
  --config /home/dragos/work/SIDSynth/work/midi-import/config/Renoise/V3.5.4/Config.xml \
  --remcp /home/dragos/work/SIDSynth/work/midi-import/config/Renoise/V3.5.4/Scripts/Tools/com.renoise.ReMCP.xrnx \
  --label release-tail-1024 --quantum 1024 --song release-tail-fixture-probe.xrns
python3 probe/host.py capture --name release-tail-fixture-1024 --seconds 1.65
python3 tools/check_envelope_capture.py work/release-tail-fixture-1024.json \
  -o work/release-tail-fixture-ownership.json
python3 probe/close_host.py
```

## Step 4 — robust percussion timing correction implemented

Converter **0.3.0** introduced source envelope timing with **SIDSynth 0.6.0**
and saved state **schema 4**.
[ENVELOPE_TIMING.md](ENVELOPE_TIMING.md) documents source-derived envelope
counter/pipeline cues, CRC integrity and coalesced native publication. The
original 67 IDs/indices remain stable; 13 host-only metadata parameters are
appended. Notes retain pitch/gate ownership and all original note cells. Old
patches default cues off; `--envelope-timing legacy` retains the earlier export.

**Automated by the agent:** 39 Python tests pass. The source model matches 2203
randomized observations / 5115269 cycles against the unmodified pinned core.
Release CTest passes 1/1 (18.00 s), ASan/UBSan/leak CTest 1/1 (195.16 s), and
pluginval strictness 10 passes at 44.1/48/96 kHz and blocks 1/64/257/1024.
Source-enabled callbacks pass the allocation/free/pthread-lock guard. Tests
cover arrival-phase invariance, three rates, packed precision/CRC corruption,
MIDI ownership/deletion, CC120, Panic, stop and schema migration/recall. The
probe is sample-identical to the processor at 128/1024 callbacks; its ENV3
chunk timestamps now remain monotonic for large engine renders.

**Actual Renoise, agent performed:** final 48-kHz / 1024-frame playback covers
the full 239.4-s window. All 599 measured percussion envelope peaks are within
**1.27 ms** of the controlled source, with **zero** >10-ms jumps. The reported
six-second passage has all 50 peaks within **1.02 ms**. Zero torn packets,
overflow or gate-ownership mismatches occur across 49434 playing blocks / 290333
ENV3 observations. All 4864 original note events remain, with maximum native
note timing error **0.015625 ms**. The 256-frame repeat also passes the reported passage (all 50 peaks within
1.02 ms; inter-buffer peak difference at most 0.667 ms). Its 22769 playing blocks
show zero torn packets, overflow or gate-ownership errors. Audio is not sample-
identical across host buffers. The installed product passes a 67-s recording,
all 80 initial values, aliases/channels, unclipped equal stereo, stop silence,
save/reopen/playback and legacy schema-3 playback with cue mode/words reset off.
A synthetic real-host note-deletion check leaves voice 3 unowned/gated off while
its source automation continues. See [step-4 evidence](../evidence/step4/summary.json).

**User listening:** the user confirms the three reported timing problems sound
fixed in the level-matched 59.75–65.75-s corrected excerpt. That listening
confirmation was on the initial audible correction, before the packet integrity
safeguard; no full-song subjective fidelity approval is claimed.

The corrected working song is `work/alibi-envelope-corrected.xrns`, with its
retained report beside it. The plugin is installed locally, with the complete
old bundle retained at `/home/dragos/work/SIDSynth/work/envelope-installed-0.5.1-backup`.
Canonical init, native quantization and other capture/representation limits
remain explicit. No ending is inferred, no original Alibi file is changed,
and no commit/push is performed. Normal Renoise preferences remain untouched. All private hosts are normally closed.

Working commands (use fresh output/profile names):

```sh
./bin/sid2xrns export work/alibi-cli-window.capture.jsonl.gz -o work/alibi-envelope-corrected.xrns
python3 -m unittest discover -s tests -v
python3 tools/check_envelope_model.py work/step4/envelope-oracle
cmake --build work/build --target SIDXRNSTimingProbe_VST3 probe_self_check --parallel 4
work/build/probe_self_check
python3 tools/check_envelope_capture.py work/envelope-final-1024-full.json \
  --source work/alibi-cli-window.capture.jsonl.gz -o work/step4/new-host-check.json
```

## Historical step 3 checkpoint

## Step 3 — comparison implemented; percussion fidelity fails

`bin/sid2xrns-compare` **0.1.0** now supplies independent VICE source rendering,
ordered-write checks, actual-host register comparison and audio reports/clips.
Converter **0.2.1**, its standard-library runtime, the installed SIDSynth and
saved parameter/state contract are unchanged. [COMPARISON.md](COMPARISON.md)
records exact commands, methods, limits and [retained evidence](../evidence/step3/summary.json).
The reference pins installed VICE 3.10 / package 3.10-3 and local ROM hashes;
optional NumPy/SciPy/Matplotlib versions/licenses are pinned and retained.
Everything ran offline, without new installation or HVSC access.

**Automated by the agent:** 36 tests pass. Independent play-phase writes match
all 287977 Alibi writes over 12000 calls, 20400 Turrican writes over 1200 calls,
48 existing synthetic writes and 27 new known-event writes, with zero mismatched
calls. Alibi's timing difference against the independent VICE driver is at most
about 1.015 us after first-play alignment. Independent synthetic WAV/write/entry
repeats are byte-identical. The extended diagnostic verifies sample-identical
audio against the direct processor, register replay and offsets 13/47. No new
complete callback allocation/mutex, sanitizer or pluginval audit is claimed.

**Actual Renoise 3.5.4 Demo, automated by the agent:** full Alibi playback is
recorded from the installed plugin at actual 48 kHz / 1024 device frames, with
complete 239.4036875-s audio comparison coverage, all 67 effective initial values,
aliases/channels, unclipped equal stereo and silence around transport. The full
diagnostic first pass records 102321 physical writes and passes 48390 register-
replay block checks with zero overflow. Later loops are excluded from analysis.
The reported 59.75–65.75-s excerpt has 2860 physical writes with identical sample
timelines at actual 1024/256 device frames. Seven synthetic correct/fault/edit
takes are sample-identical across both settings; the unchanged correct case also
repeats exactly. All five intentional faults are detected in real-host audio;
the octave edit changes voice-2 frequency while preserving other register fields.

**User listening:** three percussion hits sound off in the posted six-second
Alibi excerpt, first before excerpt second 1, apparently early. Placement/shape
is the concern, not exact timbre. Full fidelity is not approved; full-window
listening remains unassessed.

**Focused regression:** direct non-mutating real-processor ENV3 readback shows a
peak about **32.834 ms early** near excerpt **0.70 s** (source **60.449987 s**).
The source's SR write leads the gate by 13 CPU cycles; both round to one native
unit. Controlled replay at the actual measured chip clock reproduces ENV3
(mean absolute error 0.281 / 255, 98.65% within three units). Substituting the
source SR schedule restores the first expected peak; control-word substitution
alone does not. The roughly 33-ms discontinuity is consistent with SID ADSR
rate-counter delay. Five large envelope deviations are distinct from the three
perceived hits; peak times are not identical to audible attack times. The
resampler's measured effective clock/phase difference is also documented.

**Scratch candidate, not adopted:** advancing collapsed ADSR changes one native
unit moves 2507 points without changing notes. It repairs the first peak to
**+0.562 ms**, but introduces another roughly 33-ms early peak near excerpt
**0.580 s**. It remains an optional experimental fidelity helper, with regression
tests. No general timing correction or new production policy is claimed.

All private hosts are normally closed. Preservation checks cover the original
Alibi files, Turrican input, installed module, normal Renoise profile and pending
sibling source/tests; only sibling documentation is updated. No product install,
commit or push. Full raw traces/WAVs/scratch XRNS files remain under `work/`;
compact results, raw excerpt context, tests and hashes are in `evidence/step3/`.

Working checks:

```sh
python3 -m unittest discover -s tests -v
cmake --build work/build --target SIDXRNSTimingProbe_VST3 probe_self_check --parallel 4
work/build/probe_self_check
python3 tools/collect_step3_evidence.py
```

Use fresh output/profile names for the full reference/host commands in
[COMPARISON.md](COMPARISON.md). Those checks record new runtime/host evidence;
the earlier checkpoints below remain historical.

**Next concrete task — step 4:** reduce the SR/gate interaction to an original
deterministic regression and implement a robust representation/timing policy.
Preserve envelope behavior across both buffers and real passages; validate note
ownership, recall, full-window playback and listening. Do not adopt the failed
one-unit guard or hide Manual replay under notes. Duration/end selection remains
open; preserve raw captures, originals and pending synth work.

## Earlier step-2 compatibility checkpoint

**Compatibility update — CLI 0.2.1:** Turrican 3 now captures and exports. Init
has a separate 500000-instruction allowance with the existing 1000000-cycle
bound; play-call bounds remain in force. Shared write-only SID bus reads use
the model decay/discharge policy from pinned libresidfp 1.3.0. OSC3/ENV3/paddle,
ROM and other hardware limitations remain explicit. Captures use v2 execution
metadata; schema-1/v1 traces still export. No new runtime dependency or vendored
CPU change. See [TURRICAN.md](TURRICAN.md) for exact commands and evidence.

**New automated checks:** 24 tests pass. All 24 Turrican subsongs export with
both models for 1200 calls each (48 cases); snapshots replay against ordered
writes and native instance/alias/channel/parameter structure passes. Default
subsong 2 / 8580 also exports 12000 calls / 239.403683 seconds into 47 patterns.
Ten bus-policy read checks match the compiled pinned SID core. Alibi's first
28777 writes / 1200 snapshots match its previous capture, and its old v1 full
capture re-exports byte-identically. No ending was inferred.

**New actual Renoise checks, automated by the agent:** the short Turrican song
and full 47-pattern container load in isolated Renoise 3.5.4 Demo; short playback
verifies 67 effective values, aliases/channels, nonzero unclipped equal stereo
audio and silence around transport. Saved-song reopen/playback also passes;
time-zero automation restores 16 later saved values. The private host closed
normally; inputs, sibling synth source/module and normal preferences are
preserved. No full-window playback, listening approval or
independent audio fidelity is claimed. Existing timing/representation reductions
are retained in reports. Step 3 was next at that checkpoint; it is now recorded above.

**Step 2 implemented: CLI 0.2.0.** `bin/sid2xrns` provides `inspect`, `capture`,
`export` and `convert`. It runs offline with Python and the included pinned MIT
CPU subset. Ordered schema-1 capture, interpretation and native writing are
separate modules. Conversion needs no Renoise, compiler or installed plugin;
playback needs the compatible release-pitch-corrected SIDSynth. See [CLI.md](CLI.md).

Initial scope is one SID, directly callable RAM PSID init/play routines and fixed
VBI timing. Unsupported hardware/ROM access, CIA/interrupt players, multiple SIDs,
malformed data and execution budgets fail explicitly. Every song contains all
67 parameters, three real MIDI note parts, one plugin plus two aliases and native
Points automation. Reports quantify semantic reductions and sub-333-us timing
risks. A strict mode rejects these and keeps capture/report without a new song.

The development play-call budget bounds capture; the final song-ending policy
remains undecided. No HVSC lookup, repeat detection or automatic trimming exists.

**Automated:** 17 Python tests pass, including all five step-1 checks. The pinned
ChiptuneSAK subset reproduces from its local source with only relative-import
changes. The complete original synthetic example is in [examples](../examples/README.md).
Its generated XRNS bytes match the host-tested export and preserve all 520 calls,
including repeated sections. An explicit 12000-call Alibi window retains 287977
ordered writes, matches all 12000 preserved snapshots, and exports 47 patterns.
This baseline shares the CPU family and is not an independent audio oracle.

**Actual Renoise 3.5.4 Demo, automated by the agent:** the synthetic CLI song
receives notes on all three channels, retunes a release while another part stays
held, preserves a held voice across the pattern boundary and has at most
0.015625-ms note error. Physical-write replay matches 314 subsequent snapshots.
A short Alibi export loads/plays/saves/reopens/plays with the installed SIDSynth;
all 67 effective parameters, aliases/channels, equal stereo, unclipped audio and
silence around transport pass. The full 47-pattern container also opens with all
sequence entries and passes short playback. No full-window playback or subjective
listening is claimed. See [STEP2.md](STEP2.md) and [evidence](../evidence/step2/summary.json).

**Known limits at step 2:** the Alibi window reports 15 frequency changes before note
ownership, 2433 zero-frequency intervals that the current MIDI tuning path cannot
represent literally, and 2308 sub-333-us control intervals. This is an editable
approximation with retained source writes. Independent source rendering, audio
comparison and listening were still pending then; step 3 above records their
implementation and the failed percussion check. SIDSynth source/tests, installed
module, normal preferences and Alibi originals were not edited. Private hosts
were normally closed. No commit/push or global CLI/plugin installation.

**Next at step 2 (completed above):** choose and pin an independent source renderer/
write reference, compare actual exported-song playback on synthetic cases and
Alibi, localize the worst passages, inject known faults, and obtain listening
feedback. Do not use the historical snapshot baseline as the fidelity oracle.
Keep the end-boundary decision open and preserve the explicit raw capture.

## CLI commands

Run from this folder (or invoke the absolute `bin/sid2xrns` path from anywhere):

```sh
./bin/sid2xrns --version
./bin/sid2xrns inspect /home/dragos/work/Alibi-Renoise/Alibi.sid
./bin/sid2xrns convert fixtures/cli-performance.sid --play-calls 520 -o work/example.xrns
./bin/sid2xrns convert /home/dragos/work/Alibi-Renoise/Alibi.sid \
  --play-calls 12000 -o work/alibi-window.xrns
./bin/sid2xrns export work/alibi-window.capture.jsonl.gz -o work/alibi-reexport.xrns
python3 -m unittest discover -s tests -v
```

Use fresh output paths; `--force` explicitly permits replacement. Current working
Alibi output is `work/alibi-cli-window.xrns`, its ordered trace/report are beside
it. The report, compact synthetic host traces and actual host checks are retained
under `evidence/step2/`; full logs, captures and recordings remain in `work/`.
Tested Python/runtime versions and exact source digests are in the evidence.

Step 1 remains available in [TIMING.md](TIMING.md): all tested 20-ms/2-ms controls
survive at 48 kHz / 1024 and 256 frames; a 250-us burst loses four of 16 changes
at both settings. Device buffer size differs from native automation callback size.
The optional probe compiles the actual locked SIDSynth core/processor; it is not
part of the CLI runtime and does not replace the installed plugin.

## Optional step-1 diagnostic commands

Run from this project. The source lock includes the existing uncommitted
SIDSynth release-pitch fix. A clean checkout of its recorded commit needs
`docs/sidsynth-source.patch` applied before its source hashes will match.
Do not apply that patch to the already corrected sibling checkout.

```sh
cmake -S probe -B work/build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DSIDSYNTH_SOURCE_DIR=/home/dragos/work/SIDSynth \
  -DFETCHCONTENT_SOURCE_DIR_JUCE=/home/dragos/work/SIDSynth/build-clean/_deps/juce-src \
  -DFETCHCONTENT_SOURCE_DIR_LIBRESIDFP=/home/dragos/work/SIDSynth/build-clean/_deps/libresidfp-src
cmake --build work/build --target SIDXRNSTimingProbe_VST3 probe_self_check --parallel 4
work/build/probe_self_check
python3 -m unittest discover -s tests -v
python3 probe/make_fixture.py --template fixtures/native-template.xrns \
  --bindings fixtures/sidsynth-bindings.json --output work/native-timing-probe.xrns
python3 probe/make_fixture.py --template fixtures/native-template.xrns \
  --bindings fixtures/sidsynth-bindings.json --output work/native-timing-subms-probe.xrns --submillisecond
```

Private host launch, using locally installed ReMCP and copied preferences:

```sh
python3 probe/host.py launch \
  --config /home/dragos/work/SIDSynth/work/midi-import/config/Renoise/V3.5.4/Config.xml \
  --remcp /home/dragos/work/SIDSynth/work/midi-import/config/Renoise/V3.5.4/Scripts/Tools/com.renoise.ReMCP.xrnx \
  --label new1024 --quantum 1024 --song native-timing-probe.xrns
python3 probe/host.py capture --name new1024
python3 probe/analyze.py work/new1024.json work/native-timing-probe.expected.json work/new1024-results.json
python3 probe/close_host.py
```

Use a fresh label for each host profile. The label names the profile only; the
actual device and callback sizes must be verified from the log and trace.
Private ReMCP uses loopback port 19716. Normal user profiles are not modified.
Native tools bound to the normal MCP endpoint cannot target these isolated
profiles, so the runner uses their dedicated guarded HTTP endpoint.

The completed matrix's orchestration uses labels/capture names in
`probe/collect_evidence.py`; its original inputs and per-run metadata remain in
ignored `work/`. Recollecting verifies the raw register traces and refreshes
`evidence/`. Raw float audio, full host transcripts, logs, saved roundtrips and
normal-close records remain in `work/`; compact raw traces/results and one
installed-plugin recording are retained outside ignored folders.
