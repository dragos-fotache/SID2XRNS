# Original CLI example

`cli-performance.xrns` is generated from the original tiny
`../fixtures/cli-performance.sid` program. Its source generator is
`../tests/sid_fixtures.py`. The three MIDI parts share one SIDSynth. Voice 1
retunes after note-off, voice 2 holds across patterns, and voice 3 has its own
note pair. The program repeats naturally when its byte counter wraps; the
520-call capture preserves those repeats.

The captured writes and conversion report are beside the song. Regenerate from
the project root into a fresh output path:

```sh
./bin/sid2xrns convert fixtures/cli-performance.sid --play-calls 520 -o work/example.xrns \
  --trace work/example.capture.jsonl.gz --report work/example.report.json
```

This is a functional transport/ownership example. Its four sub-333-us control
intervals remain timing risks; its report has no semantic reductions. It is not
an audio-fidelity reference. SIDSynth must be installed to play the XRNS.
