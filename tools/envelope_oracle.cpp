// SPDX-License-Identifier: AGPL-3.0-only
// Unmodified pinned core as an observable oracle for the Python envelope model.
#include "EnvelopeGenerator.h"
#include <array>
#include <iostream>
int main()
{
    std::array<reSIDfp::EnvelopeGenerator, 3> env;
    for (auto& e : env) e.reset();
    long long now=0, when; int reg,value;
    while (std::cin>>when>>reg>>value)
    {
        if (when<now) return 2;
        for (;now<when;++now) for (auto& e:env) e.clock();
        if (reg==-1)
        {
            std::cout<<when;
            for (auto& e:env) std::cout<<' '<<unsigned(e.readENV())<<' '<<unsigned(e.output());
            std::cout<<'\n';
        }
        else if (reg<21)
        {
            auto& e=env[reg/7];
            if(reg%7==4)e.writeCONTROL_REG(value);
            if(reg%7==5)e.writeATTACK_DECAY(value);
            if(reg%7==6)e.writeSUSTAIN_RELEASE(value);
        }
    }
}
