#!/usr/bin/env python3
"""
dds3tool - list, extract and patch Atlus DDS3.IMG / DDS3.DDT archives
(Nocturne, Digital Devil Saga 1/2, Devil Summoner 1/2 on PS2).

DDT format (little-endian), a tree of 12-byte entries:
    u32 name_offset   byte offset of a NUL-terminated name in the DDT
    u32 data          directory: byte offset of its first child entry in the DDT
                      file:      2048-byte sector index into the IMG
    s32 size          directory: -(number of children)
                      file:      size in bytes
The root entry is at offset 0 and has an empty name.

Commands:
    dds3tool.py list    DDS3.DDT [PREFIX...]
    dds3tool.py extract DDS3.DDT DDS3.IMG OUTDIR [PREFIX...]
    dds3tool.py patch   DDS3.DDT DDS3.IMG MODDIR OUTDIR [--in-place]
    dds3tool.py isopatch GAME.iso MODDIR OUT.iso [--append]  (recommended for PCSX2)
    dds3tool.py reskin DS2_DIR NOCTURNE_DIR NOCTURNE_ID DS2_ID MODDIR [--move-from SLOT]
    dds3tool.py add-demon DS2_DIR NOCTURNE_DIR NOCTURNE_ID TEMPLATE_ID RESERVE_ID NAME MODDIR [--level N]
    dds3tool.py menu-model PROGRAM_FILE MODDIR ID [ID ...]
    dds3tool.py names  DS2_DIR [MODDIR]
    dds3tool.py rename DS2_DIR MODDIR ID=Name [ID=Name ...]
    dds3tool.py locks DS2_DIR [MODDIR]
    dds3tool.py compare DS2_DIR NOCTURNE_DIR NOCTURNE_ID DS2_ID
    dds3tool.py set-level DS2_DIR MODDIR ID=LEVEL [...]
    dds3tool.py unlock DS2_DIR MODDIR ID [ID ...]
    dds3tool.py bases  DS2_DIR                          (which demons make good reskin bases)
    dds3tool.py templates DS2_DIR NOCTURNE_DIR NOCTURNE_ID   (rank DS2 templates for a model)
    dds3tool.py motions    MODEL.PB [...]                (list animation slots)
    dds3tool.py motion-alias IN.PB OUT.PB SLOT=SOURCE ...
    dds3tool.py set-class DS2_DIR MODDIR ID=VALUE|ID=like:ID ...
    dds3tool.py bones      MODEL.PB                      (list a skeleton)
    dds3tool.py mht-list   FILE.MHT
    dds3tool.py mht-bones  IN.MHT OUT.MHT RECORD=BONE ...
    dds3tool.py lb-list    FILE.LB
    dds3tool.py lb-extract FILE.LB OUTDIR
    dds3tool.py lb-replace IN.LB INDEX NEWFILE [INDEX NEWFILE ...] OUT.LB

`patch` replaces every file found under MODDIR (mirroring the archive paths,
e.g. MODDIR/model/devil/000.PB). Files that still fit in their original
sectors are overwritten in place; larger files are appended to the end of the
IMG and their DDT entry is updated. Without --in-place, the IMG and DDT are
written to OUTDIR (the IMG copy is instant on APFS).
"""

import os
import shutil
import struct
import sys

SECTOR = 2048


class Entry:
    __slots__ = ("path", "entry_offset", "sector", "size")

    def __init__(self, path, entry_offset, sector, size):
        self.path = path
        self.entry_offset = entry_offset
        self.sector = sector
        self.size = size


def read_ddt(ddt_path):
    return parse_ddt(open(ddt_path, "rb").read())


def parse_ddt(raw):
    data = bytearray(raw)

    def name_at(offset):
        end = data.index(0, offset)
        return data[offset:end].decode("ascii", "replace")

    files = []
    stack = [(0, "")]
    while stack:
        offset, parent = stack.pop()
        name_offset, value, size = struct.unpack_from("<IIi", data, offset)
        name = name_at(name_offset)
        path = f"{parent}/{name}" if name else parent
        if size < 0:
            for i in reversed(range(-size)):
                stack.append((value + 12 * i, path))
        else:
            files.append(Entry(path.lstrip("/"), offset, value, size))
    return data, files


def matches(path, prefixes):
    return not prefixes or any(path.startswith(p.lstrip("/")) for p in prefixes)


def cmd_list(args):
    _, files = read_ddt(args[0])
    shown = 0
    for f in files:
        if matches(f.path, args[1:]):
            print(f"{f.size:>10}  {f.path}")
            shown += 1
    print(f"{shown} file(s)", file=sys.stderr)


def cmd_extract(args):
    ddt, img, outdir, prefixes = args[0], args[1], args[2], args[3:]
    _, files = read_ddt(ddt)
    count = 0
    with open(img, "rb") as src:
        for f in files:
            if not matches(f.path, prefixes):
                continue
            dest = os.path.join(outdir, f.path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            src.seek(f.sector * SECTOR)
            with open(dest, "wb") as out:
                out.write(src.read(f.size))
            count += 1
    print(f"Extracted {count} file(s) to {outdir}")


def collect_replacements(files, moddir, allow_empty=False):
    """Map files under MODDIR (mirroring archive paths) to DDT entries."""
    by_path = {f.path.lower(): f for f in files}
    replacements = []
    for root, _, names in os.walk(moddir):
        for name in names:
            if name.startswith(".") or os.path.abspath(root) == os.path.abspath(moddir):
                continue  # top-level files replace files on the disc (see isopatch)
            full = os.path.join(root, name)
            rel = os.path.relpath(full, moddir).replace(os.sep, "/")
            entry = by_path.get(rel.lower())
            if entry is None:
                sys.exit(f"error: {rel} is not in the archive (new files need a DDT entry; not supported yet)")
            replacements.append((entry, full))
    if not replacements and not allow_empty:
        sys.exit("error: no replacement files found")
    return replacements


def cmd_patch(args):
    in_place = "--in-place" in args
    args = [a for a in args if a != "--in-place"]
    ddt_path, img_path, moddir, outdir = args[0], args[1], args[2], args[3]
    ddt, files = read_ddt(ddt_path)
    replacements = collect_replacements(files, moddir)

    if in_place:
        out_img, out_ddt = img_path, ddt_path
    else:
        os.makedirs(outdir, exist_ok=True)
        out_img = os.path.join(outdir, "DDS3.IMG")
        out_ddt = os.path.join(outdir, "DDS3.DDT")
        print("Copying DDS3.IMG ...")
        shutil.copyfile(img_path, out_img)

    with open(out_img, "r+b") as img:
        img.seek(0, os.SEEK_END)
        end = img.tell()
        if end % SECTOR:
            end += SECTOR - end % SECTOR
        for entry, path in replacements:
            new = open(path, "rb").read()
            old_sectors = (entry.size + SECTOR - 1) // SECTOR
            new_sectors = (len(new) + SECTOR - 1) // SECTOR
            if new_sectors <= old_sectors:
                sector = entry.sector
                where = "in place"
            else:
                sector = end // SECTOR
                end += new_sectors * SECTOR
                where = f"appended at sector {sector}"
            img.seek(sector * SECTOR)
            img.write(new + b"\0" * (new_sectors * SECTOR - len(new)))
            struct.pack_into("<Ii", ddt, entry.entry_offset + 4, sector, len(new))
            print(f"{entry.path}: {entry.size} -> {len(new)} bytes, {where}")

    with open(out_ddt, "wb") as f:
        f.write(ddt)
    print(f"Wrote {out_img} and {out_ddt}")


# ---------------------------------------------------------------- LB containers
#
# A .LB file (e.g. model_lb/devil_b/04A.LB, the model a demon uses in battle)
# is a list of entries, each starting on a 64-byte boundary:
#     u8 compressed(1)  u8 1  u8 index  u8 0
#     u32 entry size (16-byte header + packed data)
#     char[4] type ("PBN", "AT3", "MHT", "SMG", "TMXN", ...)
#     u32 unpacked size
# The list ends with an entry of type END0 (first byte 0xff), and the file is
# padded to 2048 bytes.
#
# Compression: a stream of opcodes. The top 3 bits pick the operation, the low
# 5 bits are a count N; N == 0 means a 16-bit count follows instead.
#     0  N literal bytes follow
#     1  N zero bytes
#     2  repeat the next byte N times
#     3  copy N bytes from D bytes back (D is one byte)
#     4  copy N bytes from D bytes back (D is two bytes)
#     5  N bytes follow, each written followed by a zero byte
# The byte 0xff ends the stream (the game decodes until it sees it).

LB_ALIGN = 64
MAX_DISTANCE = 1024   # largest back-reference Atlus's files use
MAX_RUN = 255         # longest run/copy we emit
MAX_LITERALS = 512


def lz_decompress(src, pos, size):
    out = bytearray()
    while True:
        op = src[pos]
        if op == 0xFF:  # end of stream
            break
        kind, n = op >> 5, op & 0x1F
        pos += 1
        if n == 0:
            n = src[pos] | src[pos + 1] << 8
            pos += 2
        if kind == 0:
            out += src[pos:pos + n]
            pos += n
        elif kind == 1:
            out += bytes(n)
        elif kind == 2:
            out += bytes([src[pos]]) * n
            pos += 1
        elif kind in (3, 4):
            if kind == 3:
                dist = src[pos]
                pos += 1
            else:
                dist = src[pos] | src[pos + 1] << 8
                pos += 2
            for _ in range(n):
                out.append(out[-dist])
        elif kind == 5:
            for b in src[pos:pos + n]:
                out += bytes((b, 0))
            pos += n
        else:
            raise ValueError(f"unknown LB opcode {op:#04x} at {pos - 1:#x}")
    if len(out) != size:
        raise ValueError("LB entry decompressed to the wrong size")
    return bytes(out)


def _op(kind, n):
    if n < 32:
        return bytes([kind << 5 | n])
    return bytes([kind << 5]) + struct.pack("<H", n)


_LZ_CACHE = {}


def lz_compress(data):
    """lz_compress_uncached, remembering the last results (the same model goes
    into both the battle and the field container)."""
    import hashlib
    key = hashlib.sha1(data).digest()
    if key not in _LZ_CACHE:
        if len(_LZ_CACHE) > 8:
            _LZ_CACHE.clear()
        _LZ_CACHE[key] = lz_compress_uncached(data)
    return _LZ_CACHE[key]


def lz_compress_uncached(data):
    """Compress in the LB format using an optimal parse over all opcodes.

    Stays within the limits Atlus's own compressor keeps to: back-references
    reach at most 1024 bytes (the game decodes through a 1 KB window) and
    runs/copies are kept short.
    """
    data = bytes(data)
    size = len(data)
    INF = float("inf")

    # Longest matches at every position: one with a 1-byte distance, one with
    # a 2-byte distance.
    heads = {}
    prev = [-1] * size
    short_m = [(0, 0)] * size
    long_m = [(0, 0)] * size
    for i in range(size - 2):
        key = data[i:i + 3]
        cand = heads.get(key, -1)
        prev[i] = cand
        heads[key] = i
        limit = min(MAX_RUN, size - i)
        best_s = best_l = (0, 0)
        tries = 0
        while cand >= 0 and i - cand <= MAX_DISTANCE and tries < 64:
            dist = i - cand
            cur = best_s if dist < 256 else best_l
            n = cur[0]
            if n < limit and data[cand:cand + n + 1] == data[i:i + n + 1]:
                lo, hi = n + 1, limit
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if data[cand:cand + mid] == data[i:i + mid]:
                        lo = mid
                    else:
                        hi = mid - 1
                if dist < 256:
                    best_s = (lo, dist)
                else:
                    best_l = (lo, dist)
            if best_s[0] == limit:
                break
            cand = prev[cand]
            tries += 1
        short_m[i], long_m[i] = best_s, best_l

    def ext(n):
        return 0 if n < 32 else 2

    # Backward DP. cost[i][s]: bytes to encode data[i:], s=1 if a literal
    # run is already open (so another literal costs 1 byte, not 2).
    cost0 = [0.0] * (size + 1)
    cost1 = [0.0] * (size + 1)
    tok = [None] * (size + 1)
    tok_cost = [INF] * (size + 1)
    run_len = [0] * (size + 1)
    pair_len = [0] * (size + 2)
    for i in range(size - 1, -1, -1):
        run_len[i] = run_len[i + 1] + 1 if i + 1 < size and data[i + 1] == data[i] else 1
        pair_len[i] = pair_len[i + 2] + 1 if i + 1 < size and data[i + 1] == 0 else 0
    for i in range(size - 1, -1, -1):
        best, pick = INF, None
        r = min(run_len[i], MAX_RUN)
        if r >= 2:
            for n in {r, min(r, 31)}:
                c = (1 if data[i] == 0 else 2) + ext(n) + cost0[i + n]
                if c < best:
                    best, pick = c, (1 if data[i] == 0 else 2, n, data[i])
        for kind, (n, dist) in ((3, short_m[i]), (4, long_m[i])):
            if n >= 3:
                for m in {n, min(n, 31)}:
                    c = (2 if kind == 3 else 3) + ext(m) + cost0[i + m]
                    if c < best:
                        best, pick = c, (kind, m, dist)
        k = min(pair_len[i], MAX_RUN // 2)
        if k >= 2:
            for m in {k, min(k, 31)}:
                c = 1 + ext(m) + m + cost0[i + 2 * m]
                if c < best:
                    best, pick = c, (5, m, None)
        tok[i], tok_cost[i] = pick, best
        cost1[i] = min(best, 1 + cost1[i + 1])
        cost0[i] = min(best, 2 + cost1[i + 1])

    # Walk the plan forward. A literal run continues while taking a literal is
    # no worse than the best token from inside the run.
    out = bytearray()
    literals = bytearray()

    def flush():
        for j in range(0, len(literals), MAX_LITERALS):
            part = literals[j:j + MAX_LITERALS]
            out.extend(_op(0, len(part)) + part)
        literals.clear()

    i = 0
    while i < size:
        lit = (1 if literals else 2) + cost1[i + 1]
        if tok[i] is None or lit < tok_cost[i]:
            literals.append(data[i])
            i += 1
            continue
        flush()
        kind, n, arg = tok[i]
        if kind == 1:
            out += _op(1, n)
            i += n
        elif kind == 2:
            out += _op(2, n) + bytes([arg])
            i += n
        elif kind == 3:
            out += _op(3, n) + bytes([arg])
            i += n
        elif kind == 4:
            out += _op(4, n) + struct.pack("<H", arg)
            i += n
        else:
            out += _op(5, n) + data[i:i + 2 * n:2]
            i += 2 * n
    flush()
    out.append(0xFF)  # end-of-stream marker; the game stops decoding here
    return bytes(out)


class LbEntry:
    def __init__(self, header, kind, data, packed=None):
        self.header = header  # original 16-byte header
        self.kind = kind
        self.data = data      # unpacked contents
        self._orig = data     # to tell whether it changed
        self.packed = packed  # original stored bytes, reused when unchanged


def read_lb(path):
    src = open(path, "rb").read()
    entries, pos = [], 0
    while pos + 16 <= len(src):
        header = src[pos:pos + 16]
        size, kind, unpacked = struct.unpack_from("<I4sI", src, pos + 4)
        kind = kind.rstrip(b"\0").decode("ascii", "replace")
        if kind == "END0" or size == 0:
            break
        if header[0] == 1:
            data = lz_decompress(src, pos + 16, unpacked)
        else:
            data = src[pos + 16:pos + 16 + unpacked]
        entries.append(LbEntry(header, kind, data, src[pos + 16:pos + size]))
        pos += size
        pos += -pos % LB_ALIGN
    return entries


def write_lb(path, entries):
    out = bytearray()
    for i, e in enumerate(entries):
        header = bytearray(e.header)
        if e.packed is not None and (e.data is e._orig or e.data == e._orig):
            packed = e.packed            # unchanged: keep the game's own bytes
        else:
            packed = lz_compress(e.data)
            header[0] = 1
        header[2] = i & 0xFF
        struct.pack_into("<I", header, 4, 16 + len(packed))
        struct.pack_into("<I", header, 12, len(e.data))
        out += header + packed
        out += bytes(-len(out) % LB_ALIGN)
    out += bytes([0xFF, 0, 0, 0]) + struct.pack("<I4sI", 16, b"END0", 0)
    out += bytes(-len(out) % SECTOR)
    with open(path, "wb") as f:
        f.write(out)
    return len(out)


def cmd_lb_list(args):
    for i, e in enumerate(read_lb(args[0])):
        print(f"{i:>3}  {e.kind:<5} {len(e.data):>9} bytes")


def cmd_lb_extract(args):
    src, outdir = args[0], args[1]
    os.makedirs(outdir, exist_ok=True)
    for i, e in enumerate(read_lb(src)):
        name = os.path.join(outdir, f"{i:02d}_{e.kind}.bin")
        with open(name, "wb") as f:
            f.write(e.data)
        print(name)


def cmd_lb_replace(args):
    """lb-replace IN.LB INDEX NEWFILE OUT.LB [INDEX NEWFILE ...]"""
    if len(args) < 4 or len(args) % 2:
        sys.exit("usage: dds3tool.py lb-replace IN.LB INDEX NEWFILE [INDEX NEWFILE ...] OUT.LB")
    src, out_path, pairs = args[0], args[-1], args[1:-1]
    entries = read_lb(src)
    for idx, new_file in zip(pairs[0::2], pairs[1::2]):
        idx = int(idx)
        if not 0 <= idx < len(entries):
            sys.exit(f"error: {src} has entries 0-{len(entries) - 1}")
        old = len(entries[idx].data)
        entries[idx].data = open(new_file, "rb").read()
        print(f"entry {idx} ({entries[idx].kind}): {old} -> {len(entries[idx].data)} bytes")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    print("Compressing ...")
    size = write_lb(out_path, entries)
    print(f"Wrote {out_path} ({size} bytes)")


# ---------------------------------------------------------------- Bones and hit data
#
# PB models: chunks of [u32 type][s32 size][4cc magic][u32 0], 64-byte aligned.
# MD00 holds the skeleton: node count at +0x30, then 0x50-byte nodes from +0x40:
#     u32 type, u32 flags, u32 index, s32 parent, f32 rot[3] (+0x10, applied
#     Z*Y*X), f32 pos[3] (+0x20), f32 scale[3] (+0x30).
# MHT hit data (battle/mdlhit/<ID>.MHT, also entry 2 of the battle LB):
#     u32 record count, then 148-byte records; the u32 at +8 is the bone the
#     hit sphere follows during attacks.

MHT_RECORD = 148


def pb_chunks(data):
    pos, found = 0, {}
    while pos + 16 <= len(data):
        kind, size, magic = struct.unpack_from("<Ii4s", data, pos)
        found[magic.decode("ascii", "replace")] = pos
        if kind == 255 or size <= 0:
            break
        pos += size
        pos += -pos % 64
    return found


def pb_skeleton(data):
    """Return [(parent, (x, y, z) rest-pose position)] for every node."""
    import math
    md = pb_chunks(data).get("MD00")
    if md is None:
        sys.exit("error: no MD00 (model) chunk in this file")
    count = struct.unpack_from("<I", data, md + 0x30)[0]
    nodes, world = [], []
    for i in range(count):
        rec = md + 0x40 + i * 0x50
        parent = struct.unpack_from("<i", data, rec + 12)[0]
        rx, ry, rz = struct.unpack_from("<3f", data, rec + 0x10)
        pos = struct.unpack_from("<3f", data, rec + 0x20)
        cx, sx, cy, sy, cz, sz = (math.cos(rx), math.sin(rx), math.cos(ry),
                                  math.sin(ry), math.cos(rz), math.sin(rz))
        rot = [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
               [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
               [-sy, cy * sx, cy * cx]]
        if parent < 0:
            world.append((rot, list(pos)))
        else:
            prot, ppos = world[parent]
            r = [[sum(prot[a][k] * rot[k][b] for k in range(3)) for b in range(3)] for a in range(3)]
            p = [ppos[a] + sum(prot[a][k] * pos[k] for k in range(3)) for a in range(3)]
            world.append((r, p))
        nodes.append((parent, tuple(world[-1][1])))
    return nodes


def cmd_bones(args):
    nodes = pb_skeleton(open(args[0], "rb").read())
    children = [0] * len(nodes)
    for parent, _ in nodes:
        if parent >= 0:
            children[parent] += 1
    print(f"{len(nodes)} bones (rest pose; negative Y is up)")
    print("bone parent kids        x       y       z")
    for i, (parent, (x, y, z)) in enumerate(nodes):
        print(f"{i:>4} {parent:>6} {children[i]:>4} {x:>8.1f}{y:>8.1f}{z:>8.1f}")


def mht_records(data):
    count = struct.unpack_from("<I", data)[0]
    return [(i, struct.unpack_from("<I", data, 4 + i * MHT_RECORD + 8)[0]) for i in range(count)]


def cmd_mht_list(args):
    for i, bone in mht_records(open(args[0], "rb").read()):
        print(f"record {i}: bone {bone}")


def cmd_mht_bones(args):
    """mht-bones IN.MHT OUT.MHT REC=BONE [REC=BONE ...]"""
    if len(args) < 3:
        sys.exit("usage: dds3tool.py mht-bones IN.MHT OUT.MHT RECORD=BONE [RECORD=BONE ...]")
    data = bytearray(open(args[0], "rb").read())
    count = struct.unpack_from("<I", data)[0]
    for pair in args[2:]:
        rec, bone = (int(v) for v in pair.split("="))
        if not 0 <= rec < count:
            sys.exit(f"error: {args[0]} has records 0-{count - 1}")
        off = 4 + rec * MHT_RECORD + 8
        old = struct.unpack_from("<I", data, off)[0]
        struct.pack_into("<I", data, off, bone)
        print(f"record {rec}: bone {old} -> {bone}")
    os.makedirs(os.path.dirname(os.path.abspath(args[1])), exist_ok=True)
    with open(args[1], "wb") as f:
        f.write(data)


# ---------------------------------------------------------------- Animation slots
#
# MT00 (animations): +0x10 u32 offset (from +0x20) of a small trailer at the
# end of the chunk, +0x14 u32 its length; +0x20 u16 slot count, u16 channel
# count, u32 size of the channel table (counted from +0x20). The slot table follows it: one u32 per
# slot, an offset from MT00+0x20 to that animation, or 0 for an empty slot.
# DS2 battle slots 9 and 10 look like walk/run: ground demons fill them,
# floating ones (and Nocturne models) leave them empty.

def motion_slots(data):
    mt = pb_chunks(data).get("MT00")
    if mt is None:
        return None, []
    count = struct.unpack_from("<H", data, mt + 0x20)[0]
    table = mt + 0x20 + struct.unpack_from("<I", data, mt + 0x24)[0]
    return table, list(struct.unpack_from(f"<{count}I", data, table))


def motion_frames(data, slot_offset):
    """Length in frames of the animation at a slot-table offset."""
    mt = pb_chunks(data)["MT00"]
    return struct.unpack_from("<I", data, mt + 0x20 + slot_offset)[0]


def pb_replace_chunk(data, magic, new_chunk):
    """Rebuild a PB with one chunk replaced (chunks stay 64-byte aligned)."""
    out, pos = bytearray(), 0
    while pos + 16 <= len(data):
        kind, size, m = struct.unpack_from("<Ii4s", data, pos)
        chunk = new_chunk if m.decode("ascii", "replace") == magic else data[pos:pos + size]
        out += chunk
        out += bytes(-len(out) % 64)
        if kind == 255 or size <= 0:
            break
        pos += size
        pos += -pos % 64
    return bytes(out)


def extend_motion_slots(model, count):
    """Grow MT00's slot table to COUNT entries (new ones empty).

    DS2 models have 17 animation slots, Nocturne models 16; DS2 code that asks
    for slot 16 would otherwise read past the end of a Nocturne table.
    The animation data moves down 16 bytes, keeping its alignment.
    """
    table, slots = motion_slots(model)
    if table is None or count <= len(slots):
        return bytes(model)
    mt = pb_chunks(model)["MT00"]
    size = struct.unpack_from("<i", model, mt + 4)[0]
    chunk = bytearray(model[mt:mt + size])
    tpos = table - mt
    old_end = tpos + 4 * len(slots)
    shift = (4 * (count - len(slots)) + 15) & ~15
    new_entries = [off + shift if off else 0 for off in slots] + [0] * (count - len(slots))
    trailer = struct.unpack_from("<I", chunk, 0x10)[0]   # see MT00 notes above
    chunk[old_end:old_end] = bytes(shift)
    struct.pack_into(f"<{count}I", chunk, tpos, *new_entries)
    struct.pack_into("<H", chunk, 0x20, count)
    struct.pack_into("<i", chunk, 4, len(chunk))
    struct.pack_into("<I", chunk, 0x10, trailer + shift)
    return pb_replace_chunk(bytes(model), "MT00", bytes(chunk))


def encode_reloc(positions):
    """MT00 ends with a packed list of the words the game turns from offsets into
    pointers at load time (the header's table offset and every non-empty slot).
    A slot missing from it stays a raw offset, and playing it reads garbage.
    Byte forms: even b = advance (b>>1) words; b&3==1 = 2-byte advance;
    b&7==3 = 3-byte advance; b&7==7 = ((b>>3)+2) consecutive words."""
    out = bytearray(); pos = 0; i = 0
    while i < len(positions):
        p = positions[i]; words = (p - pos) // 4
        if words == 1:
            run = 1
            while i + run < len(positions) and positions[i + run] - positions[i + run - 1] == 4 and run < 33:
                run += 1
            if run >= 2:
                out.append(((run - 2) << 3) | 7)
                pos = positions[i + run - 1]; i += run
                continue
        if words < 0x80:
            out.append(words << 1)
        elif words < 0x4000:
            out += struct.pack("<H", (words << 2) | 1)
        else:
            v = (words << 3) | 3
            out += bytes((v & 255, (v >> 8) & 255, (v >> 16) & 255))
        pos = p; i += 1
    return bytes(out)


def rebuild_motion_reloc(chunk):
    """Rewrite an MT00 chunk's relocation trailer to match its slot table (in place)."""
    trailer, length = struct.unpack_from("<II", chunk, 0x10)
    count = struct.unpack_from("<H", chunk, 0x20)[0]
    table = struct.unpack_from("<I", chunk, 0x24)[0]
    slots = struct.unpack_from(f"<{count}I", chunk, 0x20 + table)
    new = encode_reloc([4] + [table + 4 * i for i, off in enumerate(slots) if off])
    chunk[0x20 + trailer:0x20 + trailer + length] = new
    struct.pack_into("<I", chunk, 0x14, len(new))
    struct.pack_into("<i", chunk, 4, len(chunk))


def fill_motion_slots(model, base, source=None, extend=True, fill=True, share=False):
    """Fill slots that BASE uses but MODEL leaves empty.

    By default each one gets the model's animation closest in length to what
    the DS2 original plays there, so actions end when the game expects them
    to. With SOURCE, every such slot plays that slot instead. Each filled slot
    gets its own copy of the animation appended to the MT00 chunk: the game
    can't handle two slots pointing at the same animation data.
    An explicit SOURCE dictionary can remap occupied slots; None clears a slot.
    Returns (new model, [(slot, source slot)]).
    """
    if extend:
        model = extend_motion_slots(model, len(motion_slots(base)[1]))
    if not fill:
        return bytes(model), []
    table, slots = motion_slots(model)
    _, base_slots = motion_slots(base)
    filled = []
    if table is None:
        return bytes(model), filled
    used = [i for i, off in enumerate(slots) if off]
    if isinstance(source, dict):   # --map: exactly these slots, from these sources
        for dst, src in source.items():
            if (src is not None and src not in used) or not 0 <= dst < len(slots):
                sys.exit(f"error: --map {dst}={src}: source slot must hold an animation, "
                         f"target must be 0-{len(slots) - 1}")
        picks = sorted(source.items())
        used = []
    elif not used or (source is not None and source not in used):
        return bytes(model), filled
    else:
        picks = []
    for i in range(min(len(slots), len(base_slots)) if used else 0):
        if base_slots[i] and not slots[i]:
            if source is None:
                want = motion_frames(base, base_slots[i])
                pick = min(used, key=lambda j: abs(motion_frames(model, slots[j]) - want))
            else:
                pick = source
            picks.append((i, pick))
    if not picks:
        return bytes(model), filled

    if share:   # point the slots at the existing animations: no extra bytes
        mt = pb_chunks(model)["MT00"]
        size = struct.unpack_from("<i", model, mt + 4)[0]
        chunk = bytearray(model[mt:mt + size])
        for slot, pick in picks:
            struct.pack_into("<I", chunk, table - mt + 4 * slot, slots[pick] if pick is not None else 0)
            filled.append((slot, pick))
        rebuild_motion_reloc(chunk)
        return pb_replace_chunk(bytes(model), "MT00", bytes(chunk)), filled

    mt = pb_chunks(model)["MT00"]
    size = struct.unpack_from("<i", model, mt + 4)[0]
    chunk = bytearray(model[mt:mt + size])
    trailer = struct.unpack_from("<I", chunk, 0x10)[0]   # trailer offset (from +0x20)
    starts = sorted(set(off for off in slots if off))
    ends = dict(zip(starts, starts[1:] + [trailer]))
    tpos = table - mt
    insert_at = 0x20 + trailer
    added = bytearray()
    for slot, pick in picks:
        if pick is None:
            struct.pack_into("<I", chunk, tpos + 4 * slot, 0)
            filled.append((slot, pick))
            continue
        src = slots[pick]
        struct.pack_into("<I", chunk, tpos + 4 * slot, trailer + len(added))
        added += model[mt + 0x20 + src: mt + 0x20 + ends[src]]
        added += bytes(-len(added) % 16)
        filled.append((slot, pick))
    chunk[insert_at:insert_at] = added
    struct.pack_into("<I", chunk, 0x10, trailer + len(added))
    rebuild_motion_reloc(chunk)   # filled slots must be relocated too
    return pb_replace_chunk(bytes(model), "MT00", bytes(chunk)), filled


def cmd_motions(args):
    for path in args:
        data = open(path, "rb").read()
        _, slots = motion_slots(data)
        used = " ".join(f"{i}:{motion_frames(data, s)}" if s else f"{i}:-" for i, s in enumerate(slots))
        print(f"{path}: {len(slots)} slots (slot:frames)  {used}")


def cmd_compare(args):
    """compare DS2_DIR NOCTURNE_DIR NOCTURNE_ID DS2_ID - animation slots of both models side by side"""
    if len(args) != 4:
        sys.exit("usage: dds3tool.py compare DS2_DIR NOCTURNE_DIR NOCTURNE_ID DS2_ID")
    ds2_dir, noc_dir, noc_id, target = args[0], args[1], int(args[2], 16), args[3].upper()
    ds2 = read_archive_file(ds2_dir, f"model/devil/{target}.PB")
    noc = read_archive_file(noc_dir, find_nocturne_model(noc_dir, noc_id))
    _, a = motion_slots(ds2)
    _, b = motion_slots(noc)
    print(f"slot  DS2 {target}  Nocturne 0x{noc_id:x}   (frames, - = empty)")
    for i in range(max(len(a), len(b))):
        x = (str(motion_frames(ds2, a[i])) if a[i] else "-") if i < len(a) else ""
        y = (str(motion_frames(noc, b[i])) if b[i] else "-") if i < len(b) else ""
        flag = "   <-- missing" if x not in ("", "-") and y in ("", "-") else ""
        print(f"{i:4}  {x:>7}  {y:>13}{flag}")


def cmd_bases(args):
    """bases DS2_DIR - which playable DS2 demons walk in battle (slots 9/10)."""
    ds2_dir = args[0]
    files = game(ds2_dir).files
    tbl = bytearray(read_archive_file(ds2_dir, SB_DATA))
    base, count = find_name_table(tbl)
    models = {}
    for f in files:
        p = f.path.lower()
        if p.startswith("model/devil/") and p.endswith(".pb") and p.count("/") == 2:
            try:
                models[int(os.path.basename(p)[:-3], 16)] = f
            except ValueError:
                pass
    floaters, walkers = [], []
    if True:
        for demon in sorted(models):
            if not 0 < demon < 0xC0:
                continue
            f = models[demon]
            _, slots = motion_slots(game(ds2_dir).read(f))
            if len(slots) < 11:
                continue
            name = tbl[base + demon * NAME_LEN: base + (demon + 1) * NAME_LEN].split(b"\0")[0]
            entry = f"{demon:03X}  {name.decode('ascii', 'replace')}"
            (walkers if slots[9] or slots[10] else floaters).append(entry)
    print("Good reskin bases (no walk/run animations needed):")
    for e in floaters:
        print("   ", e)
    print("\nWalkers (Nocturne models will stand still in battle):")
    for e in walkers:
        print("   ", e)


def cmd_templates(args):
    """templates DS2_DIR NOCTURNE_DIR NOCTURNE_ID [N]

    Rank summonable DS2 demons as templates for a Nocturne model: the fewer
    animation slots the template uses that the model lacks, the better (an
    empty slot means that action plays nothing, e.g. no attack lunge).
    """
    if len(args) < 3:
        sys.exit("usage: dds3tool.py templates DS2_DIR NOCTURNE_DIR NOCTURNE_ID [HOW_MANY]")
    ds2_dir, noc_dir, noc_id = args[0], args[1], int(args[2], 16)
    show = int(args[3]) if len(args) > 3 else 15
    model = read_archive_file(noc_dir, find_nocturne_model(noc_dir, noc_id))
    _, mslots = motion_slots(model)
    have = {i for i, off in enumerate(mslots) if off}
    tbl = bytearray(read_archive_file(ds2_dir, SB_DATA))
    names, _ = find_name_table(tbl)
    motionmv = read_archive_file(ds2_dir, SB_MOTIONMV) if archive_has(ds2_dir, SB_MOTIONMV) else b""
    rows = []
    for demon in range(1, 0xC0):
        rel = f"model/devil/{demon:03X}.PB"
        if not archive_has(ds2_dir, rel):
            continue
        name = tbl[names + demon * NAME_LEN: names + (demon + 1) * NAME_LEN].split(b"\0")[0].decode("ascii", "replace")
        if not name or "reserve" in name.lower():
            continue
        _, bslots = motion_slots(read_archive_file(ds2_dir, rel))
        if len(bslots) < 11:
            continue
        missing = [i for i, off in enumerate(bslots) if off and i not in have]
        # Slots the template moves during (attack lunges) matter most.
        lunge = set()
        if motionmv:
            for k in range(8):
                slot = struct.unpack_from("<h", motionmv, 4 + demon * 64 + k * 8)[0]
                if slot >= 0:
                    lunge.add(slot)
        bad_lunge = sorted(lunge - have)
        level = struct.unpack_from("<H", tbl, 4 + demon * DATA_RECORD + 4)[0]
        rows.append((len(bad_lunge), len(missing), demon, name, level, missing, bad_lunge))
    rows.sort()
    print(f"Nocturne 0x{noc_id:X} has animation slots: {sorted(have)}")
    print("best templates (missing lunge slots, then missing slots):")
    for lunge_miss, miss, demon, name, level, missing, bad_lunge in rows[:show]:
        note = f"  lunge slots missing {bad_lunge}" if bad_lunge else ""
        print(f"  {demon:03X} {name:<16} L{level:<3} missing {missing or 'none'}{note}")


def cmd_motion_alias(args):
    """motion-alias IN.PB OUT.PB SLOT=SOURCE [...]"""
    if len(args) < 3:
        sys.exit("usage: dds3tool.py motion-alias IN.PB OUT.PB SLOT=SOURCE_SLOT [...]")
    data = bytearray(open(args[0], "rb").read())
    table, slots = motion_slots(data)
    for pair in args[2:]:
        dst, src = (int(v) for v in pair.split("="))
        if not (0 <= dst < len(slots) and 0 <= src < len(slots)) or not slots[src]:
            sys.exit(f"error: bad slots {pair} (model has {len(slots)}; source must not be empty)")
        struct.pack_into("<I", data, table + 4 * dst, slots[src])
        print(f"slot {dst} now plays slot {src}")
    mt = pb_chunks(bytes(data))["MT00"]
    chunk = bytearray(data[mt:mt + struct.unpack_from("<i", data, mt + 4)[0]])
    rebuild_motion_reloc(chunk)
    data = bytearray(pb_replace_chunk(bytes(data), "MT00", bytes(chunk)))
    with open(args[1], "wb") as f:
        f.write(data)


# ---------------------------------------------------------------- Demon names
#
# battle/SB_DATA.TBL holds a name table: a u32 section size (count * 21),
# then fixed 21-byte, NUL-padded ASCII names indexed by demon ID
# (0 = Raidou, 1 = Ukobach, ... 0x4A = Angel). IDs 0xC0 and up are enemies.

SB_DATA = "battle/SB_DATA.TBL"
NAME_LEN = 21


def find_name_table(tbl):
    pos = tbl.find(b"Raidou\0")
    while pos != -1:
        size = struct.unpack_from("<I", tbl, pos - 4)[0] if pos >= 4 else 0
        if size and size % NAME_LEN == 0 and pos + size <= len(tbl):
            return pos, size // NAME_LEN
        pos = tbl.find(b"Raidou\0", pos + 1)
    sys.exit("error: couldn't find the demon name table in SB_DATA.TBL")


def load_sb_data(ds2_dir, moddir):
    """SB_DATA.TBL from the mod folder if it was already changed, else from the game."""
    modded = os.path.join(moddir, SB_DATA)
    if os.path.exists(modded):
        return bytearray(open(modded, "rb").read())
    return bytearray(read_archive_file(ds2_dir, SB_DATA))


def cmd_names(args):
    """names DS2_DIR [MODDIR]  - list demon IDs and names"""
    tbl = load_sb_data(args[0], args[1] if len(args) > 1 else "")
    base, count = find_name_table(tbl)
    for i in range(count):
        name = tbl[base + i * NAME_LEN: base + (i + 1) * NAME_LEN].split(b"\0")[0]
        if name:
            print(f"{i:03X}  {name.decode('ascii', 'replace')}")


SB_VISUAL = "battle/SB_VISUAL.TBL"
VISUAL_RECORD = 492  # one per demon ID, after a u32 section size


def cmd_set_class(args):
    """set-class DS2_DIR MODDIR ID=VALUE|ID=like:OTHER_ID [...]

    Sets the first field of a demon's SB_VISUAL record (body class: 0x6 small,
    0x10a human-sized, 0x212 large, 0x322 huge; Angel is 0x106).
    """
    if len(args) < 3:
        sys.exit("usage: dds3tool.py set-class DS2_DIR MODDIR 0B5=0x10a  (or 0B5=like:04B, or 0B5=all:04B to copy the whole record)")
    ds2_dir, moddir = args[0], args[1]
    modded = os.path.join(moddir, SB_VISUAL)
    if os.path.exists(modded):
        tbl = bytearray(open(modded, "rb").read())
    else:
        tbl = bytearray(read_archive_file(ds2_dir, SB_VISUAL))
    count = struct.unpack_from("<I", tbl)[0] // VISUAL_RECORD

    def field(demon):
        if not 0 <= demon < count:
            sys.exit(f"error: demon IDs go from 000 to {count - 1:03X}")
        return 4 + demon * VISUAL_RECORD

    for pair in args[2:]:
        demon, value = pair.split("=", 1)
        demon = int(demon, 16)
        if value.startswith("all:"):
            src = field(int(value[4:], 16))
            dst = field(demon)
            tbl[dst:dst + VISUAL_RECORD] = tbl[src:src + VISUAL_RECORD]
            print(f"{demon:03X}: whole record copied from {int(value[4:], 16):03X}")
            continue
        if value.startswith("like:"):
            value = struct.unpack_from("<I", tbl, field(int(value[5:], 16)))[0]
        else:
            value = int(value, 0)
        old = struct.unpack_from("<I", tbl, field(demon))[0]
        struct.pack_into("<I", tbl, field(demon), value)
        print(f"{demon:03X}: class {old:#x} -> {value:#x}")
    os.makedirs(os.path.dirname(modded), exist_ok=True)
    with open(modded, "wb") as f:
        f.write(tbl)
    print(f"Wrote {modded}")


def cmd_rename(args):
    """rename DS2_DIR MODDIR ID=Name [ID=Name ...]"""
    if len(args) < 3:
        sys.exit('usage: dds3tool.py rename DS2_DIR MODDIR 04A=Principality ["0B5=Eligor" ...]')
    ds2_dir, moddir = args[0], args[1]
    tbl = load_sb_data(ds2_dir, moddir)
    base, count = find_name_table(tbl)
    for pair in args[2:]:
        demon, name = pair.split("=", 1)
        demon = int(demon, 16)
        raw = name.encode("ascii")
        if not 0 <= demon < count:
            sys.exit(f"error: demon IDs go from 000 to {count - 1:03X}")
        if len(raw) >= NAME_LEN:
            sys.exit(f"error: '{name}' is too long (max {NAME_LEN - 1} characters)")
        off = base + demon * NAME_LEN
        old = tbl[off:off + NAME_LEN].split(b"\0")[0].decode("ascii", "replace")
        tbl[off:off + NAME_LEN] = raw.ljust(NAME_LEN, b"\0")
        print(f"{demon:03X}: {old} -> {name}")
    dest = os.path.join(moddir, SB_DATA)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(tbl)
    print(f"Wrote {dest}")


# ---------------------------------------------------------------- Reskins

class GameSource:
    """A game's archive, read either from a folder holding DDS3.DDT + DDS3.IMG
    or straight out of the game's ISO (nothing gets extracted)."""

    def __init__(self, path):
        self.path = path
        self.iso_files = None
        if os.path.isfile(path):
            with open(path, "rb") as iso:
                self.iso_files = iso_list_files(iso)
                ddt, img = self.iso_files.get("DDS3.DDT"), self.iso_files.get("DDS3.IMG")
                if not ddt or not img:
                    sys.exit(f"error: {path} has no DDS3.DDT/DDS3.IMG (is it the right game?)")
                iso.seek(ddt.lsn * SECTOR)
                raw = iso.read(ddt.size)
            self.img_path, self.img_base = path, img.lsn * SECTOR
        else:
            ddt_path = os.path.join(path, "DDS3.DDT")
            if not os.path.exists(ddt_path):
                sys.exit(f"error: {ddt_path} not found")
            raw = open(ddt_path, "rb").read()
            self.img_path, self.img_base = os.path.join(path, "DDS3.IMG"), 0
        _, self.files = parse_ddt(raw)
        self.index = {f.path.lower(): f for f in self.files}

    def read(self, entry):
        with open(self.img_path, "rb") as img:
            img.seek(self.img_base + entry.sector * SECTOR)
            return img.read(entry.size)

    def program_file(self):
        """(name, bytes) of the game's program file (SLUS_218.45), or None."""
        if self.iso_files is not None:
            for name, f in sorted(self.iso_files.items()):
                if name.startswith(PROGRAM_PREFIXES):
                    with open(self.path, "rb") as iso:
                        iso.seek(f.lsn * SECTOR)
                        return name, iso.read(f.size)
            return None
        found = find_program_file(self.path)
        return (os.path.basename(found), open(found, "rb").read()) if found else None


PROGRAM_PREFIXES = ("SLUS_", "SLES_", "SLPM_", "SCUS_")
_GAMES = {}


def game(path):
    if path not in _GAMES:
        _GAMES[path] = GameSource(path)
    return _GAMES[path]


def read_archive_file(game_dir, path):
    """Read one file out of a game's archive (folder or ISO; path is case-insensitive)."""
    g = game(game_dir)
    f = g.index.get(path.lower())
    if f is None:
        sys.exit(f"error: {path} not found in {game_dir}")
    return g.read(f)


def find_nocturne_model(noc_dir, demon_id, quiet=False):
    """Nocturne stores demon 0x42 as model/devil/0x40/0x42/0x42.PB."""
    files = game(noc_dir).files
    def num(text):
        try:
            return int(text, 16)
        except ValueError:
            return None
    for f in files:
        p = f.path.lower()
        parts = p.split("/")
        # model/devil/<group>/<id>/<id>.pb, with or without zero padding (0x9 or 0x09)
        if (p.startswith("model/devil/") and p.endswith(".pb") and len(parts) >= 4
                and num(parts[-2]) == demon_id and num(parts[-1][:-3]) == demon_id):
            return f.path
    if quiet:
        return None
    sys.exit(f"error: no Nocturne model for demon 0x{demon_id:x}")


_ARCHIVE_INDEX = {}


def archive_index(game_dir):
    return game(game_dir).index


def archive_has(game_dir, path):
    return path.lower() in archive_index(game_dir)


def write_mod_file(moddir, rel, data, note=""):
    dest = os.path.join(moddir, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    print(f"  {rel}{note}")


def put_model(ds2_dir, noc_dir, noc_id, target, source, moddir, move_from=None, raw=False, share=False,
              extend=True, fill=False):
    """Write Nocturne model NOC_ID into DS2 demon TARGET's model files.

    SOURCE is the DS2 demon whose battle/field files (sounds, hit data,
    textures) and animation timings are used; for a plain reskin it is TARGET.
    """
    import tempfile
    noc_path = find_nocturne_model(noc_dir, noc_id)
    model = read_archive_file(noc_dir, noc_path)
    print(f"Nocturne {noc_path} ({len(model)} bytes) -> DS2 demon {target}")
    base = read_archive_file(ds2_dir, f"model/devil/{source}.PB")
    # Every copy of the model must be identical (the game shares them), and
    # the Compendium crashes if the animation section grows, so by default the
    # only change is extending the slot table to DS2's 17. --fill also copies
    # animations into empty slots (in every copy) for experimenting.
    fill = fill or move_from is not None
    if raw:
        filled = []
        print("  (--raw: animation table left exactly as in Nocturne)")
    else:
        model, filled = fill_motion_slots(model, base, move_from, extend=extend, fill=fill, share=share)
        if not extend:
            print("  (--no-extend: slot table kept at Nocturne's size)")
    battle_model = model
    for slot, pick in filled:
        if pick is None:
            print(f"  animation slot {slot} left empty")
        else:
            print(f"  animation slot {slot} now plays {'' if share else 'a copy of '}slot {pick}")

    for rel in (f"model/devil/{target}.PB", f"model/devil_hi/{target}_hi.PB"):
        if archive_has(ds2_dir, rel):
            write_mod_file(moddir, rel, model)
        else:
            print(f"  ({rel} doesn't exist in this game; skipped)")
    fd, tmp = tempfile.mkstemp(suffix=".LB")
    os.close(fd)
    try:
        for pattern in ("model_lb/devil_b/{}.LB", "model/devil_lb/DEVIL{}.LB"):
            rel = pattern.format(target)
            if not archive_has(ds2_dir, rel):
                print(f"  ({rel} doesn't exist in this game; skipped)")
                continue
            with open(tmp, "wb") as f:
                f.write(read_archive_file(ds2_dir, pattern.format(source)))
            entries = read_lb(tmp)
            if not entries or entries[0].kind != "PBN":
                sys.exit(f"error: {pattern.format(source)} doesn't start with a model entry")
            entries[0].data = battle_model if pattern.startswith("model_lb/devil_b/") else model
            dest = os.path.join(moddir, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            write_lb(dest, entries)
            print(f"  {rel} (recompressed)")
    finally:
        os.remove(tmp)


def pop_option(args, name):
    if name in args:
        i = args.index(name)
        value = args[i + 1]
        return args[:i] + args[i + 2:], value
    return args, None


def cmd_reskin(args):
    """reskin DS2_DIR NOCTURNE_DIR NOCTURNE_ID DS2_ID MODDIR [--move-from SLOT]

    Puts Nocturne demon NOCTURNE_ID's model into DS2 demon DS2_ID's slot:
    menus (devil_hi), battle (devil_b LB), field (devil_lb LB) and devil/.
    """
    raw = "--raw" in args
    no_extend = "--no-extend" in args
    do_fill = "--fill" in args
    share = "--share" in args
    args = [a for a in args if a not in ("--raw", "--no-extend", "--no-fill", "--fill", "--share")]
    args, move_from = pop_option(args, "--move-from")
    args, mapping = pop_option(args, "--map")
    if mapping:
        move_from = {int(a): None if b == "-" else int(b)
                     for a, b in (p.split("=") for p in mapping.split(","))}
    elif move_from is not None:
        move_from = int(move_from)
    if len(args) != 5:
        sys.exit("usage: dds3tool.py reskin DS2_DIR NOCTURNE_DIR NOCTURNE_ID DS2_ID MODDIR [--fill] [--move-from SLOT] [--map 6=7,12=7] [--share] [--raw]\n"
                 "  e.g. dds3tool.py reskin ds2 nocturne 0x42 04A mod")
    ds2_dir, noc_dir, noc_id, ds2_id, moddir = args
    ds2_id = f"{int(ds2_id, 16):03X}"
    put_model(ds2_dir, noc_dir, int(noc_id, 16), ds2_id, ds2_id, moddir,
              move_from, raw=raw, share=share,
              extend=not no_extend, fill=do_fill or move_from is not None)
    print("Done. Next: dds3tool.py isopatch DS2.ISO", moddir, "OUT.iso")


SB_MOTIONMV = "battle/SB_MOTIONMV.TBL"
# Tables with one fixed-size entry per demon ID, copied by add-demon.
PER_DEMON_TABLES = (
    (SB_VISUAL, 0, VISUAL_RECORD),        # battle size, reach, camera
    (SB_MOTIONMV, 0, 64),                 # lunges during attacks
    ("battle/SB_EFFECT.TBL", 1, 20),
    ("battle/SB_EFFECT.TBL", 2, 1),
    ("battle/SB_EFFECT.TBL", 3, 16),      # hit/damage effects (reserves hold filler)
    ("battle/SB_DVLFOOT.TBL", 0, 20),     # footsteps
)


def table_sections(data):
    """Sections of a battle table: [u32 size][data], each start 16-byte aligned."""
    secs, pos = [], 0
    while pos + 4 <= len(data):
        size = struct.unpack_from("<I", data, pos)[0]
        if size == 0 or pos + 4 + size > len(data):
            break
        secs.append((pos, size))
        pos += 4 + size
        pos += -pos % 16
    return secs
DATA_RECORD = 148


def load_table(ds2_dir, moddir, rel):
    modded = os.path.join(moddir, rel)
    if os.path.exists(modded):
        return bytearray(open(modded, "rb").read())
    return bytearray(read_archive_file(ds2_dir, rel))


# ---------------------------------------------------------------- Program (ELF) patches
#
# The menus (fusion preview, party, status) load each demon's model through a
# table in the game's program file (SLUS_218.45): one pointer per demon ID to
# a file name such as "devil_hi/04A_hi.PB". Reserve slots all point at
# "devil_hi/000_hi.PB", a placeholder. menu_model() writes new file names into
# unused padding between program sections and repoints the table entries.

def elf_layout(elf):
    phoff, phnum = struct.unpack_from("<I", elf, 28)[0], struct.unpack_from("<H", elf, 44)[0]
    segs = []
    for i in range(phnum):
        kind, off, va, _, filesz, _, _, _ = struct.unpack_from("<8I", elf, phoff + i * 32)
        if kind == 1:
            segs.append((va, off, filesz))
    return segs


def elf_va_to_off(elf, va):
    for seg_va, off, size in elf_layout(elf):
        if seg_va <= va < seg_va + size:
            return off + va - seg_va
    return None


def elf_free_gaps(elf):
    """Zero-filled padding between allocated sections that is loaded into memory."""
    shoff, shnum = struct.unpack_from("<I", elf, 32)[0], struct.unpack_from("<H", elf, 48)[0]
    secs = sorted((s[3], s[5], s[1]) for s in (struct.unpack_from("<10I", elf, shoff + i * 40)
                                                for i in range(shnum)) if s[3] and s[2] & 2)
    gaps = []
    for (va, size, kind), (va2, _, _) in zip(secs, secs[1:]):
        start, end = va + size, va2
        if kind == 8 or end <= start:
            continue
        lo, hi = elf_va_to_off(elf, start), elf_va_to_off(elf, end - 1)
        if lo is not None and hi is not None and hi - lo == end - 1 - start:
            gaps.append([start, end])
    return gaps


def elf_off_to_va(elf, off):
    for seg_va, seg_off, size in elf_layout(elf):
        if seg_off <= off < seg_off + size:
            return seg_va + off - seg_off
    return None


def elf_string_at(elf, va):
    off = elf_va_to_off(elf, va) if va else None
    if off is None or off >= len(elf):
        return None
    end = elf.find(b"\0", off)
    if end == -1 or end - off > 64:
        return None
    try:
        return elf[off:end].decode("ascii")
    except UnicodeDecodeError:
        return None


# Per-demon file-name tables in the program file. Each is found by what its
# entries for 04A and 04B look like. "own" entries get a new name for the
# demon's own file; "template" entries reuse the template demon's name
# (add-demon copies the template's file into the new slot).
NAME_TABLES = (
    ("menu model", "devil_hi/{:03X}_hi.PB", "own"),
    ("model", "devil/{:03X}.PB", "own"),
    ("battle texture", "{:03X}.tmx", "template"),
    ("battle icon", "icon_{:03X}.tmx", "template"),
)


def find_name_tables(elf):
    """Return {pattern: [table file offsets]}."""
    found = {pattern: [] for _, pattern, _ in NAME_TABLES}
    for va, off, size in elf_layout(elf):
        for pos in range(off, off + size - 0xC0 * 4, 4):
            a = struct.unpack_from("<I", elf, pos + 4 * 0x4A)[0]
            if not a:
                continue
            sa = elf_string_at(elf, a)
            if not sa:
                continue
            for _, pattern, _ in NAME_TABLES:
                if sa == pattern.format(0x4A) and \
                        elf_string_at(elf, struct.unpack_from("<I", elf, pos + 4 * 0x4B)[0]) == pattern.format(0x4B):
                    found[pattern].append(pos)
    return found


def place_string(elf, gaps, text):
    """Write TEXT (NUL-terminated) into the first free gap; return its address."""
    for start, end in gaps:
        va = start
        while va + len(text) <= end:
            off = elf_va_to_off(elf, va)
            if elf[off:off + len(text)] == bytes(len(text)) and elf[off - 1] == 0:
                elf[off:off + len(text)] = text
                return va
            va += 1
    sys.exit("error: no free space left in the program file for more demon file names")


def string_va(elf, gaps, text):
    """Address of TEXT (NUL-terminated) in the program, adding it if needed."""
    pos = elf.find(text)
    while pos > 0 and elf[pos - 1] != 0:
        pos = elf.find(text, pos + 1)
    return elf_off_to_va(elf, pos) if pos > 0 else place_string(elf, gaps, text)


def patch_demon_names(elf, demon, template, has_file=lambda rel: True):
    """Point every per-demon file-name table entry for DEMON at a usable file.

    Returns (new program, notes).
    """
    elf = bytearray(elf)
    gaps = elf_free_gaps(elf)
    tables = find_name_tables(bytes(elf))
    notes = []
    for label, pattern, mode in NAME_TABLES:
        if not tables[pattern]:
            notes.append(f"{label}: table not found")
            continue
        if mode == "own":
            name = pattern.format(demon)
            if not has_file(name):
                notes.append(f"{label}: no {name} in this game, left as is")
                continue
            va = string_va(elf, gaps, name.encode() + b"\0")
            for pos in tables[pattern]:
                struct.pack_into("<I", elf, pos + 4 * demon, va)
            notes.append(f"{label} -> {name}")
        else:
            for pos in tables[pattern]:
                va = struct.unpack_from("<I", elf, pos + 4 * template)[0]
                struct.pack_into("<I", elf, pos + 4 * demon, va)
            notes.append(f"{label} -> {pattern.format(template)}")
    return bytes(elf), notes


def menu_model(elf, demon_ids):
    """Back-compat wrapper: only the menu-model table, own file names."""
    elf = bytearray(elf)
    gaps = elf_free_gaps(elf)
    table = find_name_tables(bytes(elf))["devil_hi/{:03X}_hi.PB"][0]
    notes = []
    for demon in demon_ids:
        name = f"devil_hi/{demon:03X}_hi.PB"
        struct.pack_into("<I", elf, table + 4 * demon, string_va(elf, gaps, name.encode() + b"\0"))
        notes.append(f"{demon:03X} -> {name}")
    return bytes(elf), notes


def find_program_file(*dirs):
    for d in dirs:
        if d and os.path.isdir(d):
            for name in sorted(os.listdir(d)):
                if name.upper().startswith(PROGRAM_PREFIXES):
                    return os.path.join(d, name)
    return None


def cmd_menu_model(args):
    """menu-model PROGRAM_FILE MODDIR ID [ID ...]"""
    if len(args) < 3:
        sys.exit("usage: dds3tool.py menu-model SLUS_218.45 MODDIR 012 [013 ...]")
    src, moddir = args[0], args[1]
    name = os.path.basename(src)
    modded = os.path.join(moddir, name)
    elf = open(modded if os.path.exists(modded) else src, "rb").read()
    elf, notes = menu_model(elf, [int(a, 16) for a in args[2:]])
    write_mod_file(moddir, name, elf, " (menu models: " + ", ".join(notes) + ")")


def cmd_add_demon(args):
    """add-demon DS2_DIR NOCTURNE_DIR NOCTURNE_ID TEMPLATE_ID RESERVE_ID NAME MODDIR [--level N]

    Turns an unused DS2 "reserve" slot into a new demon: copies TEMPLATE's
    stats, skills, race, battle settings, sounds and hit data, puts the
    Nocturne model on it, and names it. TEMPLATE itself is left unchanged.
    """
    args, level = pop_option(args, "--level")
    args, move_from = pop_option(args, "--move-from")
    if len(args) != 7:
        sys.exit("usage: dds3tool.py add-demon DS2_DIR NOCTURNE_DIR NOCTURNE_ID TEMPLATE_ID RESERVE_ID NAME MODDIR [--level N]\n"
                 '  e.g. dds3tool.py add-demon ds2 nocturne 0x40 04A 012 Virtue mod --level 20')
    ds2_dir, noc_dir, noc_id, template, reserve, name, moddir = args
    template = f"{int(template, 16):03X}"
    reserve = f"{int(reserve, 16):03X}"
    t_id, r_id = int(template, 16), int(reserve, 16)

    data = load_table(ds2_dir, moddir, SB_DATA)
    names, count = find_name_table(data)
    old_name = data[names + r_id * NAME_LEN: names + (r_id + 1) * NAME_LEN].split(b"\0")[0].decode()
    if "reserve" not in old_name.lower():
        print(f"warning: {reserve} is '{old_name}', not a reserve slot; it will be overwritten")
    if len(name.encode("ascii")) >= NAME_LEN:
        sys.exit(f"error: '{name}' is too long (max {NAME_LEN - 1} characters)")

    # Stats, skills, race: copy the template's record but keep the slot's own IDs.
    t_off, r_off = 4 + t_id * DATA_RECORD, 4 + r_id * DATA_RECORD
    record = bytearray(data[t_off:t_off + DATA_RECORD])
    struct.pack_into("<H", record, 6, r_id)
    struct.pack_into("<H", record, 12, r_id)
    if level is not None:
        struct.pack_into("<H", record, 4, int(level))
    data[r_off:r_off + DATA_RECORD] = record
    # Elemental affinities: the second table in SB_DATA, 64 bytes per demon.
    aff = 4 + struct.unpack_from("<I", data, 0)[0]
    aff += -aff % 16
    aff_size = struct.unpack_from("<I", data, aff)[0]
    if aff_size == count * 64:
        a_t, a_r = aff + 4 + t_id * 64, aff + 4 + r_id * 64
        data[a_r:a_r + 64] = data[a_t:a_t + 64]
    data[names + r_id * NAME_LEN: names + (r_id + 1) * NAME_LEN] = name.encode("ascii").ljust(NAME_LEN, b"\0")
    write_mod_file(moddir, SB_DATA, data, f" ({reserve}: {old_name} -> {name}, "
                   f"level {struct.unpack_from('<H', record, 4)[0]}, stats, skills and affinities from {template})")

    # Other per-demon battle tables: (file, section number, bytes per demon).
    for rel, section, size in PER_DEMON_TABLES:
        if not archive_has(ds2_dir, rel):
            continue
        tbl = load_table(ds2_dir, moddir, rel)
        secs = table_sections(tbl)
        if section >= len(secs):
            print(f"  ({rel} has no section {section}; skipped)")
            continue
        start, length = secs[section]
        if (r_id + 1) * size > length or (t_id + 1) * size > length:
            print(f"  ({rel} section {section} has no entry for {reserve}; skipped)")
            continue
        base = start + 4
        tbl[base + r_id * size: base + (r_id + 1) * size] = tbl[base + t_id * size: base + (t_id + 1) * size]
        write_mod_file(moddir, rel, tbl, f" (entry from {template})")

    # Per-demon files that aren't models: hit data, battle textures, sounds.
    for pattern in ("battle/mdlhit/{}.MHT", "battle/dvltktex/{}.tmx", "battle/dvltktex/icon_{}.tmx",
                    "sobed_lb/{}.LB"):
        src, dst = pattern.format(template), pattern.format(reserve)
        if archive_has(ds2_dir, src) and archive_has(ds2_dir, dst):
            write_mod_file(moddir, dst, read_archive_file(ds2_dir, src), f" (from {template})")
        elif archive_has(ds2_dir, src):
            print(f"  ({dst} doesn't exist in this game; skipped)")

    put_model(ds2_dir, noc_dir, int(noc_id, 16), reserve, template, moddir,
              None if move_from is None else int(move_from))

    # Menus load models through a table in the program file; reserve slots
    # point at a placeholder there, so repoint this one.
    modded = find_program_file(moddir)
    program = ((os.path.basename(modded), open(modded, "rb").read()) if modded
               else game(ds2_dir).program_file())
    if program:
        name, elf = program
        elf, notes = patch_demon_names(elf, r_id, t_id,
                                       lambda rel: archive_has(ds2_dir, "model/" + rel))
        write_mod_file(moddir, name, elf, " (" + "; ".join(notes) + ")")
    else:
        print("  NOTE: copy the game's program file (SLUS_218.45) into", ds2_dir,
              "and rerun, or menus will show a placeholder model for this demon")
    print("Done. Next: dds3tool.py isopatch DS2.ISO", moddir, "OUT.iso")


# ---------------------------------------------------------------- ISO patching

class IsoFile:
    __slots__ = ("name", "lsn", "size", "record_offset")

    def __init__(self, name, lsn, size, record_offset):
        self.name = name
        self.lsn = lsn
        self.size = size
        self.record_offset = record_offset  # byte offset of its directory record


def iso_list_files(iso):
    """{NAME: IsoFile} for every file on the disc (first one wins on duplicates)."""
    return iso_find_files(iso, None)


def iso_find_files(iso, wanted):
    """Walk the ISO9660 tree and return {NAME: IsoFile} for names in `wanted` (None = all)."""
    iso.seek(16 * SECTOR)
    pvd = iso.read(SECTOR)
    if pvd[0] != 1 or pvd[1:6] != b"CD001":
        sys.exit("error: not an ISO9660 image (no primary volume descriptor)")
    root = pvd[156:156 + 34]
    found = {}
    dirs = [(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0])]  # (lsn, size)
    seen = set()
    while dirs:
        lsn, size = dirs.pop()
        if lsn in seen:
            continue
        seen.add(lsn)
        iso.seek(lsn * SECTOR)
        data = iso.read(size)
        pos = 0
        while pos < len(data):
            length = data[pos]
            if length == 0:  # records never cross sectors; skip to the next one
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            rec = data[pos:pos + length]
            r_lsn, r_size = struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0]
            flags, name_len = rec[25], rec[32]
            name = rec[33:33 + name_len]
            if name not in (b"\0", b"\1"):
                text = name.decode("ascii", "replace").split(";")[0].upper()
                if flags & 2:
                    dirs.append((r_lsn, r_size))
                elif (wanted is None or text in wanted) and text not in found:
                    found[text] = IsoFile(text, r_lsn, r_size, lsn * SECTOR + pos)
            pos += length
    return found


def write_both_endian_u32(f, offset, value):
    f.seek(offset)
    f.write(struct.pack("<I", value) + struct.pack(">I", value))


PAD_SECTORS = 512  # 1 MB of empty space after the last file on the disc


def cmd_isopatch(args):
    """Patch DDS3.IMG/DDS3.DDT directly inside a copy of the game's ISO.

    Nothing on the disc moves: files that fit are overwritten where they are,
    larger ones are appended after the end of the image, and only the DDT
    entries, the IMG's size and the volume size are updated.
    """
    in_place = "--in-place" in args
    force_append = "--append" in args
    args = [a for a in args if a not in ("--in-place", "--append")]
    if len(args) < (2 if in_place else 3):
        sys.exit("usage: dds3tool.py isopatch GAME.iso MODDIR OUT.iso   (or: GAME.iso MODDIR --in-place)")
    src_iso, moddir = args[0], args[1]
    if in_place:
        out_iso = src_iso
    else:
        out_iso = args[2]
        if os.path.abspath(out_iso) == os.path.abspath(src_iso):
            sys.exit("error: output must differ from the input (or use --in-place)")
        print(f"Copying {src_iso} -> {out_iso} ...")
        shutil.copyfile(src_iso, out_iso)

    with open(out_iso, "r+b") as iso:
        found = iso_find_files(iso, {"DDS3.DDT", "DDS3.IMG"})
        for name in ("DDS3.DDT", "DDS3.IMG"):
            if name not in found:
                sys.exit(f"error: {name} not found in {src_iso}")
        ddt_file, img_file = found["DDS3.DDT"], found["DDS3.IMG"]
        print(f"DDS3.DDT at sector {ddt_file.lsn}, DDS3.IMG at sector {img_file.lsn} ({img_file.size} bytes)")

        iso.seek(ddt_file.lsn * SECTOR)
        ddt = bytearray(iso.read(ddt_file.size))
        tmp_ddt = out_iso + ".ddt.tmp"
        with open(tmp_ddt, "wb") as f:
            f.write(ddt)
        try:
            ddt, files = read_ddt(tmp_ddt)
        finally:
            os.remove(tmp_ddt)
        replacements = collect_replacements(files, moddir, allow_empty=True)

        iso.seek(0, os.SEEK_END)
        end = iso.tell()
        if end % SECTOR:
            end += SECTOR - end % SECTOR
        img_end = img_file.lsn * SECTOR + img_file.size

        for entry, path in replacements:
            new = open(path, "rb").read()
            old_sectors = (entry.size + SECTOR - 1) // SECTOR
            new_sectors = (len(new) + SECTOR - 1) // SECTOR
            if new_sectors <= old_sectors and not force_append:
                abs_sector = img_file.lsn + entry.sector
                where = "in place"
            else:
                abs_sector = end // SECTOR
                end += new_sectors * SECTOR
                where = f"appended at disc sector {abs_sector}"
            iso.seek(abs_sector * SECTOR)
            iso.write(new + b"\0" * (new_sectors * SECTOR - len(new)))
            struct.pack_into("<Ii", ddt, entry.entry_offset + 4, abs_sector - img_file.lsn, len(new))
            img_end = max(img_end, abs_sector * SECTOR + len(new))
            print(f"{entry.path}: {entry.size} -> {len(new)} bytes, {where}")

        iso.seek(ddt_file.lsn * SECTOR)
        iso.write(ddt)

        # Top-level files in MODDIR (e.g. the patched program file) replace the
        # disc file of the same name, which must keep its size.
        top = [n for n in sorted(os.listdir(moddir))
               if not n.startswith(".") and os.path.isfile(os.path.join(moddir, n))]
        if top:
            disc = iso_find_files(iso, {n.upper() for n in top})
            for n in top:
                f = disc.get(n.upper())
                data = open(os.path.join(moddir, n), "rb").read()
                if f is None:
                    sys.exit(f"error: {n} is not a file on the disc")
                if len(data) != f.size:
                    sys.exit(f"error: {n} must stay {f.size} bytes (is {len(data)})")
                iso.seek(f.lsn * SECTOR)
                iso.write(data)
                print(f"{n}: replaced on disc")

        # Let DDS3.IMG cover anything appended, and grow the volume to match.
        new_img_size = img_end - img_file.lsn * SECTOR
        if new_img_size != img_file.size:
            if new_img_size >= 1 << 32:
                sys.exit("error: DDS3.IMG would exceed 4 GB")
            write_both_endian_u32(iso, img_file.record_offset + 10, new_img_size)
        iso.seek(0, os.SEEK_END)
        total = iso.tell()
        if total % SECTOR:
            iso.write(b"\0" * (SECTOR - total % SECTOR))
            total += SECTOR - total % SECTOR
        # The game reads ahead past the end of a file; if an appended file is
        # the last thing on the disc, that read-ahead runs off the image. Keep
        # empty padding after the last file, like a pressed disc has.
        if img_end + PAD_SECTORS * SECTOR > total:
            pad = img_end + PAD_SECTORS * SECTOR - total
            pad += -pad % SECTOR
            iso.write(b"\0" * pad)
            total += pad
        iso.seek(16 * SECTOR + 80)
        old_blocks = struct.unpack("<I", iso.read(4))[0]
        if total // SECTOR > old_blocks:
            write_both_endian_u32(iso, 16 * SECTOR + 80, total // SECTOR)
    print(f"Wrote {out_iso}")


# ---------------------------------------------------------------- Fusion locks

FUSION_LOCKS = "gohEventDevil.dat"  # 12-byte entries: u32 story flag, u32 demon ID, u32 1


def load_fusion_locks(ds2_dir, moddir):
    """The lock list from the mod folder if already changed, else from the game; returns (path, data)."""
    files = game(ds2_dir).files
    hits = [f for f in files if f.path.lower().endswith("/" + FUSION_LOCKS.lower())
            or f.path.lower() == FUSION_LOCKS.lower()]
    if not hits:
        sys.exit(f"error: {FUSION_LOCKS} not found in {ds2_dir}/DDS3.DDT")
    path = hits[0].path
    modded = os.path.join(moddir, path)
    if moddir and os.path.exists(modded):
        return path, bytearray(open(modded, "rb").read())
    return path, bytearray(read_archive_file(ds2_dir, path))


def cmd_locks(args):
    """locks DS2_DIR [MODDIR]  - list demons that fusion hides until a story flag is set"""
    path, data = load_fusion_locks(args[0], args[1] if len(args) > 1 else "")
    print(f"{path}:")
    for i in range(0, len(data) - 11, 12):
        flag, demon, _ = struct.unpack_from("<III", data, i)
        print(f"  {demon:03X}  locked until flag 0x{flag:x}")


def cmd_unlock(args):
    """unlock DS2_DIR MODDIR ID [ID ...]  - let fusion make these demons without their story event"""
    if len(args) < 3:
        sys.exit("usage: dds3tool.py unlock DS2_DIR MODDIR 099 [098 ...]")
    ds2_dir, moddir = args[0], args[1]
    want = {int(a, 16) for a in args[2:]}
    path, data = load_fusion_locks(ds2_dir, moddir)
    entries = [struct.unpack_from("<III", data, i) for i in range(0, len(data) - 11, 12)]
    keep = [e for e in entries if e[1] not in want]
    found = {e[1] for e in entries} & want
    for d in sorted(want - found):
        print(f"{d:03X} is not locked")
    if not found:
        return
    if not keep:
        sys.exit("error: can't unlock every demon in the list")
    # Keep the file the same size: overwrite unlocked entries with a copy of a remaining lock.
    filler = keep[-1]
    for i, e in enumerate(entries):
        if e[1] in want:
            struct.pack_into("<III", data, i * 12, *filler)
            print(f"{e[1]:03X}: unlocked (was flag 0x{e[0]:x})")
    dest = os.path.join(moddir, path)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    print(f"Wrote {dest}")


def cmd_set_level(args):
    """set-level DS2_DIR MODDIR ID=LEVEL [...]  - change a demon's base level (stats stay)"""
    if len(args) < 3:
        sys.exit("usage: dds3tool.py set-level DS2_DIR MODDIR 066=1 [03B=1 ...]")
    ds2_dir, moddir = args[0], args[1]
    tbl = load_sb_data(ds2_dir, moddir)
    for pair in args[2:]:
        demon, level = pair.split("=")
        demon, level = int(demon, 16), int(level)
        off = 4 + demon * DATA_RECORD + 4
        old = struct.unpack_from("<H", tbl, off)[0]
        struct.pack_into("<H", tbl, off, level)
        print(f"{demon:03X}: level {old} -> {level}")
    dest = os.path.join(moddir, SB_DATA)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(tbl)
    print(f"Wrote {dest}")


def main():
    commands = {"list": cmd_list, "extract": cmd_extract, "patch": cmd_patch, "isopatch": cmd_isopatch,
                "lb-list": cmd_lb_list, "reskin": cmd_reskin, "menu-model": cmd_menu_model, "add-demon": cmd_add_demon, "motions": cmd_motions, "bases": cmd_bases, "templates": cmd_templates, "motion-alias": cmd_motion_alias, "names": cmd_names, "rename": cmd_rename, "locks": cmd_locks, "compare": cmd_compare, "set-level": cmd_set_level, "unlock": cmd_unlock, "set-class": cmd_set_class, "bones": cmd_bones, "mht-list": cmd_mht_list, "mht-bones": cmd_mht_bones, "lb-extract": cmd_lb_extract, "lb-replace": cmd_lb_replace}
    if len(sys.argv) < 3 or sys.argv[1] not in commands:
        print(__doc__)
        sys.exit(1)
    commands[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
