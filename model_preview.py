"""Read-only DDS3 preview decoder. No rendering or third-party dependencies.

Binary layouts were checked against real Nocturne/DS2 data and the public
DDS3 Model Studio format documentation (see preview/FORMAT_NOTES.md).
"""
import base64
import math
import struct

import dds3tool as archive


class FormatError(ValueError):
    pass


def align(n, a=16):
    return (n + a - 1) // a * a


class Reader:
    def __init__(self, data, start=0, end=None):
        self.data, self.pos = data, start
        self.end = len(data) if end is None else end
        if not 0 <= start <= self.end <= len(data):
            raise FormatError('Invalid section bounds')

    def read(self, fmt):
        size = struct.calcsize('<' + fmt)
        if self.pos + size > self.end:
            raise FormatError(f'Truncated model at 0x{self.pos:X}')
        value = struct.unpack_from('<' + fmt, self.data, self.pos)
        self.pos += size
        return value[0] if len(value) == 1 else list(value)

    def skip(self, n):
        if n < 0 or self.pos + n > self.end:
            raise FormatError('Section exceeds model bounds')
        self.pos += n

    def aligned(self, a=16):
        self.skip(align(self.pos, a) - self.pos)

    def vectors(self, n, dimensions):
        return [self.read(f'{dimensions}f') for _ in range(n)]

    def packet(self):
        immediate, count, cmd = self.read('HBB')
        if cmd & 0x60 != 0x60:
            raise FormatError(f'Expected VIF unpack at 0x{self.pos-4:X}, got {cmd:X}')
        count = count or 256
        components = ((cmd >> 2) & 3) + 1
        width = cmd & 3
        if width == 3:
            raise FormatError('Packed VIF color format is unsupported')
        fmt = ['f', 'H', 'B'][width]
        values = [self.read(f'{components}{fmt}') for _ in range(count)]
        self.aligned(4)
        return values

    def kick(self, expected=(0x14, 0x17)):
        _, _, cmd = self.read('HBB')
        if cmd not in expected:
            raise FormatError(f'Unexpected VIF command {cmd:X}')


def chunks(data):
    r = Reader(data)
    result = {"motion_sections": []}
    while r.pos + 16 <= r.end:
        start = r.pos
        kind, size, magic, _ = r.read('II4sI')
        if size < 16 or start + size > len(data):
            raise FormatError(f'Invalid chunk size at 0x{start:X}')
        key = magic.decode('ascii', 'replace')
        if key in result and key in ('MD00', 'TXP0'):
            raise FormatError(f'Multiple {key} sections are not supported yet')
        if key == 'MT00':
            result['motion_sections'].append((start, start+size))
        result[key] = (start, start + size)
        if kind == 255 or magic == b'END0':
            break
        r.pos = align(start + size, 64)
    if 'MD00' not in result:
        raise FormatError('No MD00 model section')
    return result


def unpack_lb(data):
    """Return the first model entry; never writes or recompresses the LB."""
    r = Reader(data)
    while r.pos + 16 <= r.end:
        start = r.pos
        header = data[start:start+16]
        size, kind, unpacked = struct.unpack_from('<I4sI', header, 4)
        if kind == b'END0':
            break
        if size < 16 or start + size > len(data) or unpacked > 64*1024*1024:
            raise FormatError('Invalid LB entry bounds')
        if kind.startswith(b'PB') or kind == b'MD00':
            if header[0] == 1:
                try:
                    payload = archive.lz_decompress(data[:start+size], start+16, unpacked)
                except (IndexError, struct.error) as exc:
                    raise FormatError('Truncated compressed LB entry') from exc
            else:
                payload = data[start+16:start+16+unpacked]
            if len(payload) != unpacked:
                raise FormatError('Truncated LB payload')
            return bytes(payload)
        r.pos = align(start + size, archive.LB_ALIGN)
    raise FormatError('LB contains no supported model entry')


def decode_mesh(data, base, end, offset, node):
    r = Reader(data, base+offset, end)
    kind = r.read('I')
    material = None
    batches = []
    if kind in (1, 2):
        qwords, material, stream = r.read('HHI')
        used = [node]
        if kind == 2:
            n = r.read('I')
            if not 1 <= n <= 256:
                raise FormatError('Invalid mesh bone count')
            used = [r.read('H') for _ in range(n)]
        r = Reader(data, base+stream, base+stream+qwords*16)
        while r.pos + 12 <= r.end:
            if not any(data[r.pos:r.end]):
                break
            influences = []
            triangles, uv = [], []
            for j, bone in enumerate(used):
                header = r.packet()[0]
                tc, vc, lo, hi = header
                flags = lo | hi << 16
                if j == len(used)-1:
                    triangles = [v[:3] for v in r.packet()]
                    if len(triangles) != tc:
                        raise FormatError('Triangle packet count mismatch')
                pos = r.packet()
                if len(pos) != vc:
                    raise FormatError('Vertex packet count mismatch')
                if kind == 1:
                    pos = [p + [1.0] for p in pos]
                influences.append({'bone': bone, 'positions': pos})
                if flags & (1 << 23):
                    r.packet()  # Normals; preview recomputes them after deformation.
                if j == len(used)-1:
                    if flags & (1 << 4):
                        uv = [p[:2] for p in r.packet()]
                    if flags & (1 << 11):
                        r.packet()
                r.kick()
            batches.append({'influences': influences, 'triangles': triangles, 'uv': uv})
    elif kind in (7, 8):
        _, material, _, _, tc, vc, flags = r.read('HHIIHHI')
        used = [node]
        if kind == 7:
            n = r.read('H')
            if not 1 <= n <= 256:
                raise FormatError('Invalid mesh bone count')
            used = [r.read('H') for _ in range(n)]
        r.aligned()
        triangles = [r.read('3H') for _ in range(tc)]
        r.aligned()
        influences = [{'bone': b, 'positions': []} for b in used]
        uv, total = [], 0
        while total < vc:
            h = r.packet()[0]
            count = h[1] if kind == 7 else h[0]
            if count <= 0 or total+count > vc:
                raise FormatError('Invalid vertex batch count')
            for j in range(len(used)):
                p = r.packet()
                if len(p) != count:
                    raise FormatError('Vertex count mismatch')
                influences[j]['positions'].extend(p if kind == 7 else [v+[1.0] for v in p])
                r.packet()  # Normals
                if kind == 7:
                    r.kick()
            uv.extend(r.packet())
            r.kick((0x17,) if kind == 7 else (0x14,))
            r.kick((0x10,))
            r.aligned()
            total += count
        batches.append({'influences': influences, 'triangles': triangles, 'uv': uv})
    else:
        raise FormatError(f'Mesh type {kind} is not supported')
    for batch in batches:
        count = len(batch['influences'][0]['positions'])
        if any(len(i['positions']) != count for i in batch['influences']):
            raise FormatError('Inconsistent skinning batch lengths')
        if any(not 0 <= i < count for tri in batch['triangles'] for i in tri):
            raise FormatError('Triangle index outside vertex array')
        batch['material'] = material
        batch['type'] = kind
    return batches


def decode_motions(data, section, warnings):
    if section is None:
        return []
    start, end = section
    base = start+32
    r = Reader(data, base, end)
    count, channels, table = r.read('HHI')
    if channels > 4096 or count > 4096:
        raise FormatError('Invalid animation table size')
    controllers = [r.read('HHHH') for _ in range(channels)]
    r.pos = base+table
    offsets = [r.read('I') for _ in range(count)]
    motions, cached = [], {}
    for slot, offset in enumerate(offsets):
        if not offset:
            motions.append(None)
            continue
        if offset in cached:
            motions.append(cached[offset])
            continue
        r = Reader(data, base+offset, end)
        frames = r.read('I')
        tracks = []
        unsupported = set()
        for typ, _, bone, _ in controllers:
            start_track = r.pos
            size, keys, stride = r.read('IHH')
            if size < 8 or start_track+size > end:
                raise FormatError('Invalid animation track bounds')
            times = [r.read('h') for _ in range(keys)]
            r.aligned(4)
            values = []
            supported = (typ in (0, 2) and stride == 12) or (typ == 3 and stride == 8)
            if r.pos + keys*stride > start_track+size:
                raise FormatError('Animation values exceed track size')
            if supported:
                if times != sorted(times):
                    raise FormatError('Unsorted skeletal animation keys')
                for _ in range(keys):
                    values.append(r.read('3f') if typ in (0, 2) else [x/4096 for x in r.read('4h')])
                if keys:
                    tracks.append({'type': typ, 'bone': bone, 'times': times, 'values': values})
            elif keys:
                unsupported.add((typ, stride))
            r.pos = start_track+size
        if unsupported:
            warnings.add('Some animation channels are not displayed (type/size: '+
                         ', '.join(f'{a}/{b}' for a,b in sorted(unsupported))+').')
        motion = {'frames': frames, 'tracks': tracks}
        cached[offset] = motion
        motions.append(motion)
    return motions


def decode_materials(data, base, end, offset):
    if not offset:
        return []
    r = Reader(data, base+offset, end)
    count = r.read('I')
    if count > 4096:
        raise FormatError('Invalid material count')
    materials = []
    sizes = {16:4, 17:4, 18:4, 19:20, 20:4, 21:4, 22:20, 23:4, 24:4, 25:4, 26:8}
    for _ in range(count):
        index, flags = r.read('II')
        texture = None
        color = None
        for bit in range(16,32):
            if flags & (1 << bit):
                if bit not in sizes:
                    raise FormatError(f'Unknown material property {bit}')
                if bit == 16:
                    color = r.read('4B')
                elif bit == 18:
                    texture = r.read('i')
                else:
                    r.skip(sizes[bit])
        materials.append({'texture': texture, 'color': color})
    return materials


def decode_textures(data, section, warnings):
    if section is None:
        return []
    start, end = section
    r = Reader(data, start+16, end)
    count = r.read('I')
    if count > 4096:
        raise FormatError('Invalid texture count')
    offsets = [r.read('I') for _ in range(count)]
    textures = []
    for off in offsets:
        # TXP offsets are relative to the chunk header, unlike MD00/MT00.
        p = start+off
        tr = Reader(data, p, end)
        _, size, magic, _ = tr.read('II4sI')
        if magic != b'TMX0' or size < 64 or p+size > end:
            raise FormatError('Invalid TMX texture')
        palettes, pf, width, height, fmt, _ = tr.read('BBHHBB')
        if width*height > 4096*4096 or not width or not height:
            raise FormatError('Invalid texture dimensions')
        wrap = data[p+27]
        tr = Reader(data, p+64, p+size)
        def colors(n, pixel_format):
            out=[]
            for _ in range(n):
                if pixel_format == 0:
                    red,green,blue,alpha = tr.read('4B')
                    out.extend((red,green,blue,min(255,alpha*2)))
                elif pixel_format == 1:
                    out.extend(tr.read('3B')+[255])
                elif pixel_format in (2,10):
                    c=tr.read('H')
                    out.extend(((c&31)*255//31, ((c>>5)&31)*255//31,
                                ((c>>10)&31)*255//31, 255 if c&32768 else 0))
                else:
                    raise FormatError(f'Unsupported texture color format {pixel_format}')
            return out
        try:
            if palettes and fmt in (19,20):
                n=256 if fmt == 19 else 16
                palette=colors(n,pf)
                for _ in range(palettes-1):
                    colors(n,pf)
                indices=[]
                if fmt == 19:
                    indices=[tr.read('B') for _ in range(width*height)]
                    # PS2 CSM1 CLUT swaps index bits 3 and 4 in each 32-color group.
                    indices=[(i & ~24) | ((i&8)<<1) | ((i&16)>>1) for i in indices]
                else:
                    for _ in range((width*height+1)//2):
                        b=tr.read('B'); indices.extend((b&15,b>>4))
                rgba=bytes(c for i in indices[:width*height] for c in palette[i*4:i*4+4])
            elif not palettes:
                rgba=bytes(colors(width*height,fmt))
            else:
                raise FormatError(f'Unsupported texture index format {fmt}')
            textures.append({'width':width,'height':height,'rgba':base64.b64encode(rgba).decode(), 'wrap':wrap})
        except FormatError as exc:
            warnings.add(str(exc)); textures.append(None)
    return textures


def decode_model(data, name='Model'):
    if data[8:12] != b'PIB0':
        data = unpack_lb(data)
    parts = chunks(data)
    md, end = parts['MD00']; base=md+32
    r=Reader(data,base,end)
    nodes_off, mat_off, _, _ = r.read('4I')
    r=Reader(data,base+nodes_off,end)
    count=r.read('I'); r.aligned()
    if not 0 < count <= 4096:
        raise FormatError('Invalid skeleton size')
    nodes, geometry = [], []
    for i in range(count):
        _, _, index, parent = r.read('IIii')
        rot=r.read('4f')[:3]; pos=r.read('4f')[:3]; scale=r.read('4f')[:3]
        box, geo, _, old = r.read('4I')
        if parent < -1 or parent >= i:
            raise FormatError(f'Invalid parent for bone {i}')
        nodes.append({'parent':parent,'position':pos,'rotation':rot,'scale':scale})
        geometry.append((box,geo,old))
    meshes=[]; warnings=set()
    for node,(box,geo,old) in enumerate(geometry):
        lists=[]
        if geo:
            if box:
                gr=Reader(data,base+geo,end)
                while True:
                    off=gr.read('I')
                    if not off:break
                    lists.append(off)
                    if len(lists)>16:raise FormatError('Invalid geometry list')
            else:lists.append(geo)
        if old:lists.append(old)
        for off in lists:
            gr=Reader(data,base+off,end)
            n,_=gr.read('HH')
            if n>4096:raise FormatError('Invalid mesh count')
            offsets=[gr.read('I') for _ in range(n)]
            for off in offsets:
                if not off:continue
                meshes.extend(decode_mesh(data,base,end,off,node))
    for mesh in meshes:
        if any(not 0 <= inf['bone'] < count for inf in mesh['influences']):
            raise FormatError('Mesh refers to a missing bone')
    motions=[]
    motion_slots=[]
    for pack,section in enumerate(parts['motion_sections']):
        for slot,motion in enumerate(decode_motions(data,section,warnings)):
            if motion is not None:
                motion = dict(motion, pack=pack, slot=slot)
            motions.append(motion)
            motion_slots.append({'pack':pack, 'slot':slot})
    textures=decode_textures(data,parts.get('TXP0'),warnings)
    result={'name':name,'nodes':nodes,'meshes':meshes,'motions':motions,
            'motion_slots':motion_slots, 'materials':decode_materials(data,base,end,mat_off),
            'textures':textures,'warnings':sorted(warnings)}
    # Reject NaN/Inf before JSON encoding or handing data to a GPU.
    def finite(v):
        if isinstance(v,float) and not math.isfinite(v):raise FormatError('Nonfinite model value')
        if isinstance(v,list):
            for x in v:finite(x)
        elif isinstance(v,dict):
            for x in v.values():finite(x)
    finite(result)
    return result
