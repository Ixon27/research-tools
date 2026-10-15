"""Fill text into an existing HWP 5.x form.

Only replaces text of existing paragraphs (no row/paragraph insertion).
All HWPTAG_PARA_LINE_SEG records are dropped and nLineSegs set to 0 so that
Hangul recomputes the layout on open (same shape as previously accepted output).
"""
import struct, zlib, olefile
from cfb import write_cfb

TAG_PARA_HEADER = 66
TAG_PARA_TEXT = 67
TAG_PARA_CHAR_SHAPE = 68
TAG_PARA_LINE_SEG = 69

CTRL_EXT = {1, 2, 3, 11, 12, 14, 15, 16, 17, 18}
CTRL_INLINE8 = {4, 5, 6, 7, 8, 9}


def _parse(buf):
    recs = []
    i, n = 0, len(buf)
    while i + 4 <= n:
        h = struct.unpack('<I', buf[i:i + 4])[0]
        tag, level, size = h & 0x3FF, (h >> 10) & 0x3FF, (h >> 20) & 0xFFF
        p = i + 4
        if size == 0xFFF:
            size = struct.unpack('<I', buf[p:p + 4])[0]
            p += 4
        recs.append([tag, level, bytearray(buf[p:p + size])])
        i = p + size
    return recs


def _serialize(recs):
    out = bytearray()
    for tag, level, payload in recs:
        size = len(payload)
        if size >= 0xFFF:
            out += struct.pack('<I', (tag & 0x3FF) | ((level & 0x3FF) << 10) | (0xFFF << 20))
            out += struct.pack('<I', size)
        else:
            out += struct.pack('<I', (tag & 0x3FF) | ((level & 0x3FF) << 10) | (size << 20))
        out += payload
    return bytes(out)


def decode_text(payload):
    """UTF-16 units -> readable text; control chars become '\\ufffc'."""
    out, i, n = [], 0, len(payload)
    while i + 2 <= n:
        c = struct.unpack('<H', payload[i:i + 2])[0]
        if c in CTRL_EXT or c in CTRL_INLINE8:
            out.append('￼'); i += 16; continue
        if c == 10:
            out.append('\n'); i += 2; continue
        if c == 13:
            i += 2; continue          # paragraph terminator
        if c < 32:
            i += 2; continue
        out.append(chr(c)); i += 2
    return ''.join(out)


def has_control(payload):
    i, n = 0, len(payload)
    while i + 2 <= n:
        c = struct.unpack('<H', payload[i:i + 2])[0]
        if c in CTRL_EXT or c in CTRL_INLINE8:
            return True
        i += 2
    return False


class Section:
    def __init__(self, raw):
        self.recs = _parse(raw)
        self._index()

    def _index(self):
        """paragraphs: list of dicts {hdr, text, cs, ls} -> record indexes"""
        self.paras = []
        cur = None
        for i, (tag, level, payload) in enumerate(self.recs):
            if tag == TAG_PARA_HEADER:
                cur = {'hdr': i, 'text': None, 'cs': None, 'ls': None}
                self.paras.append(cur)
            elif cur is not None and tag == TAG_PARA_TEXT and cur['text'] is None:
                cur['text'] = i
            elif cur is not None and tag == TAG_PARA_CHAR_SHAPE and cur['cs'] is None:
                cur['cs'] = i
            elif cur is not None and tag == TAG_PARA_LINE_SEG and cur['ls'] is None:
                cur['ls'] = i

    def text(self, pi):
        t = self.paras[pi]['text']
        return '' if t is None else decode_text(self.recs[t][2])

    def texts(self):
        return [self.text(i) for i in range(len(self.paras))]

    def set_text(self, pi, s):
        p = self.paras[pi]
        hidx = p['hdr']
        hdr = self.recs[hidx][2]
        old_nchars = struct.unpack('<I', hdr[0:4])[0]
        msb = old_nchars & 0x80000000

        if p['text'] is not None and has_control(self.recs[p['text']][2]):
            raise ValueError(f'paragraph {pi} contains control chars; refusing to overwrite')

        if s == '':
            self._clear_text(pi)
            return

        payload = bytearray()
        for ch in s:
            payload += struct.pack('<H', 10 if ch == '\n' else ord(ch))
        payload += struct.pack('<H', 13)          # paragraph terminator
        nchars = len(payload) // 2

        # char shapes: keep entries that still start inside the new text
        cs_idx = p['cs']
        if cs_idx is not None:
            cs = self.recs[cs_idx][2]
            pairs = [struct.unpack('<II', cs[i:i + 8]) for i in range(0, len(cs), 8)]
        else:
            pairs = [(0, 0)]
        pairs = [(st, sh) for st, sh in pairs if st < nchars] or [(0, pairs[0][1])]
        if pairs[0][0] != 0:
            pairs[0] = (0, pairs[0][1])
        newcs = bytearray()
        for st, sh in pairs:
            newcs += struct.pack('<II', st, sh)

        # write header fields
        struct.pack_into('<I', hdr, 0, msb | nchars)
        struct.pack_into('<I', hdr, 4, 0)              # control mask
        struct.pack_into('<H', hdr, 12, len(pairs))    # nCharShapes
        struct.pack_into('<H', hdr, 14, 0)             # nRangeTags
        struct.pack_into('<H', hdr, 16, 0)             # nLineSegs

        if cs_idx is not None:
            self.recs[cs_idx][2] = newcs
        if p['text'] is not None:
            self.recs[p['text']][2] = payload
        else:
            lvl = self.recs[hidx][1]
            self.recs.insert(hidx + 1, [TAG_PARA_TEXT, lvl + 1, payload])
            self._index()
            p = self.paras[pi]
            if p['cs'] is None:
                self.recs.insert(p['text'] + 1, [TAG_PARA_CHAR_SHAPE, lvl + 1, newcs])
                self._index()

    def _clear_text(self, pi):
        """Empty a paragraph the way Hangul stores one: no HWPTAG_PARA_TEXT at
        all, nChars = 1 (the implicit terminator), a single char shape at 0.
        Writing a record holding just CR instead makes Hangul refuse the file."""
        p = self.paras[pi]
        hdr = self.recs[p['hdr']][2]
        msb = struct.unpack('<I', hdr[0:4])[0] & 0x80000000

        cs_idx = p['cs']
        if cs_idx is not None:
            cs = self.recs[cs_idx][2]
            shape = struct.unpack('<II', cs[0:8])[1] if len(cs) >= 8 else 0
            self.recs[cs_idx][2] = bytearray(struct.pack('<II', 0, shape))

        struct.pack_into('<I', hdr, 0, msb | 1)
        struct.pack_into('<I', hdr, 4, 0)              # control mask
        struct.pack_into('<H', hdr, 12, 1)             # nCharShapes
        struct.pack_into('<H', hdr, 14, 0)             # nRangeTags
        struct.pack_into('<H', hdr, 16, 0)             # nLineSegs

        if p['text'] is not None:
            del self.recs[p['text']]
        self._index()

    def drop_line_segs(self):
        keep = [r for r in self.recs if r[0] != TAG_PARA_LINE_SEG]
        self.recs = keep
        for tag, level, payload in self.recs:
            if tag == TAG_PARA_HEADER:
                struct.pack_into('<H', payload, 16, 0)
        self._index()

    def serialize(self):
        return _serialize(self.recs)


class HwpDoc:
    def __init__(self, path):
        ole = olefile.OleFileIO(path)
        self.streams = {'/'.join(e): ole.openstream(e).read()
                        for e in ole.listdir(streams=True, storages=False)}
        self.storages = ['/'.join(e) for e in ole.listdir(streams=False, storages=True)]
        ole.close()
        flags = struct.unpack('<I', self.streams['FileHeader'][36:40])[0]
        self.compressed = bool(flags & 1)
        self.sections = {}
        for k in sorted(self.streams):
            if k.startswith('BodyText/'):
                raw = zlib.decompress(self.streams[k], -15) if self.compressed else self.streams[k]
                self.sections[k] = Section(raw)

    def save(self, path):
        for k, sec in self.sections.items():
            raw = sec.serialize()
            if self.compressed:
                co = zlib.compressobj(9, zlib.DEFLATED, -15)
                raw = co.compress(raw) + co.flush()
            self.streams[k] = raw
        # PrvText: plain preview text; keep as-is (Hangul regenerates it)
        data = write_cfb(self.streams, self.storages)
        with open(path, 'wb') as f:
            f.write(data)
