# SPDX-License-Identifier: AGPL-3.0-only
import argparse
from contextlib import ExitStack
import hashlib
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from . import __version__
from .errors import ConversionError
from .hvsc import lookup_song_lengths, play_calls_for_duration
from .psid import read
from .storage import atomic_file, preflight

DEFAULT_HVSC_DB = Path('Songlengths.md5')


def capture_input(args, output):
    from .capture import capture

    sid = read(args.sid, hvsc_digest=args.hvsc_db is not None)
    profile = sid.profile(args.subsong, args.clock, args.model)
    if args.hvsc_db is None:
        return capture(sid, profile, args.play_calls, output)

    try:
        lengths = lookup_song_lengths(args.hvsc_db, sid.hvsc_md5)
    except FileNotFoundError as exc:
        raise ConversionError('hvsc-database-not-found',
                              f'Cannot find {args.hvsc_db}. Use --hvsc-db PATH or --play-calls to set the window.',
                              database=str(args.hvsc_db)) from exc
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


def export_trace(args, trace_file, retained_trace, report_file):
    from .interpret import interpret
    from .trace import read_trace
    from .xrns import write_song

    trace = read_trace(trace_file)
    performance = interpret(trace, round(args.gain_db, 1))
    if args.envelope_timing == 'source':
        from .envelope_cues import add_envelope_cues
        performance = add_envelope_cues(performance, trace)

    paths = {'output': str(args.output), 'trace': str(retained_trace) if retained_trace is not None else None,
             'report': str(report_file) if report_file is not None else None}
    diagnostics = {key: performance.report[key] for key in ('issues', 'controls_closer_than_measured_333us')}
    rejected = args.strict and any(diagnostics.values())
    result = {} if rejected else write_song(performance, args.output, args.diagnostic)
    if report_file is not None:
        report = {'tool_version': __version__, **performance.report, **result,
                  'trace': paths['trace'], 'trace_sha256': hashlib.sha256(trace_file.read_bytes()).hexdigest(),
                  'output': paths['output'], 'exported': not rejected}
        if not rejected:
            report['xrns_sha256'] = hashlib.sha256(args.output.read_bytes()).hexdigest()
        with atomic_file(report_file) as temp:
            temp.write_text(json.dumps(report, indent=2) + '\n')
    if rejected:
        raise ConversionError('lossy-interpretation', 'Strict export rejected reported reductions',
                              trace=paths['trace'], report=paths['report'], **diagnostics)

    print(json.dumps({**paths, 'patterns': result['patterns'],
                      'notes_on': performance.report['notes_on'], **diagnostics}, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog='sid2xrns', description='Offline bounded PSID capture and editable native Renoise export')
    parser.add_argument('--version', action='version', version=__version__)
    commands = parser.add_subparsers(dest='command', required=True)
    hvsc_db_options = {
        'type': Path, 'nargs': '?', 'const': DEFAULT_HVSC_DB, 'metavar': 'PATH',
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
        window = command.add_mutually_exclusive_group(required=name == 'capture')
        window.add_argument('--play-calls', type=int, help='Set the capture window in whole play calls')
        window.add_argument('--hvsc-db', **hvsc_db_options)
        command.add_argument('--subsong', type=int)
        command.add_argument('--clock', choices=('pal', 'ntsc'))
        command.add_argument('--model', choices=('6581', '8580'))
        command.add_argument('--force', action='store_true')
    commands.choices['capture'].add_argument('-o', '--output', type=Path, required=True, help='Trace output path')
    convert = commands.choices['convert']
    convert.epilog = 'Without a window option, convert uses Songlengths.md5 in the current directory.'
    convert.add_argument('-o', '--output', type=Path,
                         help='XRNS output path (defaults to the SID filename with .xrns in the current directory)')
    export = commands.add_parser('export', help='Interpret a completed capture and write XRNS')
    export.add_argument('trace', type=Path)
    export.add_argument('-o', '--output', type=Path, required=True)
    export.add_argument('--force', action='store_true')
    convert.add_argument('--report', type=Path, help='Save a JSON conversion report at this path')
    export.add_argument('--report', type=Path, help='JSON report path (defaults beside the XRNS)')
    for command in (convert, export):
        command.add_argument('--gain-db', type=float, default=0,
                             help='Set SIDSynth Output in dB (default %(default)s)')
        command.add_argument('--strict', action='store_true', help='Reject reported reductions and sub-333us control timing risks')
        command.add_argument('--envelope-timing', choices=('source', 'legacy'), default='source',
                             help='Source timing requires SIDSynth 0.6.0; legacy keeps schema-3 ADSR behavior')
        command.add_argument('--diagnostic', action='store_true', help=argparse.SUPPRESS)
    convert.add_argument('--trace', type=Path, help='Save the ordered capture at this path')
    args = parser.parse_args(argv)
    if args.command == 'convert' and args.hvsc_db is None and args.play_calls is None:
        args.hvsc_db = DEFAULT_HVSC_DB
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
        if args.command == 'convert':
            if args.output is None:
                args.output = Path(args.sid.name).with_suffix('.xrns')
            outputs = [path for path in (args.output, args.trace, args.report) if path is not None]
            preflight(outputs, protected, args.force)
            with ExitStack() as stack:
                trace_file = args.trace
                if trace_file is None:
                    temp = stack.enter_context(TemporaryDirectory(prefix='sid2xrns-'))
                    trace_file = Path(temp) / 'capture.jsonl.gz'
                capture_input(args, trace_file)
                return export_trace(args, trace_file, args.trace, args.report)

        report_file = args.report or args.output.with_suffix('.report.json')
        preflight([args.output, report_file], [args.trace], args.force)
        return export_trace(args, args.trace, args.trace, report_file)
    except ConversionError as exc:
        print(json.dumps({'error': exc.as_dict()}), file=sys.stderr); return 2
    except (OSError, ValueError, KeyError, IndexError) as exc:
        print(json.dumps({'error': {'code': 'input-output-error', 'message': str(exc)}}), file=sys.stderr); return 2


if __name__ == '__main__': raise SystemExit(main())
