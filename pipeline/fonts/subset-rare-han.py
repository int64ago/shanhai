"""Subset a TrueType glyf font using only Python's standard library.
Keeps .notdef, requested glyphs and recursive composite components; renumbers
composite references, rebuilds metrics/cmap/loca/name, and checks all checksums.
Run with -I. This only reads font data and never executes embedded font programs.
"""
import argparse
import datetime
import hashlib
import json
import math
from pathlib import Path
import struct


def u16(data, offset):
    return struct.unpack_from('>H', data, offset)[0]


def u32(data, offset):
    return struct.unpack_from('>I', data, offset)[0]


def padded(data):
    return data + b'\0' * (-len(data) % 4)


def checksum(data):
    data = padded(data)
    return sum(value for (value,) in struct.iter_unpack('>I', data)) & 0xffffffff


def components(data):
    if not data or struct.unpack_from('>h', data)[0] >= 0:
        return []
    offset, result = 10, []
    while True:
        flags, glyph = struct.unpack_from('>HH', data, offset)
        result.append((offset + 2, glyph))
        offset += 4 + (4 if flags & 1 else 2)
        offset += 2 if flags & 8 else 4 if flags & 64 else 8 if flags & 128 else 0
        assert offset <= len(data), 'composite component bounds'
        if not flags & 32:
            return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('font', type=Path)
    p.add_argument('license', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--text', default='𧔥')
    p.add_argument('--date', default='2026-11-08')
    a = p.parse_args()
    source = a.font.read_bytes()
    assert source[:4] == b'\0\1\0\0', 'requires TrueType outlines'
    tables = {}
    for i in range(u16(source, 4)):
        tag, expected, offset, size = struct.unpack_from('>4sIII', source, 12 + i * 16)
        assert offset + size <= len(source), 'font download is incomplete'
        table = source[offset:offset + size]
        check = bytearray(table)
        if tag == b'head':
            check[8:12] = b'\0' * 4
        assert checksum(check) == expected, 'source table checksum ' + repr(tag)
        tables[tag] = table
    assert checksum(source) == 0xb1b0afba, 'source font checksum'
    cmap = tables[b'cmap']
    mapping = {}
    for i in range(u16(cmap, 2)):
        platform, encoding, offset = struct.unpack_from('>HHI', cmap, 4 + 8 * i)
        if platform not in (0, 3) or u16(cmap, offset) != 12:
            continue
        for j in range(u32(cmap, offset + 12)):
            start, end, first = struct.unpack_from('>III', cmap, offset + 16 + 12 * j)
            for cp in map(ord, a.text):
                if start <= cp <= end:
                    mapping[cp] = first + cp - start
    assert set(mapping) == set(map(ord, a.text)), 'all requested characters must exist'
    glyph_count = u16(tables[b'maxp'], 4)
    long_loca = struct.unpack_from('>h', tables[b'head'], 50)[0] == 1
    loca = tables[b'loca']
    offsets = [u32(loca, 4 * i) if long_loca else u16(loca, 2 * i) * 2 for i in range(glyph_count + 1)]
    glyf = tables[b'glyf']
    assert offsets == sorted(offsets) and offsets[-1] <= len(glyf)
    raw = lambda gid: glyf[offsets[gid]:offsets[gid + 1]]
    keep = {0, *mapping.values()}
    pending = list(keep)
    while pending:
        for _, child in components(raw(pending.pop())):
            assert child < glyph_count
            if child not in keep:
                keep.add(child)
                pending.append(child)
    kept = sorted(keep)
    ids = {old: new for new, old in enumerate(kept)}
    result, locations = bytearray(), []
    metrics = bytearray()
    hmetrics = u16(tables[b'hhea'], 34)
    for old in kept:
        locations.append(len(result))
        data = bytearray(raw(old))
        for offset, child in components(data):
            struct.pack_into('>H', data, offset, ids[child])
        result.extend(padded(data))
        width = u16(tables[b'hmtx'], 4 * min(old, hmetrics - 1))
        bearing_at = 4 * old + 2 if old < hmetrics else 4 * hmetrics + 2 * (old - hmetrics)
        bearing = struct.unpack_from('>h', tables[b'hmtx'], bearing_at)[0]
        metrics.extend(struct.pack('>Hh', width, bearing))
    locations.append(len(result))
    out = {tag: tables[tag] for tag in [b'OS/2', b'cvt ', b'fpgm', b'gasp', b'prep'] if tag in tables}
    head, hhea, maxp = [bytearray(tables[tag]) for tag in [b'head', b'hhea', b'maxp']]
    struct.pack_into('>I', head, 8, 0)
    struct.pack_into('>h', head, 50, 1)
    modified = datetime.datetime.fromisoformat(a.date).replace(tzinfo=datetime.timezone.utc)
    struct.pack_into('>Q', head, 28, int(modified.timestamp()) + 2082844800)
    struct.pack_into('>H', hhea, 34, len(kept))
    struct.pack_into('>H', maxp, 4, len(kept))
    out.update({b'head': head, b'hhea': hhea, b'maxp': maxp, b'glyf': result,
                b'loca': struct.pack('>' + 'I' * len(locations), *locations), b'hmtx': metrics})
    os2 = bytearray(out[b'OS/2'])
    struct.pack_into('>IIII', os2, 42, 0, 1 << 25, 0, 0)
    struct.pack_into('>HH', os2, 64, min(min(mapping), 65535), min(max(mapping), 65535))
    out[b'OS/2'] = os2
    subtable = struct.pack('>HHIII', 12, 0, 16 + 12 * len(mapping), 0, len(mapping))
    for cp, old in sorted(mapping.items()):
        subtable += struct.pack('>III', cp, cp, ids[old])
    out[b'cmap'] = struct.pack('>HHHHIHHI', 0, 2, 0, 4, 20, 3, 10, 20) + subtable
    original_names = tables[b'name']
    names_by_id = {}
    for i in range(u16(original_names, 2)):
        platform, encoding, language, name_id, length, offset = struct.unpack_from('>HHHHHH', original_names, 6 + 12 * i)
        data = original_names[u16(original_names, 4) + offset: u16(original_names, 4) + offset + length]
        try:
            text = data.decode('utf-16-be' if platform in (0, 3) else 'mac-roman')
        except UnicodeError:
            continue
        names_by_id.setdefault(name_id, set()).add(text)
    copyright_text = '\n'.join(sorted(names_by_id.get(0, set())))
    assert copyright_text, 'preserve original copyright notices'
    license_text = a.license.read_text()
    names = {0: copyright_text, 1: 'Shanhai Rare Han', 2: 'Regular',
             3: 'ShanhaiRareHan-Regular-1.0', 4: 'Shanhai Rare Han Regular',
             5: 'Version 1.0', 6: 'ShanhaiRareHan-Regular',
             10: f'Modified {a.date}: subset to '+', '.join(f'U+{cp:04X}' for cp in sorted(mapping))+'. Renumbered glyphs and metrics; font family renamed Shanhai Rare Han. Original glyph outlines and hint programs retained. Freely available under the Arphic Public License; see ARPHICPL.TXT beside this file.',
             13: license_text, 14: 'https://ftp.gnu.org/non-gnu/chinese-fonts-truetype/LICENSE'}
    strings, records = bytearray(), bytearray()
    for key, text in sorted(names.items()):
        encoded = text.encode('utf-16-be')
        records.extend(struct.pack('>HHHHHH', 3, 1, 0x409, key, len(encoded), len(strings)))
        strings.extend(encoded)
    out[b'name'] = struct.pack('>HHH', 0, len(names), 6 + len(records)) + records + strings
    post = bytearray(tables[b'post'][:32])
    struct.pack_into('>I', post, 0, 0x00030000)
    out[b'post'] = post
    tags = sorted(out)
    power = 2 ** int(math.log2(len(tags)))
    header = struct.pack('>IHHHH', 0x00010000, len(tags), power * 16, int(math.log2(power)), len(tags) * 16 - power * 16)
    directory, payload = bytearray(), bytearray()
    head_at = None
    for tag in tags:
        data = bytes(out[tag])
        at = 12 + 16 * len(tags) + len(payload)
        directory.extend(struct.pack('>4sIII', tag, checksum(data), at, len(data)))
        if tag == b'head':
            head_at = at
        payload.extend(padded(data))
    output = bytearray(header + directory + payload)
    struct.pack_into('>I', output, head_at + 8, (0xb1b0afba - checksum(output)) & 0xffffffff)
    assert checksum(output) == 0xb1b0afba
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(output)
    report = {'sourceBytes': len(source), 'sourceSha256': hashlib.sha256(source).hexdigest(),
              'outputBytes': len(output), 'outputSha256': hashlib.sha256(output).hexdigest(),
              'family': names[1], 'characters': a.text, 'glyphsIncludingComponents': len(kept),
              'modified': a.date, 'license': 'Arphic Public License', 'checksumsVerified': True}
    a.output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
