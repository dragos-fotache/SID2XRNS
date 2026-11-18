// SPDX-License-Identifier: AGPL-3.0-only
#include "Probe.cpp"
#include <iostream>
#include <stdexcept>
void check(int size)
{
    diagnostic::Probe probe;
    sidsynth::PluginProcessor direct;
    struct PlayHead final : juce::AudioPlayHead
    {
        juce::Optional<PositionInfo> getPosition() const override
        { PositionInfo p;p.setIsPlaying(true);return p; }
    } playhead;
    probe.setPlayHead(&playhead);direct.setPlayHead(&playhead);
    probe.prepareToPlay(48000, size); direct.prepareToPlay(48000, size);
    juce::AudioBuffer<float> a(2,size), b(2,size);
    juce::MidiBuffer ma, mb;
    auto same = [&]
    {
        for (int r=0;r<25;++r)
            if (probe.engineForCheck().registerValue(r)!=direct.sidEngine().registerValue(r))
                throw std::runtime_error("Proxy and direct processor SID registers differ");
    };
    for (int block=0; block<8; ++block)
    {
        const auto& specs=sidsynth::parameters::specs();
        const bool gate=block<2;
        auto cue=sidsynth::EnvelopeCue::seal({0x1234u|(1u<<16)|(unsigned(gate)<<17),
            (gate?0u:200u)|(1u<<13)|((gate?0u:2u)<<16),
            (unsigned(block)&3u)<<16|(gate?0u:15u)<<12,1u});
        for (std::size_t i=0;i<specs.size();++i)
        {
            const auto& s=specs[i];
            float raw=s.initial;
            if(s.id=="voice1.release")raw=15;
            if(s.id=="voice1.tuning")raw=block*2;
            if(s.id=="voice1.pulseWidth")raw=100+block*400;
            if(s.id=="filter.cutoff")raw=100+block*200;
            if(s.id=="envelope.cueMode")raw=1;
            for(int word=0;word<4;++word)
                if(i==sidsynth::parameters::envelopeCue(0,word))raw=static_cast<float>(cue[static_cast<std::size_t>(word)]);
            const auto value=(raw-s.minimum)/(s.maximum-s.minimum);
            probe.getParameters()[static_cast<int>(i)]->setValueNotifyingHost(value);
            direct.getParameters()[static_cast<int>(i)]->setValueNotifyingHost(value);
        }
        ma.clear();mb.clear();
        if(block==0)ma.addEvent(juce::MidiMessage::noteOn(1,69,juce::uint8(127)),13);
        if(block==2)ma.addEvent(juce::MidiMessage::noteOff(1,69),47);
        mb=ma;
        probe.processBlock(a,ma);direct.processBlock(b,mb);same();
        const auto& captured=probe.captured();
        for (int sample=0;sample<size;++sample)
            if (captured.audio[static_cast<std::size_t>(block*size+sample)]!=b.getSample(0,sample))
                throw std::runtime_error("Diagnostic observation changed processor audio");
        if(block>2 && probe.engineForCheck().activeNote(0)!=-1)
            throw std::runtime_error("Release acquired note ownership");
    }
    const auto& sink=probe.captured();
    bool gate13=false, off47=false;
    long long previousEnvelopeSample=-1;
    for(std::size_t i=0;i<sink.eventCount;++i)
    {
        const auto& e=sink.events[i];
        if(e.kind==4)
        {
            if(e.sample<=previousEnvelopeSample) throw std::runtime_error("ENV3 timestamps moved backwards across engine chunks");
            previousEnvelopeSample=e.sample;
        }
        gate13|=e.kind==2 && e.a==4 && (e.b&1) && e.offset==13;
        off47|=e.kind==2 && e.a==4 && !(e.b&1) && e.offset==47;
    }
    if(!gate13||!off47||sink.overflow)throw std::runtime_error("Real-write timing observation failed");
    std::cout<<"Proxy/direct source-cue audio identical, monotonic ENV3, registers, release pitch and SID offsets 13/47: pass\n";
}

int main()
{
    juce::ScopedJuceInitialiser_GUI init;
    check(128);check(1024);
}
