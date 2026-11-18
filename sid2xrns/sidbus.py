# SPDX-License-Identifier: AGPL-3.0-only
"""SID write-only readback at the capture's instruction-end precision.

The latch lifetimes and read-discharge policy follow libresidfp 1.3.0,
commit 5393471a02a505ff43aa710148b2d35289b72c31 (SID.cpp/SID.h).
See third_party/NOTICES.md. This does not emulate OSC3, ENV3 or paddles.
"""


class SidBus:
    def __init__(self, model):
        self.lifetime = {'6581': 0x01d00, '8580': 0xa2000}[model]
        self.value = self.ttl = self.cycle = 0

    def write(self, value, cycle):
        self.value, self.ttl, self.cycle = value, self.lifetime, cycle

    def read(self, cycle):
        if cycle < self.cycle:
            raise ValueError('SID bus clock must be monotonic')
        if self.ttl:
            self.ttl -= cycle - self.cycle
            if self.ttl <= 0:
                self.value = self.ttl = 0
        self.cycle = cycle
        # A write-only/unmapped read discharges the latch more quickly.
        # Return the held value, never a writable register's shadow value.
        self.ttl //= 2
        return self.value
