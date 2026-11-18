# SPDX-License-Identifier: AGPL-3.0-only
"""Original tiny 6502 programs with known register and subsong behavior."""
import struct


def psid(init=b'\x60', play=b'\x60', *, songs=1, default=1, flags=0x24, speed=0,
         version=2, embedded_load=True, magic=b'PSID', second=0, third=0):
    header = bytearray(118 if version == 1 else 124)
    header[:4] = magic
    init_address, play_address = 0x1000, 0x1000 + len(init)
    struct.pack_into('>7H', header, 4, version, len(header), 0 if embedded_load else 0x1000,
                     init_address, play_address, songs, default)
    struct.pack_into('>I', header, 18, speed)
    header[22:22 + 17] = b'SID2XRNS fixture\0'
    if version > 1:
        struct.pack_into('>H', header, 118, flags); header[122], header[123] = second, third
    return bytes(header) + (b'\x00\x10' if embedded_load else b'') + init + play


def store(address, value): return bytes([0xa9, value, 0x8d, address & 255, address >> 8])


def performance_sid():
    # Init uses A to select a different initial cutoff for each subsong.
    init = b'\x8d\x16\xd4' + store(0xd418, 15) + store(0xd406, 0xcf)
    init += store(0xd40d, 0xcf) + store(0xd414, 0xcf) + store(0x00f0, 0) + b'\x60'
    init = init[:-1] + store(0xd40a, 8) + b'\x60'
    # A tiny assembler: branch on the persistent invocation counter.
    code = bytearray(b'\xee\xf0\x00\xad\xf0\x00')
    branches = []
    for call in range(1, 6):
        code.extend([0xc9, call, 0xf0, 0]); branches.append((call, len(code) - 1))
    code.append(0x60)
    actions = {
        1: store(0xd400, 0x45) + store(0xd401, 0x1d) + store(0xd404, 0x21)
           + store(0xd407, 0x46) + store(0xd408, 0x0e) + store(0xd40b, 0x41),
        2: store(0xd404, 0x20) + store(0xd40e, 0x33) + store(0xd40f, 0x25) + store(0xd412, 0x11),
        3: store(0xd400, 0x08) + store(0xd401, 0x27),  # Retune releasing voice.
        4: store(0xd402, 0x34) + store(0xd403, 0x0a) + store(0xd416, 0x87),
        5: store(0xd412, 0x10),  # Voice 2 remains held across patterns.
    }
    # Use absolute JMP dispatch targets so action lengths have no branch range issue.
    for call, operand in branches:
        offset = len(code) - (operand + 1)
        assert offset < 128
        code[operand] = offset
        code.extend(actions[call] + b'\x60')
    return psid(init, bytes(code), songs=2)
