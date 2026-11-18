# SPDX-License-Identifier: AGPL-3.0-only
"""Bounded global alignment and local audio measures, without time warping."""
import importlib.metadata
import json
import os
from pathlib import Path
import numpy as np
from scipy import signal
from scipy.io import wavfile
from .reference import digest


def verify_analysis_lock():
    lock = json.loads((Path(__file__).resolve().parents[1] / 'docs/reference-lock.json').read_text())
    for package, expected in lock['analysis_packages'].items():
        if importlib.metadata.version(package) != expected:
            raise ValueError(f'Analysis package lock mismatch: {package}; review before re-pinning')


def read_audio(path):
    rate, audio = wavfile.read(path)
    if np.issubdtype(audio.dtype, np.integer):
        info = np.iinfo(audio.dtype)
        if audio.dtype == np.uint8:
            audio = (audio.astype(np.float64) - 128) / 128
        else:
            audio = audio.astype(np.float64) / max(abs(info.min), info.max)
    else:
        audio = audio.astype(np.float64)
    if audio.ndim not in (1, 2) or not len(audio) or not np.isfinite(audio).all():
        raise ValueError('Audio must be finite, nonempty mono or multichannel PCM')
    metadata = {'rate': rate, 'frames': len(audio), 'channels': 1 if audio.ndim == 1 else audio.shape[1],
                'peak': float(np.max(np.abs(audio))), 'stereo_equal': bool(audio.ndim == 2 and
                audio.shape[1] == 2 and np.array_equal(audio[:, 0], audio[:, 1]))}
    return rate, audio.mean(axis=1) if audio.ndim == 2 else audio, metadata


def rms(x):
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0


def envelope(audio, rate):
    hop = max(1, round(rate / 1000))
    n = len(audio) // hop
    return np.sqrt(np.mean(audio[:n * hop].reshape(n, hop) ** 2, axis=1)), hop


def lag_samples(reference, result, rate, maximum):
    if not np.isfinite(maximum) or not 0 <= maximum <= 5:
        raise ValueError('Alignment bound must be finite and between 0 and 5 seconds')
    a, hop = envelope(reference, rate); b, _ = envelope(result, rate)
    # Envelope differences emphasize attacks and changing sound instead of DC
    # or oscillator phase. One fixed offset is used for the entire recording.
    a = np.diff(a, prepend=a[0]); b = np.diff(b, prepend=b[0])
    if np.linalg.norm(a) < 1e-12 or np.linalg.norm(b) < 1e-12:
        raise ValueError('Insufficient changing audio for a reliable alignment')
    corr = signal.correlate(b, a, method='fft')
    lags = signal.correlation_lags(len(b), len(a))
    mask = np.abs(lags) <= round(maximum * rate / hop)
    positions = np.flatnonzero(mask)
    chosen = positions[np.argmax(corr[mask])]
    score = float(corr[chosen] / (np.linalg.norm(a) * np.linalg.norm(b)))
    return int(lags[chosen] * hop), score, hop


def spectral_distance(a, b):
    _, _, sa = signal.stft(a, nperseg=1024, noverlap=768, boundary=None)
    _, _, sb = signal.stft(b, nperseg=1024, noverlap=768, boundary=None)
    ma, mb = np.abs(sa), np.abs(sb)
    distance = float(np.linalg.norm(ma - mb) / max(np.linalg.norm(ma), 1e-12))
    # This is a level-normalized magnitude measure, not perceptual equivalence.
    return distance


def compare_arrays(reference, result, rate, maximum=1, seconds=None):
    if rate < 8000 or not np.isfinite(reference).all() or not np.isfinite(result).all():
        raise ValueError('Invalid audio sample rate or nonfinite data')
    if seconds is not None and (not np.isfinite(seconds) or seconds <= 0):
        raise ValueError('Comparison duration must be positive and finite')
    requested = min(len(reference), round(seconds * rate)) if seconds else len(reference)
    offset, score, hop = lag_samples(reference[:requested], result[:requested + round(maximum * rate)], rate, maximum)
    ref_start, out_start = max(0, -offset), max(0, offset)
    count = min(requested - ref_start, len(result) - out_start)
    if count < rate / 2:
        raise ValueError('Less than half a second of aligned audio is available')
    a = reference[ref_start:ref_start + count]; b = result[out_start:out_start + count]
    ra, rb = rms(a), rms(b)
    if min(ra, rb) < 1e-9:
        raise ValueError('Silent audio cannot establish a fidelity comparison')
    gain = ra / rb
    rows = []; window = rate // 2
    for first in range(0, count - window + 1, window):
        x, y = a[first:first + window], b[first:first + window]
        rows.append({'seconds': (ref_start + first) / rate, 'duration': window / rate,
                     'reference_rms': rms(x), 'result_rms': rms(y),
                     'level_matched_nrmse': rms(x - y * gain) / max(rms(x), 1e-9),
                     'spectral_distance': spectral_distance(x, y * gain)})
    # Independent local offsets are diagnostics only; never applied to audio.
    local = []
    span = min(4 * rate, max(rate, count // 4))
    for first in sorted(set((0, max(0, count // 2 - span // 2), max(0, count - span)))):
        x, y = a[first:first + span], b[first:first + span]
        try:
            lag, confidence, _ = lag_samples(x, y, rate, .1)
            local.append({'seconds': (ref_start + first) / rate, 'residual_lag_ms': lag * 1000 / rate,
                          'envelope_correlation': confidence})
        except ValueError:
            local.append({'seconds': (ref_start + first) / rate, 'residual_lag_ms': None,
                          'reason': 'insufficient changing audio'})
    report = {'schema': 1, 'alignment': {'result_offset_samples': offset, 'result_offset_seconds': offset / rate,
              'bound_seconds': maximum, 'envelope_hop_samples': hop, 'envelope_correlation': score,
              'method': 'one bounded global RMS-envelope-difference correlation; no time warping',
              'local_offsets_diagnostic_only': local},
              'coverage': {'reference_requested_seconds': requested / rate, 'compared_seconds': count / rate,
                           'reference_start_seconds': ref_start / rate, 'fraction': count / requested},
              'levels': {'reference_rms': ra, 'result_rms': rb, 'result_minus_reference_db': float(20 * np.log10(rb / ra)),
                         'result_rms_match_multiplier': gain},
              'raw_nrmse': rms(a - b) / ra, 'level_matched_nrmse': rms(a - b * gain) / ra,
              'waveform_correlation': float(np.corrcoef(a, b)[0, 1]), 'windows': rows,
              'worst_windows': sorted(rows, key=lambda r: r['spectral_distance'], reverse=True)[:8],
              'assessment': 'Measurements only; reSID/reSIDfp phase, filter and startup differences confound residuals. Listening required.'}
    return report, a, b


def compare_files(reference, result, output, maximum=1, seconds=None):
    verify_analysis_lock()
    rate, a, am = read_audio(reference); rate_b, b, bm = read_audio(result)
    if rate != rate_b:
        raise ValueError('Sample rates must match; no implicit resampling')
    report, a, b = compare_arrays(a, b, rate, maximum, seconds)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    report['inputs'] = {'reference': str(Path(reference).resolve()), 'reference_sha256': digest(reference),
                        'result': str(Path(result).resolve()), 'result_sha256': digest(result),
                        'reference_audio': am, 'result_audio': bm}
    report['analysis_packages'] = {p: importlib.metadata.version(p) for p in ('numpy', 'scipy', 'matplotlib')}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    gain = report['levels']['result_rms_match_multiplier']
    os.environ.setdefault('MPLCONFIGDIR', str(output.parent.resolve() / '.matplotlib-cache'))
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), constrained_layout=True)
    axes[0].plot([r['seconds'] for r in report['windows']], [r['spectral_distance'] for r in report['windows']])
    axes[0].set(ylabel='Magnitude distance', title='Independent SID reference vs actual XRNS playback')
    axes[1].plot([r['seconds'] for r in report['windows']], [r['level_matched_nrmse'] for r in report['windows']])
    axes[1].set(xlabel='Source window time (seconds)', ylabel='Waveform NRMSE')
    fig.savefig(output / 'errors.png', dpi=140); plt.close(fig)
    # First passage plus three non-overlapping worst passages, common gain and
    # headroom across A/B/difference. Retain raw level figures in the report.
    centers = [min(3, len(a) / rate / 2)]
    for row in report['worst_windows']:
        center = row['seconds'] - report['coverage']['reference_start_seconds'] + .25
        if all(abs(center - c) >= 5 for c in centers): centers.append(center)
        if len(centers) == 4: break
    clips = []
    for i, center in enumerate(centers):
        lo = max(0, round((center - 3) * rate)); hi = min(len(a), lo + 6 * rate)
        x, y = a[lo:hi], b[lo:hi] * gain
        scale = min(1., .9 / max(float(np.max(np.abs(x))), float(np.max(np.abs(y))),
                                float(np.max(np.abs(x - y))), 1e-12))
        for label, audio in [('reference', x), ('result-level-matched', y), ('difference', x - y)]:
            wavfile.write(output / f'clip-{i + 1}-{label}.wav', rate, (audio * scale).astype(np.float32))
        clips.append({'clip': i + 1, 'source_seconds': lo / rate + report['coverage']['reference_start_seconds'],
                      'duration': len(x) / rate, 'shared_headroom_multiplier': scale})
        fig, axes = plt.subplots(2, 1, figsize=(10, 5), constrained_layout=True)
        for axis, audio, label in zip(axes, (x, y), ('Independent VICE reSID', 'Renoise SIDSynth (level matched)')):
            axis.specgram(audio, NFFT=1024, Fs=rate, noverlap=768, cmap='magma', vmin=-110, vmax=-35)
            axis.set(ylim=(0, 10000), ylabel='Hz', title=label)
        axes[-1].set_xlabel(f'Seconds from source {clips[-1]["source_seconds"]:.3f} s')
        fig.savefig(output / f'clip-{i + 1}-spectrogram.png', dpi=140); plt.close(fig)
    report['clips'] = clips
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('coverage', 'levels', 'worst_windows')}, indent=2), flush=True)
    return report
