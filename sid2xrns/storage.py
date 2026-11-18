# SPDX-License-Identifier: AGPL-3.0-only
import contextlib
import gzip
import os
from pathlib import Path
import tempfile
from .errors import ConversionError


def preflight(paths, protected=(), force=False):
    paths = [Path(p).resolve() for p in paths]
    protected = {Path(p).resolve() for p in protected}
    if len(set(paths)) != len(paths) or set(paths) & protected:
        raise ConversionError('output-path-conflict', 'Input and output paths must be distinct')
    for p in paths:
        if not p.parent.is_dir(): raise ConversionError('output-directory-missing', f'Output directory does not exist: {p.parent}')
        if p.exists() and not force: raise ConversionError('output-exists', f'Refusing to overwrite {p}; use --force explicitly')


@contextlib.contextmanager
def atomic_file(path):
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    os.close(fd)
    try:
        yield Path(temp)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


@contextlib.contextmanager
def open_text(path, mode='rt'):
    path = Path(path)
    opener = gzip.open if path.name.endswith('.gz') else open
    with opener(path, mode, encoding='utf-8', newline='\n') as stream: yield stream
