# SPDX-License-Identifier: AGPL-3.0-only
"""PSID header parsing and an explicit, conservative execution profile."""
from dataclasses import asdict, dataclass, field
import hashlib
from pathlib import Path
import struct
from typing import Optional

from .errors import ConversionError


@dataclass
class SidFile:
    version: int
    load_address: int
    init_address: int
    play_address: int
    songs: int
    start_song: int
    speed: int
    flags: int
    title: str
    author: str
    released: str
    magic: str
    second_sid: int
    third_sid: int
    sha256: str
    payload: bytes = field(repr=False)
    hvsc_md5: Optional[str] = field(default=None, repr=False)

    def info(self):
        result = asdict(self)
        result.pop('payload')
        result.pop('hvsc_md5')
        result['payload_bytes'] = len(self.payload)
        result['clock_hint'] = {0: 'unknown', 1: 'pal', 2: 'ntsc', 3: 'either'}[(self.flags >> 2) & 3]
        result['model_hint'] = {0: 'unknown', 1: '6581', 2: '8580', 3: 'either'}[(self.flags >> 4) & 3]
        return result

    def profile(self, subsong=None, clock=None, model=None):
        song = self.start_song if subsong is None else subsong
        def require(condition, code, message):
            if not condition: raise ConversionError(code, message)
        require(self.magic == 'PSID', 'unsupported-rsid', 'RSID requires a full C64 execution environment')
        require(1 <= song <= self.songs, 'invalid-subsong', f'Subsong must be between 1 and {self.songs}')
        require(not self.second_sid and not self.third_sid, 'unsupported-multiple-sids', 'Only one SID is supported')
        require(not self.flags & 1, 'unsupported-mus', 'MUS data requires a separate player')
        require(not self.flags & 2, 'unsupported-playsid-specific', 'PlaySID-specific execution is not supported')
        require(self.flags & ~0x3ff == 0, 'unsupported-flags', 'Reserved PSID flags are set')
        speed_bit = (song - 1) % 32 if self.version == 1 else min(song - 1, 31)
        require(not self.speed & (1 << speed_bit), 'unsupported-cia-timing', 'Initial capture supports VBI-timed play calls only')
        require(self.play_address != 0, 'unsupported-interrupt-player', 'A nonzero directly callable play address is required')
        clock = clock or {1: 'pal', 2: 'ntsc'}.get((self.flags >> 2) & 3)
        model = model or {1: '6581', 2: '8580'}.get((self.flags >> 4) & 3)
        require(clock in ('pal', 'ntsc'), 'ambiguous-clock', 'Specify --clock pal or --clock ntsc for this header')
        require(model in ('6581', '8580'), 'ambiguous-model', 'Specify --model 6581 or --model 8580 for this header')
        return {'name': 'psid-direct-vbi-v2', 'subsong': song, 'clock': clock, 'model': model,
                'clock_hz': 985248 if clock == 'pal' else 1022727,
                'target_clock_hz': 985248 if clock == 'pal' else 1022730,
                'cycles_per_call': 63 * 312 if clock == 'pal' else 65 * 263,
                'timing_model': 'instruction-end cycles; fixed VBI calls; SID write-only bus decay; no IRQ/VIC/DMA/CIA/OSC3/ENV3/paddle emulation'}


def parse(data):
    def invalid(message): raise ConversionError('invalid-sid', message)
    if len(data) < 118 or data[:4] not in (b'PSID', b'RSID'):
        invalid('Expected a complete PSID/RSID header')
    version, offset, load, init, play, songs, start = struct.unpack_from('>7H', data, 4)
    if version not in (1, 2, 3, 4): invalid('Unsupported SID header version')
    required = 118 if version == 1 else 124
    if offset != required or len(data) <= offset: invalid('Invalid header length or missing payload')
    if not 1 <= songs <= 256 or not 1 <= start <= songs: invalid('Invalid subsong count/default')
    speed = struct.unpack_from('>I', data, 18)[0]
    flags = struct.unpack_from('>H', data, 118)[0] if version > 1 else 0
    payload = data[offset:]
    if not load:
        if len(payload) < 3: invalid('Missing little-endian load address or program data')
        load = int.from_bytes(payload[:2], 'little'); payload = payload[2:]
    if load < 0x0200 or not payload or load + len(payload) > 65536:
        invalid('Payload must fit in RAM above the CPU stack')
    def text(a): return data[a:a + 32].split(b'\0', 1)[0].decode('cp1252', errors='replace')
    return SidFile(version, load, init or load, play, songs, start, speed, flags,
                   text(22), text(54), text(86), data[:4].decode('ascii'),
                   data[122] if version > 1 else 0, data[123] if version > 1 else 0,
                   hashlib.sha256(data).hexdigest(), payload)


def read(path, *, hvsc_digest=False):
    path = Path(path)
    if path.stat().st_size > 65536 + 126:
        raise ConversionError('invalid-sid', 'SID file is larger than the supported RAM image')
    data = path.read_bytes()
    sid = parse(data)
    if hvsc_digest:
        sid.hvsc_md5 = hashlib.md5(data).hexdigest()
    return sid
