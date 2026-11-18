// SPDX-License-Identifier: AGPL-3.0-only
// Diagnostic: one pinned raw SID core, chronological physical writes, no MIDI
// router, exporter, saved snapshots, or source CPU execution in this renderer.
#include "SID.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>

// The pinned build-tree SID header already grants this diagnostic friend.
// Only public envelope readback is exposed; no emulation state is changed.
namespace sidsynth
{
class SidBackend
{
public:
    static unsigned envelope(const reSIDfp::SID& sid, int voice)
    { return sid.voice[voice].envelope()->readENV(); }
};
}

int main(int argc, char** argv)
{
    try
    {
        if (argc != 3 && argc != 4) throw std::runtime_error("usage: core-renderer TIMELINE.tsv OUTPUT.wav [ENVELOPES.tsv]");
        std::ifstream input(argv[1]);
        int model, warm; long long end; double hz, gain;
        if (!(input >> model >> warm >> end >> hz >> gain) || (model != 6581 && model != 8580)
            || warm < 0 || warm > 48000 || end < 1 || end > 300 * hz)
            throw std::runtime_error("Invalid bounded timeline header");
        reSIDfp::SID sid;
        sid.setChipModel(model == 8580 ? reSIDfp::CSG8580 : reSIDfp::MOS6581);
        sid.setSamplingParameters(hz, reSIDfp::RESAMPLE, 48000);
        sid.setNoiseLevel(1); sid.input(0); sid.reset();
        std::vector<short> scratch(48000);
        if (warm) sid.clock(scratch.data(), warm);
        double previousInput = warm ? scratch[warm - 1] / 32768.0 : 0, previousOutput = 0;
        const double coefficient = std::exp(-2 * 3.14159265358979323846 * 5 / 48000);
        std::vector<float> audio;
        audio.reserve(static_cast<std::size_t>(end * 48000 / hz + 256));
        std::ofstream envelopes;
        if (argc == 4) envelopes.open(argv[3]);
        long long currentCycle = 0, nextProbe = static_cast<long long>(std::llround(hz / 1000));
        auto clock = [&](long long cycles)
        {
            while (cycles > 0)
            {
                const auto n = static_cast<unsigned>(std::min<long long>(cycles,
                    argc == 4 ? nextProbe - currentCycle : 8192));
                const int samples = sid.clock(n, scratch.data());
                for (int i = 0; i < samples; ++i)
                {
                    const double x = scratch[i] / 32768.0;
                    const double y = x - previousInput + coefficient * previousOutput;
                    previousInput = x; previousOutput = y;
                    audio.push_back(static_cast<float>(y * gain));
                }
                cycles -= n;
                currentCycle += n;
                if (argc == 4 && currentCycle == nextProbe)
                {
                    envelopes << currentCycle << ' ' << sidsynth::SidBackend::envelope(sid, 0)
                        << ' ' << sidsynth::SidBackend::envelope(sid, 1)
                        << ' ' << sidsynth::SidBackend::envelope(sid, 2) << '\n';
                    nextProbe += static_cast<long long>(std::llround(hz / 1000));
                }
            }
        };
        long long cursor = 0, when; int reg, value;
        while (input >> when >> reg >> value)
        {
            if (when < cursor || when > end || reg < 0 || reg > 24 || value < 0 || value > 255)
                throw std::runtime_error("Invalid ordered SID write");
            clock(when - cursor); cursor = when;
            sid.write(reg, static_cast<unsigned char>(value));
        }
        if (!input.eof()) throw std::runtime_error("Malformed timeline");
        clock(end - cursor);
        std::ofstream out(argv[2], std::ios::binary);
        auto u16 = [&](unsigned v) { out.put(static_cast<char>(v)); out.put(static_cast<char>(v >> 8)); };
        auto u32 = [&](unsigned v) { u16(v); u16(v >> 16); };
        const auto bytes = static_cast<unsigned>(audio.size() * sizeof(float));
        out.write("RIFF", 4); u32(36 + bytes); out.write("WAVEfmt ", 8); u32(16);
        u16(3); u16(1); u32(48000); u32(48000 * 4); u16(4); u16(32);
        out.write("data", 4); u32(bytes);
        out.write(reinterpret_cast<const char*>(audio.data()), bytes);
        if (!out) throw std::runtime_error("WAV write failed");
        std::cout << "Rendered " << audio.size() << " samples from ordered cycle writes\n";
        return 0;
    }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
