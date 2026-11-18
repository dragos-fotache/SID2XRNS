# SPDX-License-Identifier: AGPL-3.0-only
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from . import __version__
from .errors import ConversionError
from .psid import read
from .storage import atomic_file, preflight


def main(argv=None):
    parser = argparse.ArgumentParser(prog='sid2xrns', description='Offline bounded PSID capture and editable native Renoise export')
    parser.add_argument('--version', action='version', version=__version__)
    commands = parser.add_subparsers(dest='command', required=True)
    info = commands.add_parser('inspect', help='Read SID metadata without execution')
    info.add_argument('sid', type=Path)
    for name in ('capture', 'convert'):
        command = commands.add_parser(name)
        command.add_argument('sid', type=Path)
        command.add_argument('--play-calls', type=int, required=True, help='Explicit development capture budget; does not infer the intended ending')
        command.add_argument('--subsong', type=int)
        command.add_argument('--clock', choices=('pal', 'ntsc'))
        command.add_argument('--model', choices=('6581', '8580'))
        command.add_argument('-o', '--output', type=Path, required=True)
        command.add_argument('--force', action='store_true')
    export = commands.add_parser('export', help='Interpret a completed capture and write XRNS')
    export.add_argument('trace', type=Path)
    export.add_argument('-o', '--output', type=Path, required=True)
    export.add_argument('--force', action='store_true')
    for command in (commands.choices['convert'], export):
        command.add_argument('--report', type=Path)
        command.add_argument('--gain-db', type=float, default=-12)
        command.add_argument('--strict', action='store_true', help='Reject reported reductions and sub-333us control timing risks')
        command.add_argument('--envelope-timing', choices=('source', 'legacy'), default='source',
                             help='Source timing requires SIDSynth 0.6.0; legacy keeps schema-3 ADSR behavior')
        command.add_argument('--diagnostic', action='store_true', help=argparse.SUPPRESS)
    commands.choices['convert'].add_argument('--trace', type=Path, help='Retained ordered capture; defaults beside the XRNS')
    args = parser.parse_args(argv)
    try:
        if sys.platform != 'linux': raise ConversionError('unsupported-platform', 'This initial tool supports Linux only')
        from .xrns import verify_assets
        verify_assets()
        if args.command == 'inspect':
            sid = read(args.sid); result = sid.info()
            try: result['default_execution_profile'] = sid.profile()
            except ConversionError as exc: result['default_execution_error'] = exc.as_dict()
            print(json.dumps(result, indent=2)); return 0
        from .capture import capture
        if args.command == 'capture':
            preflight([args.output], [args.sid], args.force)
            sid = read(args.sid); profile = sid.profile(args.subsong, args.clock, args.model)
            result = capture(sid, profile, args.play_calls, args.output)
            print(json.dumps({'trace': str(args.output), **result['footer']}, indent=2)); return 0
        if not math.isfinite(args.gain_db) or not -60 <= args.gain_db <= 0:
            raise ConversionError('invalid-gain', 'Output gain must be finite and between -60 and 0 dB')
        report_file = args.report or args.output.with_suffix('.report.json')
        if args.command == 'convert':
            trace_file = args.trace or args.output.with_suffix('.capture.jsonl.gz')
            preflight([args.output, report_file, trace_file], [args.sid], args.force)
            sid = read(args.sid); profile = sid.profile(args.subsong, args.clock, args.model)
            capture(sid, profile, args.play_calls, trace_file)
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
