# SPDX-License-Identifier: AGPL-3.0-only
"""Native preset primitives proven by the step-1 host fixture."""
import struct
import xml.etree.ElementTree as E

PRODUCT_ID = 'ABCDEF019182FAEB5369647353796469'
PROBE_ID = 'ABCDEF019182FAEB5369647353787470'

def put(parent, tag, value):
    e = parent.find(tag)
    if e is None:
        e = E.SubElement(parent, tag)
    e.text = str(value)
    return e


def timing(seconds):
    units = round(seconds * 12800)
    return units, units / 12800


def read_preset(data):
    if len(data) < 48 or data[:4] != b'VST3' or struct.unpack_from('<I', data, 4)[0] != 1:
        raise ValueError('Expected a VST3 version-1 preset container')
    offset = struct.unpack_from('<Q', data, 40)[0]
    if offset + 8 > len(data) or data[offset:offset + 4] != b'List':
        raise ValueError('Invalid VST3 chunk table')
    count = struct.unpack_from('<I', data, offset + 4)[0]
    if offset + 8 + count * 20 != len(data):
        raise ValueError('Unexpected VST3 chunk table size')
    chunks = []
    for i in range(count):
        tag, start, size = struct.unpack_from('<4sQQ', data, offset + 8 + i * 20)
        if start < 48 or start + size > offset:
            raise ValueError('VST3 chunk is outside the payload')
        chunks.append((tag, data[start:start + size]))
    if sum(tag == b'Comp' for tag, _ in chunks) != 1:
        raise ValueError('Expected one component chunk')
    return data[:40], chunks


def replace_patch(data, patch, identifier):
    header, chunks = read_preset(data)
    result = bytearray(header[:8] + identifier.encode('ascii') + bytes(8))
    entries = []
    for tag, chunk in chunks:
        if tag == b'Comp':
            if chunk[:4] != b'VC2!' or len(chunk) < 8:
                raise ValueError('Expected JUCE binary XML')
            size = struct.unpack_from('<I', chunk, 4)[0]
            old = E.fromstring(chunk[8:8 + size])
            if old.tag != 'SIDSynthPatch' or old.get('schemaVersion') not in ('3', '4'):
                raise ValueError('Expected SIDSynth schema 3 or 4')
            xml = E.tostring(patch, encoding='utf-8')
            chunk = b'VC2!' + struct.pack('<I', len(xml)) + xml + chunk[8 + size:]
        entries.append((tag, len(result), len(chunk)))
        result.extend(chunk)
    struct.pack_into('<Q', result, 40, len(result))
    result.extend(b'List' + struct.pack('<I', len(entries)))
    for entry in entries:
        result.extend(struct.pack('<4sQQ', *entry))
    read_preset(result)
    return bytes(result)


def validate_song(root):
    instruments = root.findall('./Instruments/Instrument')
    generators = [i.find('PluginGenerator') for i in instruments]
    if len(generators) != 3 or sum(g.find('PluginDevice') is not None for g in generators) != 1:
        raise ValueError('Expected exactly one plugin and two aliases')
    if [int(g.findtext('Channel')) for g in generators] != [0, 1, 2]:
        raise ValueError('Expected saved channels 0/1/2 (host channels 1/2/3)')
    if [int(g.findtext('AliasInstrumentIndex')) for g in generators] != [-1, 0, 0]:
        raise ValueError('Expected one root and two direct aliases; refusing cyclic links')
    if generators[0].findtext('./PluginDevice/PluginIdentifier') not in (PRODUCT_ID, PROBE_ID):
        raise ValueError('Unexpected plugin identity')

