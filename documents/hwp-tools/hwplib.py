"""Minimal HWP 5.x reader/writer helpers.

Read: OLE streams -> BodyText/SectionN (raw deflate, wbits=-15) -> record stream.
Records: header uint32 = tag(10bit) | level(10bit) | size(12bit); size==0xFFF -> next uint32 is real size.
"""
import olefile, zlib, struct, sys

HWPTAG_BEGIN = 0x10
TAG_PARA_HEADER = HWPTAG_BEGIN + 50   # 66
TAG_PARA_TEXT = HWPTAG_BEGIN + 51     # 67
TAG_PARA_CHAR_SHAPE = HWPTAG_BEGIN + 52
TAG_PARA_LINE_SEG = HWPTAG_BEGIN + 53
TAG_CTRL_HEADER = HWPTAG_BEGIN + 55
TAG_LIST_HEADER = HWPTAG_BEGIN + 56
TAG_TABLE = HWPTAG_BEGIN + 71

CTRL_INLINE = {4, 5, 6, 7, 8, 9, 19, 20, 21, 22, 23}
CTRL_EXTEND = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18}


def is_compressed(path):
    ole = olefile.OleFileIO(path)
    hdr = ole.openstream('FileHeader').read()
    flags = struct.unpack('<I', hdr[36:40])[0]
    ole.close()
    return bool(flags & 1)


def read_streams(path):
    ole = olefile.OleFileIO(path)
    out = {}
    for entry in ole.listdir(streams=True, storages=False):
        out['/'.join(entry)] = ole.openstream(entry).read()
    ole.close()
    return out


def decomp(data):
    return zlib.decompress(data, -15)


def comp(data):
    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    return co.compress(data) + co.flush()


def parse_records(buf):
    """-> list of (tag, level, payload_start, payload_end, header_start)"""
    recs = []
    i = 0
    n = len(buf)
    while i + 4 <= n:
        hdr = struct.unpack('<I', buf[i:i + 4])[0]
        tag = hdr & 0x3FF
        level = (hdr >> 10) & 0x3FF
        size = (hdr >> 20) & 0xFFF
        p = i + 4
        if size == 0xFFF:
            size = struct.unpack('<I', buf[p:p + 4])[0]
            p += 4
        recs.append((tag, level, p, p + size, i))
        i = p + size
    return recs


def para_text(payload):
    """Decode HWPTAG_PARA_TEXT payload into plain text (controls -> placeholder)."""
    out = []
    i = 0
    n = len(payload)
    while i + 2 <= n:
        code = struct.unpack('<H', payload[i:i + 2])[0]
        if code in CTRL_INLINE:
            i += 16 if code in (4, 5, 6, 7, 8, 9) else 2
            out.append('￼') if False else None
            continue
        if code in CTRL_EXTEND:
            out.append('￼')  # object anchor (table, picture, ...)
            i += 16
            continue
        if code == 10:
            out.append('\n'); i += 2; continue
        if code == 13:
            out.append('\n'); i += 2; continue
        if code == 24:
            out.append('-'); i += 2; continue
        if code == 30 or code == 31:
            out.append(' '); i += 2; continue
        if code < 32:
            i += 2; continue
        out.append(chr(code))
        i += 2
    return ''.join(out)


def dump_text(path):
    streams = read_streams(path)
    zipped = is_compressed(path)
    secs = sorted(k for k in streams if k.startswith('BodyText/'))
    result = []
    for s in secs:
        raw = decomp(streams[s]) if zipped else streams[s]
        result.append((s, raw))
    return result


if __name__ == '__main__':
    for path in sys.argv[1:]:
        print('=' * 20, path)
        for name, raw in dump_text(path):
            print('---', name, len(raw))
            for tag, level, a, b, h in parse_records(raw):
                if tag == TAG_PARA_TEXT:
                    t = para_text(raw[a:b])
                    print(f'[L{level}] {t!r}')
