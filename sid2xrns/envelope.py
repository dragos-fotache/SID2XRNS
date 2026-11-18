# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright 2011-2020 Leandro Nini; 2018 VICE Project;
# Copyright 2007-2010 Antti Lankila; 2004,2010 Dag Lem.
"""Pinned libresidfp 1.3.0 envelope semantics, with exact event skipping.

Derived from EnvelopeGenerator.{h,cpp}, commit 5393471a02a505ff43aa710148b2d35289b72c31,
GPL-2.0-or-later (GPLv3 option); original authors/notices in third_party/NOTICES.md.
No oscillator, filter, MIDI ownership or audio rendering is implemented here.
"""
import math

RATES = (0x007f, 0x3000, 0x1e00, 0x0660, 0x0182, 0x5573, 0x000e, 0x3805,
         0x2424, 0x2220, 0x090c, 0x0ecd, 0x010e, 0x23f7, 0x5237, 0x64a8)
LFSR = [0x7fff]
for _ in range(32766):
    v = LFSR[-1]
    LFSR.append((v >> 1) | (((v << 14) ^ (v << 13)) & 0x4000))
POSITIONS = {v: i for i, v in enumerate(LFSR)}
RATE_POSITIONS = tuple(POSITIONS[v] for v in RATES)
PERIODS = (0, 1, 2, 4, 8, 16, 30)
ATTACK, DECAY, RELEASE = range(3)


def seal_words(words):
    """CRC-10/ATM over 70 payload bits rejects torn host parameter updates."""
    crc = 0x3ff
    for word, bits in zip(words, (18, 18, 18, 16)):
        for bit in range(bits - 1, -1, -1):
            feedback = ((crc >> 9) ^ (word >> bit)) & 1
            crc = ((crc << 1) & 0x3ff) ^ (0x233 if feedback else 0)
    return (words[0] | (crc & 3) << 18, words[1] | ((crc >> 2) & 3) << 18,
            words[2] | ((crc >> 4) & 3) << 18, words[3] | (crc >> 6) << 16)


def warm_cycles(clock, samples=48000, rate=48000):
    """Exact cycles needed by the pinned two-pass resampler's sample-pull API."""
    half = 20000 if rate > 44000 else rate * .45
    middle = 2 * half + math.sqrt(2 * half * clock * (rate - 2 * half) / rate)
    a, b = int(clock / middle * 1024), int(middle / rate * 1024)
    # First input to each reset stage emits a sample. To obtain N final outputs,
    # stage 2 needs this many inputs; stage 1 then needs this many chip clocks.
    intermediate = ((samples - 1) * b + 1023) // 1024 + 1
    return ((intermediate - 1) * a + 1023) // 1024 + 1


class Envelope:
    def __init__(self):
        self.phase = 0
        self.rate = 0
        self.exp = 0
        self.period = 1
        self.new_period = 0
        self.state_pipe = self.env_pipe = self.exp_pipe = 0
        self.state = self.next_state = RELEASE
        self.enabled = True
        self.gate = False
        self.reset = True
        self.counter = 0xaa
        self.attack = self.decay = self.sustain = self.release = 0
        self.env3 = 0

    def write(self, offset, value):
        if offset == 4:
            gate = bool(value & 1)
            if gate != self.gate:
                self.gate = gate
                if gate:
                    self.next_state = ATTACK; self.state_pipe = 2
                    if self.reset or self.exp_pipe == 2:
                        self.env_pipe = 2 if self.period == 1 or self.exp_pipe == 2 else 4
                    elif self.exp_pipe == 1:
                        self.state_pipe = 3
                else:
                    self.next_state = RELEASE; self.state_pipe = 3 if self.env_pipe else 2
        elif offset == 5:
            self.attack, self.decay = value >> 4, value & 15
            if self.state == ATTACK: self.rate = self.attack
            elif self.state == DECAY: self.rate = self.decay
        elif offset == 6:
            self.sustain = (value & 0xf0) | (value >> 4)
            self.release = value & 15
            if self.state == RELEASE: self.rate = self.release

    def step(self):
        self.env3 = self.counter
        if self.new_period:
            self.period = self.new_period; self.new_period = 0
        if self.state_pipe:
            self.state_pipe -= 1
            if self.next_state == ATTACK:
                if self.state_pipe == 1: self.rate = self.decay
                elif self.state_pipe == 0:
                    self.state = ATTACK; self.rate = self.attack; self.enabled = True
            elif self.next_state == DECAY:
                if self.state_pipe == 0: self.state = DECAY; self.rate = self.decay
            elif ((self.state == ATTACK and self.state_pipe == 0) or
                  (self.state == DECAY and self.state_pipe == 1)):
                self.state = RELEASE; self.rate = self.release
        env_end = False
        if self.env_pipe:
            self.env_pipe -= 1
            env_end = self.env_pipe == 0
        if env_end:
            if self.enabled:
                if self.state == ATTACK:
                    self.counter = (self.counter + 1) & 255
                    if self.counter == 255: self.next_state = DECAY; self.state_pipe = 3
                else:
                    self.counter = (self.counter - 1) & 255
                    if self.counter == 0: self.enabled = False
                period = {255: 1, 0: 1, 93: 2, 54: 4, 26: 8, 14: 16, 6: 30}.get(self.counter)
                if period is not None: self.new_period = period
        else:
            exp_end = False
            if self.exp_pipe:
                self.exp_pipe -= 1
                exp_end = self.exp_pipe == 0
            if exp_end:
                self.exp = 0
                if (self.state == DECAY and self.counter != self.sustain) or self.state == RELEASE:
                    self.env_pipe = 1
            elif self.reset:
                self.phase = 0; self.reset = False
                if self.state == ATTACK:
                    self.exp = 0; self.env_pipe = 2
                elif self.enabled:
                    self.exp += 1
                    if self.exp == self.period: self.exp_pipe = 2 if self.period != 1 else 1
        if self.phase != RATE_POSITIONS[self.rate]: self.phase = (self.phase + 1) % 32767
        else: self.reset = True

    def clock(self, cycles):
        while cycles:
            if not (self.new_period or self.state_pipe or self.env_pipe or self.exp_pipe or self.reset):
                limit = RATE_POSITIONS[self.rate]
                if not self.enabled and 1 <= self.phase <= limit:
                    # Frozen zero envelope: the entire counter cycle repeats.
                    cycles %= limit + 1
                    if not cycles: self.env3 = self.counter; return
                distance = (limit - self.phase) % 32767
                if distance:
                    skip = min(cycles, distance)
                    self.phase = (self.phase + skip) % 32767
                    self.env3 = self.counter
                    cycles -= skip
                    continue
            self.step(); cycles -= 1

    def words(self, trigger, epoch, serial):
        return seal_words((LFSR[self.phase] | int(self.reset) << 15 | int(self.enabled) << 16 |
                           int(self.gate) << 17,
                           self.counter | self.exp << 8 | PERIODS.index(self.period) << 13 | self.state << 16,
                           PERIODS.index(self.new_period) | self.state_pipe << 3 | self.next_state << 5 |
                           self.env_pipe << 7 | self.exp_pipe << 10 | self.rate << 12 | (serial & 3) << 16,
                           epoch))
