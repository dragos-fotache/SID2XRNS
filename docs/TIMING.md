# Native XRNS timing checkpoint

17 November 2026. Implemented and measured by the agent in actual **Renoise
3.5.4 Demo on Linux**, at **48 kHz** with **1024- and 256-frame JACK device
buffers**. This is a synthetic native-song experiment, not a SID conversion or
an independent source-SID fidelity comparison. Listening has not been assessed.

## Results

| Requested behavior | Measured result at both device buffers |
| --- | --- |
| 20-ms tuning, pulse-width and cutoff changes | 60/60 significant changes reach the processor and SID registers |
| 2-ms waveform, pulse-width and cutoff burst | 24/24 changes survive; up to 0.317709 ms early against encoded point times |
| 250-us pulse-width/cutoff stress burst | 12/16 changes survive; four missing changes, two per parameter |
| Percussion ADSR/waveform/TEST changes | 16/16 significant changes survive in the tested sequence |
| Release pitch | 4/4 tuning changes update physical frequency with gate off and no active note owner |
| Note timing | 13 note-column events produce 14 MIDI messages, including the host's implicit replacement note-off; maximum encoded-time error 0.015625 ms |
| Initialization and stop | Exact zero in captured processor samples before play and after stop |
| Stop/start, native save/reopen, buffer comparison | Identical physical-write timelines in the measured musical passage |
| Note edit | First note 69 → 81 changes its SID frequency register 7493 → 14985, with identical automation |

The important correction to the prior assumption is that **device buffer size
does not equal native automation callback size in this route**. Renoise splits
processing into smaller callbacks around native automation. Observed callback
sizes span 16–1024 frames in the 1024-frame stress run and 16–256 in the smaller
buffer run. The processor still reads patch values at callback boundaries; the
host supplies more boundaries than the nominal device buffer suggests.

The smaller device buffer does not recover the missing 250-us changes. These
results support the tested frame-scale and 2-ms patterns, not a universal timing
guarantee or cycle-exact reproduction. No synth correction is justified by this
fixture alone. Ordered capture and explicit loss reporting remain necessary.

## Native representation

The included [timing song](../fixtures/native-timing.xrns) targets the normal
installed SIDSynth. It derives from a freshly Renoise-saved private template.
The archive contains exactly one plugin device and two direct aliases, three
MIDI-source note parts, schema-3 patch state and native Instrument Automation.
All 67 bindings come from the compiled parameter specifications and are checked
against the live host's names and order. The build also checks the complete
15-file SIDSynth source lock before compiling the probe.

125 BPM × 24 LPB gives 20 ms per row. Note delay and automation points use 256
units per row, giving 0.078125 ms representational resolution and a theoretical
rounding bound of 0.0390625 ms. The largest rounding error in this fixture is
0.03125 ms. Note timing above is measured against encoded times; source rounding
is reported separately. Delay columns are visible, and envelopes use Points
mode. Every automated control has a time-zero point.

The latter matters for recall: Renoise reapplies time-zero native automation
while stopped. After saving the played song, five later saved patch values
(voice-1 tuning/pulse width, cutoff, voice-2 tuning and voice-3 release) are
overridden by those initialization points on reopen. The installed-plugin check
compares all 67 effective values with **saved patch plus time-zero automation**.
Both initialization and replay are silent until real notes arrive.

## Observation method

The diagnostic VST3 has its own identity and is scanned from its build directory
inside a private Renoise profile. Its first 67 parameters proxy the actual
SIDSynth processor; one additional parameter arms/freezes capture. It runs one
real SIDSynth processor and one real SID core. Production source files and the
installed bundle are unchanged.

ELF linker wrapping observes the real SidBackend write/reset calls. Wrapping
SidEngine::render advances a host-sample cursor, including silent spans, so
MIDI-offset writes retain their exact offsets. A fixed-capacity sink records
MIDI, callback position/size, parameter values, end-of-callback registers/note
owners and processor audio. JSON and float audio export happen only after a
freeze handshake on the message thread. Diagnostic output to speakers is zero.
No full allocation/lock guard run is claimed for this diagnostic build.

The offline C++ check compares the proxy's registers with an unwrapped real
processor, including release pitch, and verifies physical gate edges at sample
offsets 13 and 47. Analysis replays every captured write/reset and compares its
result with every subsequent register snapshot. A fault-injection regression
removes an actual captured gate write and verifies rejection. Value transitions
are matched once each; unchanged repeated values are not counted as losses.
Host PPQ plus within-block offsets provide song-relative measured time.

Seven compressed raw traces, their inputs and complete results are retained in
[evidence/](../evidence/timing-summary.json), with SHA-256 checks. Native 1024,
restart, recall and native 256 runs have identical physical-write timelines
from the first note through the final note-off. Both stress runs also match.
Audio waveform equality after a live restart is not claimed: the existing core
can retain oscillator phase across reset.

The final fixture was also opened and played with the **installed SIDSynth**,
then saved/reopened in a fresh private host and played again. All 67 effective
parameter values, aliases/channels, equal stereo channels, nonzero unclipped
audio and exact silence after stop pass. Recorded peak is 0.024201 of full
scale. Only that PID's output ports were connected to a temporary recorder;
its speaker links were detached and restored after stop. A
[real installed-plugin recording](../evidence/installed-product.wav) is retained
for audition. No subjective listening or user approval is inferred from it.

## Harness development issues and limits

Two early disposable hosts crashed on incorrect alias fields in the first
writer. The writer now validates saved aliases -1/0/0, channels 0/1/2 and exactly
one plugin; the cyclic-link regression passes. A later unsaved document switch
reached Renoise's X11 dialog-centering recursion. The helper now saves a private
backup before a switch; the recall checks above used fresh-process startup.
An installed-plugin scan trial lacked the normal plugin path and was closed
normally; a private symlink directory then exposed only the installed SIDSynth.
These failed trials are excluded from the timing results. Original Alibi files,
SIDSynth source/tests, installed plugin and normal Renoise profile were not edited.

The fixture does not establish arbitrary SID write ordering, intra-cycle TEST/
gate behavior, audio fidelity against a source SID, alternate sample rates,
other Renoise versions or listening quality. The next step is the separate
capture/interpretation/export pipeline with a bounded SID scope. The export
boundary/duration policy remains undecided; no HVSC lookup or loop trimming
was implemented.
