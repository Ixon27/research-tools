import sys, struct
from hwplib import *

path = sys.argv[1]
streams = read_streams(path)
zipped = is_compressed(path)
print('compressed:', zipped)
hdr = streams['FileHeader']
print('signature:', hdr[:32])
print('version:', hdr[32:36].hex(), struct.unpack('<4B', hdr[32:36]))

for s in sorted(k for k in streams if k.startswith('BodyText/')):
    raw = decomp(streams[s]) if zipped else streams[s]
    recs = parse_records(raw)
    print('===', s, len(raw), 'records', len(recs))
    cur = None
    for idx, (tag, level, a, b, h) in enumerate(recs):
        if tag == TAG_PARA_HEADER:
            p = raw[a:b]
            nchars = struct.unpack('<I', p[0:4])[0]
            ctrlmask = struct.unpack('<I', p[4:8])[0]
            pshape = struct.unpack('<H', p[8:10])[0]
            style = p[10]; coltype = p[11]
            ncs, nrt, nls = struct.unpack('<HHH', p[12:18])
            print(f'#{idx} PARA_HEADER L{level} len={b-a} nchars={nchars} ctrl={ctrlmask:#x} pshape={pshape} style={style} ncs={ncs} nrt={nrt} nls={nls} rest={p[18:].hex()}')
        elif tag == TAG_PARA_TEXT:
            print(f'   #{idx} TEXT len={b-a} {para_text(raw[a:b])!r}')
        elif tag == TAG_PARA_CHAR_SHAPE:
            p = raw[a:b]
            pairs = [struct.unpack('<II', p[i:i+8]) for i in range(0, len(p), 8)]
            print(f'   #{idx} CHAR_SHAPE {pairs}')
        elif tag == TAG_PARA_LINE_SEG:
            p = raw[a:b]
            n = len(p)//36
            segs = []
            for i in range(n):
                q = p[i*36:(i+1)*36]
                segs.append(struct.unpack('<iiiiiiihhi', q[:34] + q[34:36] if False else q[:36])[:1])
            print(f'   #{idx} LINE_SEG bytes={len(p)} nseg={len(p)/36:.2f}')
        else:
            print(f'   #{idx} tag={tag} L{level} len={b-a}')
