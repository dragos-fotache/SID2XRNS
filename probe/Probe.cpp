// SPDX-License-Identifier: AGPL-3.0-only
// Real processor and core; fixed-storage observations, deferred file output.
#define createPluginFilter createInternalSIDSynthProcessor
#include "PluginProcessor.cpp"
#undef createPluginFilter
#include "SidBackend.h"
#include "SID.h"
#include <fstream>
#include <iomanip>
#include <unistd.h>

namespace diagnostic
{
struct Event { long long sample; int offset, kind, a, b, c; };
struct Block
{
    long long sample, hostSample;
    double ppq;
    int size, playing;
    std::array<float, sidsynth::parameters::count> parameters;
    std::array<unsigned char, 25> registers;
    std::array<int, 3> notes;
};
struct Sink
{
    Sink()
    {
        // Optional bounded long-take storage is prepared before any callback.
        // Default captures retain the original limits. No product changes.
        const int seconds = juce::jlimit(30, 260, juce::SystemStats::getEnvironmentVariable(
            "SID2XRNS_CAPTURE_SECONDS", "30").getIntValue());
        events.resize(seconds == 30 ? 262144 : static_cast<std::size_t>(seconds) * 8000);
        blocks.resize(seconds == 30 ? 32768 : static_cast<std::size_t>(seconds) * 3100);
        audio.resize(static_cast<std::size_t>(48000) * seconds);
    }
    std::vector<Event> events;
    std::vector<Block> blocks;
    std::vector<float> audio;
    std::size_t eventCount = 0, blockCount = 0, audioCount = 0;
    long long sample = 0;
    int offset = 0, overflow = 0;
    int sidCycles = 0;
    int clockedInRender = 0;
    void add(int kind, int a = 0, int b = 0, int c = 0) noexcept
    {
        if (eventCount == events.size()) { ++overflow; return; }
        events[eventCount++] = {sample + offset, offset, kind, a, b, c};
    }
};
thread_local Sink* active = nullptr;
thread_local sidsynth::SidBackend* writingBackend = nullptr;
thread_local sidsynth::SidBackend* observedBackend = nullptr;
thread_local reSIDfp::SID* observedCore = nullptr;

class Proxy final : public juce::AudioProcessorParameterWithID
{
public:
    Proxy(juce::AudioProcessorParameter& p, const sidsynth::parameters::Spec& spec)
        : AudioProcessorParameterWithID({spec.id, spec.version}, spec.name,
            juce::AudioProcessorParameterWithIDAttributes{}), target(p) {}
    float getValue() const override { return target.getValue(); }
    // The inner processor has no VST3 wrapper to send parameter listeners.
    // Forward notifications as its wrapper would, so APVTS raw values update.
    void setValue(float v) override { target.setValueNotifyingHost(v); }
    float getDefaultValue() const override { return target.getDefaultValue(); }
    juce::String getText(float v, int n) const override { return target.getText(v, n); }
    float getValueForText(const juce::String& t) const override { return target.getValueForText(t); }
    int getNumSteps() const override { return target.getNumSteps(); }
    bool isDiscrete() const override { return target.isDiscrete(); }
    bool isBoolean() const override { return target.isBoolean(); }
private:
    juce::AudioProcessorParameter& target;
};

class Probe final : public juce::AudioProcessor, private juce::Timer
{
public:
    Probe() : AudioProcessor(BusesProperties().withOutput("Output", juce::AudioChannelSet::stereo(), true)),
        directory(juce::SystemStats::getEnvironmentVariable("SID2XRNS_TRACE_DIR", "")), instance(++nextInstance)
    {
        const auto& specs = sidsynth::parameters::specs();
        for (std::size_t i = 0; i < specs.size(); ++i)
            addParameter(new Proxy(*inner.getParameters()[static_cast<int>(i)], specs[i]));
        addParameter(command = new juce::AudioParameterInt({"diagnostic.capture", 1}, "Capture", 0, 2, 1));
        exportBindings();
        startTimer(100);
    }
    ~Probe() override { stopTimer(); }
    const juce::String getName() const override { return "SID XRNS Timing Probe"; }
    void prepareToPlay(double sr, int n) override
    {
        rate = sr;
        inner.setRateAndBufferSizeDetails(sr, n);
        inner.prepareToPlay(sr, n);
    }
    void releaseResources() override { inner.releaseResources(); }
    void reset() override { inner.reset(); }
    bool isBusesLayoutSupported(const BusesLayout& l) const override
    { return l.getMainOutputChannelSet() == juce::AudioChannelSet::stereo(); }
    void processBlock(juce::AudioBuffer<float>& audio, juce::MidiBuffer& midi) override
    {
        const int request = command->get();
        auto current = phase.load(std::memory_order_relaxed);
        if (request == 1 && current != 1 && exported.load(std::memory_order_acquire) >= take)
        {
            sink.eventCount = sink.blockCount = sink.audioCount = 0;
            sink.sample = 0; sink.overflow = 0; sink.sidCycles = 0; ++take;
            current = 1; phase.store(1, std::memory_order_release);
        }
        if (request == 2 && current == 1) { phase.store(2, std::memory_order_release); current = 2; }
        inner.setPlayHead(getPlayHead());
        Block* row = nullptr;
        if (current == 1)
        {
            sink.offset = 0;
            for (const auto e : midi)
            {
                sink.offset = e.samplePosition;
                sink.add(1, e.numBytes > 0 ? e.data[0] : 0, e.numBytes > 1 ? e.data[1] : 0,
                    e.numBytes > 2 ? e.data[2] : 0);
            }
            sink.offset = 0;
            if (sink.blockCount < sink.blocks.size())
            {
                row = &sink.blocks[sink.blockCount++];
                row->sample = sink.sample; row->size = audio.getNumSamples();
                const auto p = getPlayHead() ? getPlayHead()->getPosition() : juce::Optional<juce::AudioPlayHead::PositionInfo>{};
                row->playing = p.hasValue() && p->getIsPlaying();
                row->ppq = p.hasValue() ? p->getPpqPosition().orFallback(-1.0) : -1.0;
                row->hostSample = p.hasValue() ? p->getTimeInSamples().orFallback(-1) : -1;
                for (std::size_t i = 0; i < row->parameters.size(); ++i)
                    row->parameters[i] = inner.state.getRawParameterValue(sidsynth::parameters::specs()[i].id)->load();
            }
            else ++sink.overflow;
            active = &sink;
        }
        inner.processBlock(audio, midi);
        active = nullptr;
        if (current == 1)
        {
            if (row)
            {
                for (int i = 0; i < 25; ++i) row->registers[static_cast<std::size_t>(i)] = inner.sidEngine().registerValue(i);
                for (int i = 0; i < 3; ++i) row->notes[static_cast<std::size_t>(i)] = inner.sidEngine().activeNote(i);
            }
            const auto n = static_cast<std::size_t>(audio.getNumSamples());
            if (sink.audioCount + n <= sink.audio.size())
            {
                std::copy_n(audio.getReadPointer(0), n, sink.audio.data() + sink.audioCount);
                sink.audioCount += n;
            }
            else ++sink.overflow;
            sink.sample += audio.getNumSamples();
        }
        // Capture real processor output internally; diagnostic host is silent.
        audio.clear();
    }
    double getTailLengthSeconds() const override { return inner.getTailLengthSeconds(); }
    bool acceptsMidi() const override { return true; }
    bool producesMidi() const override { return false; }
    bool hasEditor() const override { return true; }
    juce::AudioProcessorEditor* createEditor() override { return new juce::GenericAudioProcessorEditor(*this); }
    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram(int) override {}
    const juce::String getProgramName(int) override { return {}; }
    void changeProgramName(int, const juce::String&) override {}
    void getStateInformation(juce::MemoryBlock& b) override { inner.getStateInformation(b); }
    void setStateInformation(const void* b, int n) override { inner.setStateInformation(b, n); *command = 1; }
    const Sink& captured() const noexcept { return sink; }
    const sidsynth::SidEngine& engineForCheck() const noexcept { return inner.sidEngine(); }
private:
    void exportBindings()
    {
        if (directory.isEmpty()) return;
        juce::Array<juce::var> specs;
        for (const auto& s : sidsynth::parameters::specs())
        {
            auto* o = new juce::DynamicObject;
            o->setProperty("id", s.id); o->setProperty("name", s.name);
            o->setProperty("minimum", s.minimum); o->setProperty("maximum", s.maximum);
            o->setProperty("initial", s.initial); o->setProperty("step", s.step); o->setProperty("version", s.version);
            specs.add(juce::var(o));
        }
        juce::File(directory).getChildFile("bindings.json").replaceWithText(juce::JSON::toString(juce::var(specs)));
    }
    void timerCallback() override
    {
        if (directory.isEmpty() || phase.load(std::memory_order_acquire) != 2 || exported.load() == take) return;
        const auto stem = "trace-" + juce::String(getpid()) + "-" + juce::String(instance) + "-" + juce::String(take);
        const auto file = juce::File(directory).getChildFile(stem + ".json");
        const auto temp = file.getSiblingFile(file.getFileName() + ".tmp");
        std::ofstream out(temp.getFullPathName().toStdString());
        out << std::setprecision(12) << "{\"pid\":" << getpid() << ",\"instance\":" << instance << ",\"take\":" << take
            << ",\"sample_rate\":" << rate << ",\"overflow\":" << sink.overflow << ",\"frames\":" << sink.sample << ",\"events\":[";
        for (std::size_t i = 0; i < sink.eventCount; ++i)
        {
            const auto& r = sink.events[i]; if (i) out << ',';
            out << '[' << r.sample << ',' << r.offset << ',' << r.kind << ',' << r.a << ',' << r.b << ',' << r.c << ']';
        }
        out << "],\"blocks\":[";
        for (std::size_t i = 0; i < sink.blockCount; ++i)
        {
            const auto& r = sink.blocks[i]; if (i) out << ',';
            out << "{\"sample\":" << r.sample << ",\"host_sample\":" << r.hostSample << ",\"ppq\":" << r.ppq
                << ",\"playing\":" << r.playing << ",\"size\":" << r.size << ",\"parameters\":[";
            for (std::size_t j = 0; j < r.parameters.size(); ++j) { if (j) out << ','; out << r.parameters[j]; }
            out << "],\"registers\":[";
            for (std::size_t j = 0; j < r.registers.size(); ++j) { if (j) out << ','; out << static_cast<int>(r.registers[j]); }
            out << "],\"notes\":[" << r.notes[0] << ',' << r.notes[1] << ',' << r.notes[2] << "]}";
        }
        out << "]}\n"; out.close();
        // Raw native-endian float32 mono, accompanied by the trace's rate.
        std::ofstream wav(juce::File(directory).getChildFile(stem + ".f32").getFullPathName().toStdString(), std::ios::binary);
        wav.write(reinterpret_cast<const char*>(sink.audio.data()), static_cast<std::streamsize>(sink.audioCount * sizeof(float)));
        wav.close();
        if (out && wav && temp.moveFileTo(file)) exported.store(take, std::memory_order_release);
    }
    sidsynth::PluginProcessor inner;
    Sink sink;
    juce::AudioParameterInt* command = nullptr;
    juce::String directory;
    double rate = 0;
    int take = 0, instance;
    std::atomic<int> phase{0}, exported{0};
    inline static std::atomic<int> nextInstance{0};
};
}

extern "C" void __real__ZN8sidsynth10SidBackend5writeEih(sidsynth::SidBackend*, int, unsigned char);
extern "C" void __wrap__ZN8sidsynth10SidBackend5writeEih(sidsynth::SidBackend* self, int a, unsigned char v)
{
    if (diagnostic::active) diagnostic::active->add(2, a, v);
    diagnostic::writingBackend = self;
    __real__ZN8sidsynth10SidBackend5writeEih(self, a, v);
    diagnostic::writingBackend = nullptr;
}
extern "C" void __real__ZN7reSIDfp3SID5writeEih(reSIDfp::SID*, int, unsigned char);
extern "C" void __wrap__ZN7reSIDfp3SID5writeEih(reSIDfp::SID* self, int a, unsigned char v)
{
    if (diagnostic::writingBackend)
    {
        diagnostic::observedBackend = diagnostic::writingBackend;
        diagnostic::observedCore = self;
    }
    __real__ZN7reSIDfp3SID5writeEih(self, a, v);
}
extern "C" void __real__ZN8sidsynth10SidBackend5clockEPsi(sidsynth::SidBackend*, short*, int);
extern "C" void __wrap__ZN8sidsynth10SidBackend5clockEPsi(sidsynth::SidBackend* self, short* out, int n)
{
    auto* sink = diagnostic::active;
    if (!sink || diagnostic::observedBackend != self || !diagnostic::observedCore)
    { __real__ZN8sidsynth10SidBackend5clockEPsi(self, out, n); return; }
    // Bounded one-ms ENV3 observation. Public non-mutating peek, no private
    // layout access. Pulling the same sample count in chunks is audio-checked.
    const int originalOffset = sink->offset;
    const int offset = originalOffset + sink->clockedInRender;
    for (int cursor = 0; cursor < n;)
    {
        const int count = std::min(48, n - cursor);
        sink->sidCycles += diagnostic::observedCore->clock(out + cursor, count);
        cursor += count;
        sink->offset = offset + cursor;
        sink->add(4, diagnostic::observedCore->peek(0x1c), sink->sidCycles);
    }
    sink->clockedInRender += n;
    sink->offset = originalOffset;
}
extern "C" void __real__ZN8sidsynth10SidBackend5resetEv(sidsynth::SidBackend*);
extern "C" void __wrap__ZN8sidsynth10SidBackend5resetEv(sidsynth::SidBackend* self)
{
    if (diagnostic::active) diagnostic::active->add(3);
    __real__ZN8sidsynth10SidBackend5resetEv(self);
}
extern "C" void __real__ZN8sidsynth9SidEngine6renderEPfiPKfS3_(sidsynth::SidEngine*, float*, int, const float*, const float*);
extern "C" void __wrap__ZN8sidsynth9SidEngine6renderEPfiPKfS3_(sidsynth::SidEngine* self, float* out, int n, const float* l, const float* r)
{
    if (diagnostic::active) diagnostic::active->clockedInRender = 0;
    __real__ZN8sidsynth9SidEngine6renderEPfiPKfS3_(self, out, n, l, r);
    if (diagnostic::active) diagnostic::active->offset += n;
}
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() { return new diagnostic::Probe; }
