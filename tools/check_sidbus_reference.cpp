// SPDX-License-Identifier: AGPL-3.0-only
// Compare capture's write-only bus reads with the pinned libresidfp core.
#include <SID.h>
#include <iostream>

int main()
{
    for (int model = 0; model < 2; ++model)
    {
        reSIDfp::SID sid;
        sid.setChipModel(model ? reSIDfp::CSG8580 : reSIDfp::MOS6581);
        auto step = [&](unsigned cycles, int offset)
        {
            sid.clockSilent(cycles);
            const auto value = sid.read(offset);
            std::cout << model << ' ' << cycles << ' ' << offset << ' ' << int(value) << '\n';
        };
        sid.write(0x18, 15);
        sid.write(0, 165);
        step(10, 0x18);
        step(10, 4);
        step(100, 0x1f);
        step(19000, 0x18);
        sid.write(0x18, 90);
        step(model ? 0xa2000 : 0x1d00, 0);
    }
}
