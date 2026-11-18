# SPDX-License-Identifier: AGPL-3.0-only
import unittest
from sid2xrns.sidbus import SidBus


class SidBusTests(unittest.TestCase):
    def test_power_on_and_each_models_decay_boundary(self):
        for model, lifetime in [('6581', 0x1d00), ('8580', 0xa2000)]:
            with self.subTest(model=model):
                bus = SidBus(model)
                self.assertEqual(bus.read(0), 0)
                bus.write(0xa5, 100)
                self.assertEqual(bus.read(100 + lifetime - 1), 0xa5)
                bus.write(0x5a, 100 + lifetime)
                self.assertEqual(bus.read(100 + 2 * lifetime), 0)

    def test_reads_shorten_remaining_lifetime_and_new_writes_refresh_it(self):
        for model, lifetime in [('6581', 0x1d00), ('8580', 0xa2000)]:
            with self.subTest(model=model):
                bus = SidBus(model)
                bus.write(0xa5, 100)
                self.assertEqual(bus.read(110), 0xa5)
                self.assertEqual(bus.read(110 + (lifetime - 10) // 2), 0)
                bus.write(0x5a, 100 + lifetime)
                self.assertEqual(bus.read(101 + lifetime), 0x5a)
