# SPDX-License-Identifier: AGPL-3.0-only
"""The modern HVSC Songlengths.md5 format and its whole-file MD5 keys."""
import re

from .errors import ConversionError

DURATION = re.compile(r'([0-9]+):([0-5][0-9])(?:\.([0-9]{1,3}))?')


def lookup_song_lengths(database, sid_md5):
    """Return the listed durations in subsong order, or None on a miss."""
    with database.open(encoding='utf-8-sig', errors='replace') as stream:
        rows = ((n, line.strip()) for n, line in enumerate(stream, 1))
        records = ((n, line) for n, line in rows if line and not line.startswith(';'))
        _, header = next(records, (0, ''))
        if header.lower() != '[database]':
            raise ConversionError('invalid-hvsc-database', 'Expected a [Database] header in Songlengths.md5')
        for line_number, line in records:
            key, _, lengths = line.partition('=')
            if key.strip().lower() != sid_md5:
                continue
            durations = []
            for token in lengths.split():
                match = DURATION.fullmatch(token)
                if match is None:
                    raise ConversionError('invalid-hvsc-database', 'Invalid song length in the matched HVSC entry',
                                          line=line_number, sid_md5=sid_md5)
                minutes, seconds, fraction = match.groups()
                durations.append((int(minutes) * 60 + int(seconds)) * 1000 + int((fraction or '').ljust(3, '0')))
            return durations
    return None


def play_calls_for_duration(duration_ms, profile):
    scaled_cycles = duration_ms * profile['clock_hz']
    scaled_period = 1000 * profile['cycles_per_call']
    return (scaled_cycles + scaled_period - 1) // scaled_period
