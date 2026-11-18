# SID2XRNS project instructions

Read README.md, docs/PLAN.md and docs/STATUS.md before implementation.
Linux CLI exporting editable Renoise XRNS songs played by SIDSynth.
Exactly one SIDSynth instance plus two aliases. Notes own pitch/gate; native
automation owns sound changes and relative pitch, including releases.
Keep capture, interpretation and XRNS writing separate. Preserve ordered SID
writes before musical reduction. Do not modify original Alibi reference files.
Pin dependencies and record licenses. Work offline; no HVSC integration.
The duration/end-boundary policy is undecided. Do not implement loop trimming.
Finish the native timing fixture before generalizing the SID capture/export CLI.
Use isolated Renoise profiles and PID/path guards for host tests. Label offline,
actual-host and listening evidence separately. Never infer host success from a
build. Update docs/STATUS.md with exact commands, results, limits and next work.
Do not change the sibling SIDSynth product or install a plugin without a concrete
reason established by the timing measurements. Preserve existing pending work.
