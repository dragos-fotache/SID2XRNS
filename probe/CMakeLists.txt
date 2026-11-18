# SPDX-License-Identifier: AGPL-3.0-only
cmake_minimum_required(VERSION 3.24)
project(SIDXRNSTiming VERSION 0.1.0 LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if(NOT EXISTS "${SIDSYNTH_SOURCE_DIR}/src/PluginProcessor.cpp")
    message(FATAL_ERROR "Supply SIDSYNTH_SOURCE_DIR for the validated SIDSynth checkout")
endif()
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/../docs/source-lock.json" source_lock)
string(JSON file_count LENGTH "${source_lock}" files)
math(EXPR last_file "${file_count} - 1")
foreach(i RANGE ${last_file})
    string(JSON source_file MEMBER "${source_lock}" files ${i})
    string(JSON expected_hash GET "${source_lock}" files "${source_file}")
    file(SHA256 "${SIDSYNTH_SOURCE_DIR}/${source_file}" actual_hash)
    if(NOT actual_hash STREQUAL expected_hash)
        message(FATAL_ERROR "SIDSynth source lock mismatch: ${source_file}; review the new source before rebaselining")
    endif()
endforeach()
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
add_subdirectory("${SIDSYNTH_SOURCE_DIR}" synth EXCLUDE_FROM_ALL)
juce_add_plugin(SIDXRNSTimingProbe
    COMPANY_NAME SIDSynth BUNDLE_ID org.sidsynth.xrns-timing-probe
    PLUGIN_MANUFACTURER_CODE Sids PLUGIN_CODE Sxtp
    PRODUCT_NAME "SID XRNS Timing Probe" IS_SYNTH TRUE NEEDS_MIDI_INPUT TRUE
    NEEDS_MIDI_OUTPUT FALSE COPY_PLUGIN_AFTER_BUILD FALSE FORMATS VST3
    VST3_CATEGORIES Instrument Synth)
target_sources(SIDXRNSTimingProbe PRIVATE Probe.cpp
    "${SIDSYNTH_SOURCE_DIR}/src/PluginEditor.cpp"
    "${SIDSYNTH_SOURCE_DIR}/src/MidiRouter.cpp")
target_include_directories(SIDXRNSTimingProbe PRIVATE "${SIDSYNTH_SOURCE_DIR}/src")
target_compile_definitions(SIDXRNSTimingProbe PUBLIC
    JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0 JUCE_VST3_CAN_REPLACE_VST2=0)
target_link_libraries(SIDXRNSTimingProbe PRIVATE sid_engine libresidfp juce::juce_audio_utils
    PUBLIC juce::juce_recommended_config_flags)
# Observe real production calls without modifying any SIDSynth source. No LTO:
# these calls must cross translation units for the ELF linker's wrapping.
target_link_options(SIDXRNSTimingProbe_VST3 PRIVATE
    -Wl,--wrap=_ZN8sidsynth10SidBackend5clockEPsi
    -Wl,--wrap=_ZN7reSIDfp3SID5writeEih
    -Wl,--wrap=_ZN8sidsynth10SidBackend5writeEih
    -Wl,--wrap=_ZN8sidsynth10SidBackend5resetEv
    -Wl,--wrap=_ZN8sidsynth9SidEngine6renderEPfiPKfS3_)
add_executable(probe_self_check SelfCheck.cpp)
target_include_directories(probe_self_check PRIVATE "${SIDSYNTH_SOURCE_DIR}/src")
target_link_libraries(probe_self_check PRIVATE SIDXRNSTimingProbe libresidfp juce::juce_audio_utils)
target_link_options(probe_self_check PRIVATE
    -Wl,--wrap=_ZN8sidsynth10SidBackend5clockEPsi
    -Wl,--wrap=_ZN7reSIDfp3SID5writeEih
    -Wl,--wrap=_ZN8sidsynth10SidBackend5writeEih
    -Wl,--wrap=_ZN8sidsynth10SidBackend5resetEv
    -Wl,--wrap=_ZN8sidsynth9SidEngine6renderEPfiPKfS3_)
