"""Minimal CFB (OLE2 / Compound File Binary) v3 writer.

Enough to rebuild an HWP 5.x container: storages + streams, mini stream, MiniFAT,
FAT (<=109 sectors so no DIFAT sectors needed).
"""
import struct

SECTOR = 512
MINISECTOR = 64
MINI_CUTOFF = 4096
FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD
DIFSECT = 0xFFFFFFFC
NOSTREAM = 0xFFFFFFFF


def _dir_sort_key(name):
    u = name.upper()
    return (len(u), [ord(c) for c in u])


class Entry:
    def __init__(self, name, etype, data=b''):
        self.name = name
        self.type = etype          # 1 storage, 2 stream, 5 root
        self.data = data
        self.children = []
        self.left = NOSTREAM
        self.right = NOSTREAM
        self.child = NOSTREAM
        self.start = ENDOFCHAIN
        self.size = 0
        self.idx = -1
        self.color = 1             # 0 red, 1 black


def _build_tree(idxs, entries, depth=0, depths=None):
    """idxs: list of entry indexes sorted by CFB rule -> balanced BST root.

    Records each node's depth so the caller can paint a valid red-black tree.
    """
    if not idxs:
        return NOSTREAM
    mid = len(idxs) // 2
    root = idxs[mid]
    if depths is not None:
        depths[root] = depth
    entries[root].left = _build_tree(idxs[:mid], entries, depth + 1, depths)
    entries[root].right = _build_tree(idxs[mid + 1:], entries, depth + 1, depths)
    return root


def _paint(depths, entries):
    """Midpoint-built trees have all leaves at depth d or d-1, so painting the
    deepest level red and the rest black satisfies the red-black invariants.
    Hangul rejects an all-black tree whose paths differ in black height."""
    if not depths:
        return
    deepest = max(depths.values())
    for idx, d in depths.items():
        entries[idx].color = 0 if d == deepest else 1


def write_cfb(streams, storages=()):
    """streams: dict 'A/B' -> bytes ; storages: iterable of storage paths.
    Returns the CFB file bytes."""
    root = Entry('Root Entry', 5)
    nodes = {'': root}

    def get_storage(path):
        if path in nodes:
            return nodes[path]
        parent_path, _, name = path.rpartition('/')
        parent = get_storage(parent_path) if parent_path else root
        e = Entry(name, 1)
        parent.children.append(e)
        nodes[path] = e
        return e

    for sp in storages:
        get_storage(sp)
    for path, data in streams.items():
        parent_path, _, name = path.rpartition('/')
        parent = get_storage(parent_path) if parent_path else root
        e = Entry(name, 2, data)
        parent.children.append(e)

    # flatten, assign indexes (root first)
    flat = []

    def walk(e):
        e.idx = len(flat)
        flat.append(e)
        for c in e.children:
            walk(c)

    walk(root)

    for e in flat:
        if e.children:
            idxs = sorted((c.idx for c in e.children),
                          key=lambda i: _dir_sort_key(flat[i].name))
            depths = {}
            e.child = _build_tree(idxs, flat, 0, depths)
            _paint(depths, flat)

    # ---- split streams into mini / big
    big, mini = [], []
    for e in flat:
        if e.type != 2:
            continue
        (mini if len(e.data) < MINI_CUTOFF else big).append(e)

    # ---- mini stream + minifat
    ministream = bytearray()
    minifat = []
    for e in mini:
        n = (len(e.data) + MINISECTOR - 1) // MINISECTOR
        e.size = len(e.data)
        if n == 0:
            e.start = ENDOFCHAIN
            continue
        e.start = len(ministream) // MINISECTOR
        for k in range(n):
            minifat.append(e.start + k + 1 if k < n - 1 else ENDOFCHAIN)
        ministream += e.data
        pad = -len(ministream) % MINISECTOR
        ministream += b'\0' * pad
    ministream = bytes(ministream)

    minifat_bytes = b''.join(struct.pack('<I', v) for v in minifat)
    pad = -len(minifat_bytes) % SECTOR
    minifat_bytes += b'\xff' * pad          # pad with FREESECT
    n_minifat_sect = len(minifat_bytes) // SECTOR

    # ---- directory bytes (built after sector assignment for start fields)
    n_dir_entries = len(flat)
    n_dir_sect = ((n_dir_entries * 128) + SECTOR - 1) // SECTOR

    # ---- sector allocation
    def nsect(nbytes):
        return (nbytes + SECTOR - 1) // SECTOR

    payloads = []   # (kind, ref, nsectors)
    for e in big:
        e.size = len(e.data)
        payloads.append(('stream', e, nsect(len(e.data))))
    ms_sect = nsect(len(ministream))
    payloads.append(('ministream', root, ms_sect))
    payloads.append(('minifat', None, n_minifat_sect))
    payloads.append(('dir', None, n_dir_sect))

    total_payload = sum(n for _, _, n in payloads)

    # solve for number of FAT sectors
    n_fat = 1
    while True:
        total = total_payload + n_fat
        need = (total + 127) // 128
        if need <= n_fat:
            break
        n_fat += 1
    if n_fat > 109:
        raise ValueError('DIFAT sectors needed - not supported')

    total_sectors = total_payload + n_fat
    fat = [FREESECT] * (n_fat * 128)

    cur = 0
    chains = {}
    for kind, ref, n in payloads:
        if n == 0:
            chains[(kind, id(ref))] = ENDOFCHAIN
            continue
        start = cur
        for k in range(n):
            fat[cur + k] = cur + k + 1 if k < n - 1 else ENDOFCHAIN
        cur += n
        chains[(kind, id(ref))] = start
        if kind == 'stream':
            ref.start = start

    fat_start = cur
    for k in range(n_fat):
        fat[fat_start + k] = FATSECT
    cur += n_fat
    assert cur == total_sectors

    root.start = chains[('ministream', id(root))]
    root.size = len(ministream)
    minifat_start = chains[('minifat', id(None))] if n_minifat_sect else ENDOFCHAIN
    dir_start = chains[('dir', id(None))]

    # ---- directory bytes
    dirbuf = bytearray()
    for e in flat:
        nm = e.name.encode('utf-16le') + b'\0\0'
        if len(nm) > 64:
            raise ValueError('name too long: ' + e.name)
        b = bytearray(128)
        b[0:len(nm)] = nm
        struct.pack_into('<H', b, 64, len(nm))
        b[66] = e.type
        b[67] = e.color
        struct.pack_into('<III', b, 68, e.left, e.right, e.child)
        # CLSID 80..96, state 96, ctime 100, mtime 108 -> zeros
        struct.pack_into('<I', b, 116, e.start if e.type != 1 else 0)
        struct.pack_into('<Q', b, 120, e.size if e.type != 1 else 0)
        dirbuf += b
    pad = -len(dirbuf) % SECTOR
    dirbuf += b'\0' * pad

    # ---- header
    hdr = bytearray(SECTOR)
    hdr[0:8] = bytes.fromhex('d0cf11e0a1b11ae1')
    struct.pack_into('<H', hdr, 24, 0x003E)   # minor
    struct.pack_into('<H', hdr, 26, 0x0003)   # major
    struct.pack_into('<H', hdr, 28, 0xFFFE)   # byte order
    struct.pack_into('<H', hdr, 30, 9)        # sector shift
    struct.pack_into('<H', hdr, 32, 6)        # mini sector shift
    struct.pack_into('<I', hdr, 40, 0)        # num dir sectors (v3: 0)
    struct.pack_into('<I', hdr, 44, n_fat)
    struct.pack_into('<I', hdr, 48, dir_start)
    struct.pack_into('<I', hdr, 52, 0)        # transaction
    struct.pack_into('<I', hdr, 56, MINI_CUTOFF)
    struct.pack_into('<I', hdr, 60, minifat_start)
    struct.pack_into('<I', hdr, 64, n_minifat_sect)
    struct.pack_into('<I', hdr, 68, ENDOFCHAIN)  # first DIFAT
    struct.pack_into('<I', hdr, 72, 0)           # num DIFAT sectors
    for i in range(109):
        v = fat_start + i if i < n_fat else FREESECT
        struct.pack_into('<I', hdr, 76 + 4 * i, v)

    # ---- assemble
    out = bytearray(hdr)
    body = bytearray(total_sectors * SECTOR)

    def put(start, data):
        n = nsect(len(data))
        buf = data + b'\0' * (n * SECTOR - len(data))
        body[start * SECTOR:(start + n) * SECTOR] = buf

    for kind, ref, n in payloads:
        if n == 0:
            continue
        s = chains[(kind, id(ref))]
        if kind == 'stream':
            put(s, ref.data)
        elif kind == 'ministream':
            put(s, ministream)
        elif kind == 'minifat':
            put(s, minifat_bytes)
        elif kind == 'dir':
            put(s, bytes(dirbuf))

    fatbytes = b''.join(struct.pack('<I', v) for v in fat)
    put(fat_start, fatbytes)

    out += body
    return bytes(out)
