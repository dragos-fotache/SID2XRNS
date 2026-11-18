# Implementation plan

1. **Implemented/measured:** generate a native XRNS timing fixture from a host-saved template. Validate
   parameter bindings against the actual processor and live host. Measure
   fractional automation, delayed notes, adjacent 20-ms updates and faster
   bursts, release tuning, waveform/pulse/filter controls, ADSR/TEST/gate ordering,
   silent initialization, stop/start and save/reopen. Compare available host
   block sizes. Record losses as results, not hidden approximations.
2. **Implemented as CLI 0.2.0:** pinned SID execution/capture, interpretation, XRNS
   writing. Define supported SID scope and unsupported behavior. Keep ordered
   timestamped writes. Decide the export-boundary policy with the user later.
   **Compatibility update 0.2.1:** bounded packed initialization and write-only
   SID bus reads for Turrican 3; all 24 subsongs checked with both SID models.
3. **Implemented; fidelity regression found:** independently compare source
   playback with actual exported-song playback. VICE write checks, full-window
   Alibi host recording, synthetic fault/edit tests and user listening are
   recorded in [COMPARISON.md](COMPARISON.md). The reported percussion envelope
   can peak about 33 ms early. Blind point advances fix one hit and create another.
4. **Implemented — CLI 0.3.0 / SIDSynth 0.6.0:** source-derived envelope timing
   cues preserve the SID rate counter/pipelines across native automation timing
   changes. CRC-protected packets and coalesced publication reject partial host
   updates. Real MIDI notes retain pitch/gate ownership; state schema 4 appends
   13 metadata parameters and migrates old patches with cues off. Release,
   sanitizer, pluginval, actual Renoise and listening evidence are in
   [ENVELOPE_TIMING.md](ENVELOPE_TIMING.md) and [STATUS.md](STATUS.md).
5. **Release tails implemented in CLI 0.3.1:** preserve the capture boundary and
   note-off timing, then reserve whole XRNS rows for the estimated SID decay.
   **Next:** agree how users specify capture duration. The current CLI takes an
   explicit play-call count. Continue representative-tune listening and
   compatibility checks within the documented PSID/VBI scope.

SIDSynth remains a separate Linux VST3 plugin. No MIDI-import transport, hidden
Manual replay, HVSC dependency or automatic loop trimming is planned.
