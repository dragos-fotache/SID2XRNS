# SPDX-License-Identifier: AGPL-3.0-only
import argparse
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description='Optional independent SID/XRNS comparison tools')
    from . import __version__
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('reference')
    p.add_argument('sid', type=Path); p.add_argument('-o', '--output', type=Path, required=True)
    p.add_argument('--play-calls', type=int, required=True)
    p.add_argument('--model', choices=('6581', '8580')); p.add_argument('--subsong', type=int)
    p = sub.add_parser('audio')
    p.add_argument('reference', type=Path); p.add_argument('result', type=Path)
    p.add_argument('-o', '--output', type=Path, required=True)
    p.add_argument('--max-lag', type=float, default=1)
    p.add_argument('--seconds', type=float)
    p = sub.add_parser('writes')
    p.add_argument('reference', type=Path); p.add_argument('capture', type=Path)
    p.add_argument('-o', '--output', type=Path, required=True)
    p = sub.add_parser('target')
    p.add_argument('metadata', type=Path); p.add_argument('reference', type=Path)
    p.add_argument('-o', '--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'reference':
            from .reference import render
            render(args.sid, args.output, args.play_calls, args.model, args.subsong)
        elif args.command == 'audio':
            from .audio import compare_files
            compare_files(args.reference, args.result, args.output, args.max_lag, args.seconds)
        elif args.command == 'writes':
            from .writes import compare_capture
            compare_capture(args.reference, args.capture, args.output)
        else:
            from .target import analyze_target
            analyze_target(args.metadata, args.reference, args.output)
    except (ValueError, OSError, TimeoutError) as exc:
        parser.exit(2, str(exc) + '\n')
    return 0
