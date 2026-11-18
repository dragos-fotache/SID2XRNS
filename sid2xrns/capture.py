# SPDX-License-Identifier: AGPL-3.0-only
"""Bounded direct-call execution; retain ordered writes before interpretation."""
import gzip
import hashlib
import io
import json
from pathlib import Path
from ._vendor.chiptunesak.thin_c64_emulator import ThinC64Emulator
from .errors import ConversionError
from .sidbus import SidBus
from .storage import atomic_file

MAX_WRITES = 1_000_000
MAX_CALLS = 100_000
MAX_INIT_CYCLES = 1_000_000
MAX_INIT_INSTRUCTIONS = 500_000
MAX_PLAY_INSTRUCTIONS = 250_000


class CaptureCPU(ThinC64Emulator):
    def __init__(self, profile):
        super().__init__('PAL-C64' if profile['clock'] == 'pal' else 'NTSC-C64')
        self.memory[0] = 0x2f
        self.exit_on_empty_stack = True
        self.events = []
        self.registers = [0] * 25
        self.other_io_writes = {}
        self.instructions = 0
        self.cycle_base = 0
        self.sid_bus = SidBus(profile['model'])
        self.sid_bus_reads = {}
        self.set_mem_callback = self.observe

    def get_mem(self, address):
        if ((0xa000 <= address <= 0xbfff and self.see_basic) or
            (address >= 0xe000 and self.see_kernal) or
            (0xd000 <= address <= 0xdfff and self.see_char)):
            raise ConversionError('unsupported-rom-read', f'ROM access at ${address:04X} is outside the direct-call profile', pc=self.pc)
        if 0xd000 <= address <= 0xdfff and self.see_io:
            if 0xd400 <= address <= 0xd7ff and (address & 31) not in (0x19, 0x1a, 0x1b, 0x1c):
                value = self.sid_bus.read(self.cycle_base + self.cpucycles)
                self.sid_bus_reads[address] = self.sid_bus_reads.get(address, 0) + 1
                return value
            code = 'unsupported-sid-read' if 0xd400 <= address <= 0xd7ff else 'unsupported-io-read'
            raise ConversionError(code, f'I/O read at ${address:04X} requires unimplemented hardware behavior', pc=self.pc)
        return super().get_mem(address)

    def observe(self, address, value):
        if address == 0 and value & 7 != 7:
            raise ConversionError('unsupported-cpu-port-direction', 'The direct-call adapter requires CPU-port banking bits to remain outputs')
        if self.see_io and 0xd400 <= address <= 0xd7ff:
            register = (address - 0xd400) % 32
            if register < 25:
                self.sid_bus.write(value, self.cycle_base + self.cpucycles)
                self.registers[register] = value
                self.events.append((self.cpucycles, address, register, value))
            else:
                raise ConversionError('unsupported-sid-register-write', f'Write to reserved/read-only SID register ${address:04X}')
        elif self.see_io and 0xd000 <= address <= 0xdfff:
            raise ConversionError('unsupported-io-write', f'Non-SID I/O write at ${address:04X} requires an extended execution profile', pc=self.pc)

    def invoke(self, address, accumulator, cycle_limit, *, start_cycle=None,
               instruction_limit=MAX_PLAY_INSTRUCTIONS, phase='play', call=None):
        self.events = []
        self.cycle_base = self.cycle_base + self.cpucycles if start_cycle is None else start_cycle
        self.init_cpu(address, accumulator)
        instructions = 0
        while True:
            try:
                continuing = self.runcpu()
            except ConversionError:
                raise
            except Exception as exc:
                raise ConversionError('unsupported-cpu-execution', str(exc), pc=self.pc) from exc
            instructions += 1
            if self.cpucycles > cycle_limit or instructions > instruction_limit:
                raise ConversionError('execution-budget-exceeded', f'{phase.capitalize()} routine exceeded its instruction/cycle budget',
                                      phase=phase, call=call, pc=self.pc, cycles=self.cpucycles,
                                      cycle_limit=cycle_limit, instructions=instructions, instruction_limit=instruction_limit)
            if not continuing:
                if self.last_instruction != 0x60 or self.sp != 0xff:
                    raise ConversionError('unsupported-routine-return', 'Direct-call routines must return with RTS and a balanced stack', pc=self.pc)
                break
        self.instructions += instructions
        return self.cpucycles


def capture(sid, profile, calls, output, *, hvsc=None):
    if not isinstance(calls, int) or not 1 <= calls <= MAX_CALLS:
        raise ConversionError('invalid-play-call-budget', f'Play-call budget must be 1–{MAX_CALLS}')
    cpu = CaptureCPU(profile)
    cpu.inject_bytes(sid.load_address, sid.payload)
    init_cycles = cpu.invoke(sid.init_address, profile['subsong'] - 1, MAX_INIT_CYCLES,
                             instruction_limit=MAX_INIT_INSTRUCTIONS, phase='init')
    init_events = list(cpu.events)
    initial = list(cpu.registers)
    header = {'type': 'header', 'schema': 1, 'source': sid.info(), 'profile': profile,
              'play_call_budget': calls, 'init_cycles': init_cycles, 'initial_registers': initial,
              'boundary': 'explicit-development-play-call-budget; no ending or loop inferred'}
    if hvsc is not None:
        header['boundary'] = 'hvsc-duration-rounded-up-to-whole-play-calls'
        header['hvsc'] = hvsc
    digest = hashlib.sha256(); count = 0
    with atomic_file(output) as temp:
        with temp.open('wb') as raw:
            compressed = gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) if str(output).endswith('.gz') else raw
            stream = io.TextIOWrapper(compressed, encoding='utf-8', newline='\n')
            def emit(row):
                stream.write(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n')
            def writes(events, call, base, phase):
                nonlocal count
                for offset, address, register, value in events:
                    row = {'type': 'write', 'seq': count, 'phase': phase, 'call': call, 'call_cycle': offset,
                           'cycle': base + offset, 'address': address, 'register': register, 'value': value}
                    encoded = json.dumps(row, sort_keys=True, separators=(',', ':')).encode()
                    digest.update(encoded + b'\n'); emit(row); count += 1
                    if count > MAX_WRITES: raise ConversionError('write-budget-exceeded', 'Trace exceeds the supported write budget')
            try:
                emit(header); writes(init_events, -1, 0, 'init')
                longest = 0
                for call in range(calls):
                    base = init_cycles + call * profile['cycles_per_call']
                    elapsed = cpu.invoke(sid.play_address, 0, profile['cycles_per_call'], start_cycle=base, call=call)
                    longest = max(longest, elapsed)
                    writes(cpu.events, call, base, 'play')
                    emit({'type': 'call', 'call': call, 'start_cycle': base, 'end_cycle': base + elapsed,
                          'registers': list(cpu.registers)})
                footer = {'type': 'end', 'complete': True, 'play_calls': calls, 'writes': count,
                          'end_cycle': init_cycles + calls * profile['cycles_per_call'],
                          'write_sha256': digest.hexdigest(), 'longest_play_call_cycles': longest,
                          'instructions': cpu.instructions,
                          'sid_bus_reads': {f'{a:04X}': n for a, n in sorted(cpu.sid_bus_reads.items())},
                          'other_io_writes': {f'{a:04X}': n for a, n in sorted(cpu.other_io_writes.items())}}
                emit(footer)
            finally:
                stream.close()
    return {'header': header, 'footer': footer, 'trace': str(Path(output))}
