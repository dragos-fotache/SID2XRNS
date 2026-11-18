# SPDX-License-Identifier: AGPL-3.0-only
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from . import __version__
from .errors import ConversionError
from .hvsc import lookup_song_lengths, play_calls_for_duration
from .psid import read
from .storage import atomic_file, preflight


def capture_input(args, output):
    from .capture import capture

    sid = read(args.sid, hvsc_digest=args.hvsc_db is not None)
    profile = sid.profile(args.subsong, args.clock, args.model)
    if args.hvsc_db is None:
        return capture(sid, profile, args.play_calls, output)

    lengths = lookup_song_lengths(args.hvsc_db, sid.hvsc_md5)
    if lengths is None:
        raise ConversionError('hvsc-tune-not-found', 'SID file is absent from Songlengths.md5. Use --play-calls to set the window.',
                              sid_md5=sid.hvsc_md5)
    subsong = profile['subsong']
    if subsong > len(lengths) or lengths[subsong - 1] == 0:
        raise ConversionError('hvsc-duration-not-found', 'HVSC has no positive duration for this subsong. Use --play-calls to set the window.',
                              sid_md5=sid.hvsc_md5, subsong=subsong)
    duration = lengths[subsong - 1]
    return capture(sid, profile, play_calls_for_duration(duration, profile), output,
                   hvsc={'sid_md5': sid.hvsc_md5, 'duration_ms': duration})


def main(argv=None):
    parser = argparse.ArgumentParser(prog='sid2xrns', description='Offline bounded PSID capture and editable native Renoise export')
    parser.add_argument('--version', action='version', version=__version__)
    commands = parser.add_subparsers(dest='command', required=True)
    hvsc_db_options = {
        'type': Path, 'nargs': '?', 'const': Path('Songlengths.md5'), 'metavar': 'PATH',
        'help': 'Use an HVSC database (bare flag uses Songlengths.md5 in the current directory)',
    }
    info = commands.add_parser('inspect', help='Read SID metadata without execution')
    info.add_argument('sid', type=Path)
    info.add_argument('--hvsc-db', **hvsc_db_options)
    for name, description in (
        ('capture', 'Run a SID tune and save a trace of its timestamped register writes'),
        ('convert', 'Run a SID tune and export it as an editable Renoise XRNS song'),
    ):
        command = commands.add_parser(name, help=description, description=description)
        command.add_argument('sid', type=Path)
        window = command.add_mutually_exclusive_group(required=True)
        window.add_argument('--play-calls', type=int, help='Set the capture window in whole play calls')
        window.add_argument('--hvsc-db', **hvsc_db_options)
        command.add_argument('--subsong', type=int)
        command.add_argument('--clock', choices=('pal', 'ntsc'))
        command.add_argument('--model', choices=('6581', '8580'))
        command.add_argument('--force', action='store_true')
    commands.choices['capture'].add_argument('-o', '--output', type=Path, required=True, help='Trace output path')
    convert = commands.choices['convert']
    convert.add_argument('-o', '--output', type=Path,
                         help='XRNS output path (defaults to the SID filename with .xrns in the current directory)')
    export = commands.add_parser('export', help='Interpret a completed capture and write XRNS')
    export.add_argument('trace', type=Path)
    export.add_argument('-o', '--output', type=Path, required=True)
    export.add_argument('--force', action='store_true')
    for command in (convert, export):
        command.add_argument('--report', type=Path)
        command.add_argument('--gain-db', type=float, default=-12)
        command.add_argument('--strict', action='store_true', help='Reject reported reductions and sub-333us control timing risks')
        command.add_argument('--envelope-timing', choices=('source', 'legacy'), default='source',
                             help='Source timing requires SIDSynth 0.6.0; legacy keeps schema-3 ADSR behavior')
        command.add_argument('--diagnostic', action='store_true', help=argparse.SUPPRESS)
    convert.add_argument('--trace', type=Path, help='Retained ordered capture; defaults beside the XRNS')
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'linux': raise ConversionError('unsupported-platform', 'This initial tool supports Linux only')
        from .xrns import verify_assets
        verify_assets()
        if args.command == 'inspect':
            sid = read(args.sid, hvsc_digest=args.hvsc_db is not None)
            result = sid.info()
            try: result['default_execution_profile'] = sid.profile()
            except ConversionError as exc: result['default_execution_error'] = exc.as_dict()
            if args.hvsc_db is not None:
                result['hvsc'] = {'sid_md5': sid.hvsc_md5,
                                  'song_lengths_ms': lookup_song_lengths(args.hvsc_db, sid.hvsc_md5)}
            print(json.dumps(result, indent=2)); return 0
        if args.command in ('capture', 'convert'):
            protected = [args.sid]
            if args.hvsc_db is not None:
                protected.append(args.hvsc_db)
        if args.command == 'capture':
            preflight([args.output], protected, args.force)
            result = capture_input(args, args.output)
            summary = {'trace': str(args.output), **result['footer']}
            if 'hvsc' in result['header']:
                summary['hvsc'] = result['header']['hvsc']
            print(json.dumps(summary, indent=2)); return 0
        if not math.isfinite(args.gain_db) or not -60 <= args.gain_db <= 0:
            raise ConversionError('invalid-gain', 'Output gain must be finite and between -60 and 0 dB')
        if args.command == 'convert' and args.output is None:
            args.output = Path(args.sid.name).with_suffix('.xrns')
        report_file = args.report or args.output.with_suffix('.report.json')
        if args.command == 'convert':
            trace_file = args.trace or args.output.with_suffix('.capture.jsonl.gz')
            preflight([args.output, report_file, trace_file], protected, args.force)
            capture_input(args, trace_file)
        else:
            trace_file = args.trace
            preflight([args.output, report_file], [trace_file], args.force)
        from .trace import read_trace
        from .interpret import interpret
        from .xrns import write_song
        trace = read_trace(trace_file); performance = interpret(trace, round(args.gain_db, 1))
        if args.envelope_timing == 'source':
            from .envelope_cues import add_envelope_cues
            performance = add_envelope_cues(performance, trace)
        report = {'tool_version': __version__, **performance.report,
                  'trace': str(trace_file), 'trace_sha256': hashlib.sha256(trace_file.read_bytes()).hexdigest(),
                  'output': str(args.output)}
        if args.strict and (performance.report['issues'] or performance.report['controls_closer_than_measured_333us']):
            report['exported'] = False
            with atomic_file(report_file) as temp: temp.write_text(json.dumps(report, indent=2) + '\n')
            raise ConversionError('lossy-interpretation', 'Strict export rejected reported reductions; capture/report retained', report=str(report_file))
        report.update(write_song(performance, args.output, args.diagnostic)); report['exported'] = True
        report['xrns_sha256'] = hashlib.sha256(args.output.read_bytes()).hexdigest()
        with atomic_file(report_file) as temp: temp.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'output': str(args.output), 'trace': str(trace_file), 'report': str(report_file),
                          'patterns': report['patterns'], 'notes_on': report['notes_on'], 'issues': report['issues'],
                          'controls_closer_than_measured_333us': report['controls_closer_than_measured_333us']}, indent=2))
        return 0
    except ConversionError as exc:
        print(json.dumps({'error': exc.as_dict()}), file=sys.stderr); return 2
    except (OSError, ValueError, KeyError, IndexError) as exc:
        print(json.dumps({'error': {'code': 'input-output-error', 'message': str(exc)}}), file=sys.stderr); return 2


if __name__ == '__main__': raise SystemExit(main())
