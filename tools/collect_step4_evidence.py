#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Retain compact envelope-fix evidence; full music/audio stay in ignored work."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=Path('evidence/step4'));a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
root=Path(__file__).resolve().parents[1];work=root/'work';synth=root.parent/'SIDSynth'
def read(p):return json.loads(p.read_text())
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
files=['final-1024-check.json','final-256-clean-check.json','percussion-final-1024.json','percussion-final-256-clean.json','percussion-final-full.json','buffer-comparison.json','synthetic-check.json','deleted-voice-check.json','model-oracle-final.json','installed-clip.json']
for name in files:shutil.copyfile(work/'step4'/name,a.output/name)
products={}
for name in ('envelope-installed-final','envelope-installed-recall','envelope-installed-legacy'):
    src=work/(name+'-check.json');shutil.copyfile(src,a.output/src.name);products[name]=read(src)
for src,name in [(work/'step4/python-final-tests.log','python-tests.log'),(work/'step4/probe-final-self-check.log','probe-check.log'),(synth/'work/envelope-final-ctest.log','release-ctest.log'),(synth/'work/envelope-sanitize-ctest.log','sanitize-ctest.log'),(synth/'work/envelope-pluginval.log','pluginval.log')]:shutil.copyfile(src,a.output/name)
base=read(work/'step4/before.json');changed=[n for n,h in base.items() if not Path(n).exists() or digest(Path(n))!=h]
preserved_inputs={n:h for n,h in base.items() if not n.startswith(str(root)+'/') and not n.startswith(str(synth)+'/') and n!='/home/dragos/.vst3/SIDSynth.vst3/Contents/x86_64-linux/SIDSynth.so'}
assert all(digest(Path(n))==h for n,h in preserved_inputs.items())
old=synth/'work/envelope-installed-0.5.1-backup/Contents/x86_64-linux/SIDSynth.so';assert digest(old)==base['/home/dragos/.vst3/SIDSynth.vst3/Contents/x86_64-linux/SIDSynth.so']
preservation={'baseline_files':len(base),'preserved_inputs_and_normal_preferences':preserved_inputs,'changed_authorized_project_files':changed,'prior_installed_module_preserved_in_backup':digest(old)}
(a.output/'preservation.json').write_text(json.dumps(preservation,indent=2)+'\n')
full=read(work/'step4/percussion-final-full.json');b256=read(work/'step4/percussion-final-256-clean.json');report=read(work/'alibi-envelope-corrected.report.json')
assert not full['large_peak_deviations'] and not b256['large_peak_deviations']
assert digest(work/'alibi-envelope-corrected.xrns')==digest(work/'alibi-envelope-repro.xrns')
summary={'milestone':4,'converter_version':'0.3.0','sidsynth_version':'0.6.0','saved_schema':4,'stable_original_parameters':67,'appended_metadata_parameters':13,'corrected_song':str(work/'alibi-envelope-corrected.xrns'),'corrected_song_sha256':digest(work/'alibi-envelope-corrected.xrns'),'repeat_export_identical':True,'note_cells':report['note_cells'],'envelope_cues':report['envelope_cues'],'automated':{'python_tests':39,'release_ctest':'1/1 pass, 18.00 s','asan_ubsan_leak_ctest':'1/1 pass, 195.16 s','pluginval':'strictness 10 pass, 44100/48000/96000 Hz; blocks 1/64/257/1024','callback_guard':'Source mode: zero C++/C allocations, frees and pthread mutex locks','proxy_vs_direct':'Source cues enabled: sample-identical at 128/1024 callbacks; monotonic ENV3 observations','source_model':read(work/'step4/model-oracle-final.json')},'actual_renoise':{'full_1024':read(work/'step4/final-1024-check.json'),'excerpt_256':read(work/'step4/final-256-clean-check.json'),'percussion_peaks_full':len(full['events']),'full_peak_absolute_error_max_ms':max(abs(r['peak_difference_ms']) for r in full['events']),'full_large_peak_deviations':0,'excerpt_peaks_per_buffer':len(b256['events']),'buffer_comparison':read(work/'step4/buffer-comparison.json'),'deleted_voice':read(work/'step4/deleted-voice-check.json'),'product':products,'legacy_live_migration':'Cue mode off and all 12 cue words zero'},'listening':{'who':'user','result':'Timing sounds fixed','window_seconds':[59.75,65.75],'scope':'Initial audible correction, before packet safeguards. Final full-song subjective fidelity remains unassessed.'},'installed':read(synth/'work/envelope-install-result.json'),'private_hosts_normally_closed':[92753,93824,94571,96744,97907,99434,101631,102356],'source_lock':digest(root/'docs/source-lock.json'),'runtime_lock_v4':digest(root/'docs/runtime-lock-v4.json'),'diagnostic_correction':'ENV3 timestamps now accumulate 256-sample engine chunks; old preliminary large-buffer envelope reports are superseded, audio unaffected. Regression checks source-enabled 128/1024 callbacks.','runner_correction':'Interrupted take retained; clean 256 repeat uses explicit start_at SongPos(1,1), avoiding restart at a later selected pattern.','limits':['Native control quantization and oscillator/noise phase remain; host-buffer audio is not sample-identical.','Canonical 48000-sample silent warm-up plus final init registers; not full C64 power-on/init emulation.','Other capture/representation reductions remain reported; no inferred ending or loop trimming.'],'next':'Agree user-facing capture duration/end-boundary policy, then broaden representative-song listening.'}
(a.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(a.output/'summary.json')
