#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Check or reproduce the pinned, namespaced five-module local-source subset."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True, help='Already available checkout/archive extraction; no network is used')
    p.add_argument('--write', action='store_true', help='Restore the same pinned module contents after validating source hashes')
    a = p.parse_args()
    manifest = json.loads((ROOT / 'third_party/chiptunesak/manifest.json').read_text())
    for name, hashes in manifest['files'].items():
        upstream = (a.source / 'chiptunesak' / name).read_bytes()
        if hashlib.sha256(upstream).hexdigest() != hashes['upstream_sha256']:
            raise SystemExit(f'Upstream source hash mismatch: {name}')
        adapted = upstream.replace(b'from chiptunesak import ', b'from . import ').replace(b'from chiptunesak.', b'from .')
        if hashlib.sha256(adapted).hexdigest() != hashes['vendored_sha256']:
            raise SystemExit(f'Adaptation hash mismatch: {name}')
        destination = ROOT / 'sid2xrns/_vendor/chiptunesak' / name
        if a.write: destination.write_bytes(adapted)
        elif destination.read_bytes() != adapted: raise SystemExit(f'Vendored file mismatch: {name}')
    if (a.source / 'LICENSE').read_bytes() != (ROOT / 'third_party/chiptunesak/LICENSE').read_bytes():
        raise SystemExit('Pinned source license differs from retained license')
    print(f'Verified {len(manifest["files"])} ChiptuneSAK files at {manifest["commit"]}; import namespace only')


if __name__ == '__main__': main()
