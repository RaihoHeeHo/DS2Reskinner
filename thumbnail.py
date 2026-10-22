"""Still pictures of demon models for the reskinner window.

A small software renderer with no dependencies: it decodes a PB/LB with
model_preview, poses the skeleton on the first frame of the idle animation
(slot 0; the rest pose if there is none), skins the vertices the same way the
browser viewer does, and draws textured, lit triangles into a depth buffer.
The result is a PNG, which Tk 8.6 shows directly (tk.PhotoImage(data=...)).
"""
import base64
import math
import struct
import zlib

from model_preview import decode_model

VERSION = 1   # bump when the picture changes, so cached thumbnails are redrawn
ALPHA_CUTOFF = 90   # the viewer's alphaTest of 0.35
YAW, PITCH = 0.25, 0.1   # the viewer's starting camera angle


def _mul(a, b):
    """3x4 affine matrices as flat 12-tuples (row-major rotation|translation)."""
    return (a[0]*b[0]+a[1]*b[4]+a[2]*b[8], a[0]*b[1]+a[1]*b[5]+a[2]*b[9], a[0]*b[2]+a[1]*b[6]+a[2]*b[10],
            a[0]*b[3]+a[1]*b[7]+a[2]*b[11]+a[3],
            a[4]*b[0]+a[5]*b[4]+a[6]*b[8], a[4]*b[1]+a[5]*b[5]+a[6]*b[9], a[4]*b[2]+a[5]*b[6]+a[6]*b[10],
            a[4]*b[3]+a[5]*b[7]+a[6]*b[11]+a[7],
            a[8]*b[0]+a[9]*b[4]+a[10]*b[8], a[8]*b[1]+a[9]*b[5]+a[10]*b[9], a[8]*b[2]+a[9]*b[6]+a[10]*b[10],
            a[8]*b[3]+a[9]*b[7]+a[10]*b[11]+a[11])


def _euler_zyx(rx, ry, rz):
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    return [[cz*cy, cz*sy*sx - sz*cx, cz*sy*cx + sz*sx],
            [sz*cy, sz*sy*sx + cz*cx, sz*sy*cx - cz*sx],
            [-sy, cy*sx, cy*cx]]


def _quat(x, y, z, w):
    n = math.sqrt(x*x + y*y + z*z + w*w) or 1.0
    x, y, z, w = -x/n, -y/n, -z/n, w/n   # MT00 stores the conjugate of the local rotation
    return [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
            [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
            [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]


def bone_matrices(model, motion=None):
    """World matrix of every bone, on frame 0 of MOTION (or the rest pose)."""
    nodes = model["nodes"]
    pose = [{"p": n["position"], "s": n["scale"], "q": None, "r": n["rotation"]} for n in nodes]
    for track in (motion or {}).get("tracks", []):
        if 0 <= track["bone"] < len(pose) and track["values"]:
            key = {0: "p", 2: "s", 3: "q"}.get(track["type"])
            if key:
                pose[track["bone"]][key] = track["values"][0]
    world = []
    for i, n in enumerate(pose):
        rot = _quat(*n["q"]) if n["q"] else _euler_zyx(*n["r"])
        sx, sy, sz = n["s"]
        # local = Scale * Rotation, then translation (the viewer's premultiply).
        local = (rot[0][0]*sx, rot[0][1]*sx, rot[0][2]*sx, n["p"][0],
                 rot[1][0]*sy, rot[1][1]*sy, rot[1][2]*sy, n["p"][1],
                 rot[2][0]*sz, rot[2][1]*sz, rot[2][2]*sz, n["p"][2])
        parent = nodes[i]["parent"]
        world.append(_mul(world[parent], local) if parent >= 0 else local)
    return world


def _textures(model):
    out = []
    for t in model["textures"]:
        if not t:
            out.append(None)
            continue
        out.append((t["width"], t["height"], base64.b64decode(t["rgba"]),
                    (t["wrap"] & 15) == 1, (t["wrap"] >> 4) == 1))
    return out


def triangles(model, motion=None):
    """[(v0, v1, v2, uv0, uv1, uv2, texture index or None, tint)] in display space (Y up)."""
    world = bone_matrices(model, motion)
    materials = model["materials"]
    out = []
    for batch in model["meshes"]:
        count = len(batch["influences"][0]["positions"])
        verts = [[0.0, 0.0, 0.0] for _ in range(count)]
        for inf in batch["influences"]:
            e = world[inf["bone"]]
            for i, (x, y, z, w) in enumerate(inf["positions"]):
                v = verts[i]
                v[0] += (e[0]*x + e[1]*y + e[2]*z + e[3]) * w
                v[1] -= (e[4]*x + e[5]*y + e[6]*z + e[7]) * w
                v[2] -= (e[8]*x + e[9]*y + e[10]*z + e[11]) * w
        uv = batch["uv"]
        mat = materials[batch["material"]] if batch["material"] is not None and batch["material"] < len(materials) else {}
        tex = mat.get("texture")
        color = mat.get("color")
        tint = (color[0]/255, color[1]/255, color[2]/255) if color else (1.0, 1.0, 1.0)
        for a, b, c in batch["triangles"]:
            out.append((verts[a], verts[b], verts[c],
                        uv[a] if a < len(uv) else (0, 0), uv[b] if b < len(uv) else (0, 0),
                        uv[c] if c < len(uv) else (0, 0), tex, tint))
    return out


def render(model, size=220, background=(244, 244, 244), supersample=2, motion=None):
    """RGB bytes (size*size*3) of MODEL (a decode_model result)."""
    if motion is None:
        motion = next((m for m in model["motions"] if m and m.get("slot") == 0 and m.get("pack", 0) == 0), None)
    tris = triangles(model, motion)
    texs = _textures(model)
    n = size * supersample
    # Camera: orbit angle of the viewer, orthographic, fitted to the model.
    cy, sy, cp, sp = math.cos(YAW), math.sin(YAW), math.cos(PITCH), math.sin(PITCH)

    def view(v):
        x, y, z = v[0]*cy - v[2]*sy, v[1], v[0]*sy + v[2]*cy
        return x, y*cp - z*sp, y*sp + z*cp   # depth: larger is nearer the camera

    projected = []
    xs, ys = [], []
    for t in tris:
        p = (view(t[0]), view(t[1]), view(t[2]))
        projected.append(p)
        for q in p:
            xs.append(q[0])
            ys.append(q[1])
    rgb = bytearray(bytes(background) * (n * n))
    if not projected:
        return _downsample(rgb, n, supersample)
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    span = max(x1 - x0, y1 - y0) or 1.0
    scale = n * 0.9 / span
    ox = n / 2 - (x0 + x1) / 2 * scale
    oy = n / 2 + (y0 + y1) / 2 * scale
    depth = [-1e30] * (n * n)
    for (pa, pb, pc), t in zip(projected, tris):
        ax, ay = ox + pa[0]*scale, oy - pa[1]*scale
        bx, by = ox + pb[0]*scale, oy - pb[1]*scale
        cx, cyy = ox + pc[0]*scale, oy - pc[1]*scale
        area = (bx - ax) * (cyy - ay) - (cx - ax) * (by - ay)
        if abs(area) < 1e-9:
            continue
        minx, maxx = max(int(min(ax, bx, cx)), 0), min(int(max(ax, bx, cx)) + 1, n - 1)
        miny, maxy = max(int(min(ay, by, cyy)), 0), min(int(max(ay, by, cyy)) + 1, n - 1)
        if minx > maxx or miny > maxy:
            continue
        # Flat shading from the face normal; light from the camera, slightly above.
        ux, uy, uz = pb[0]-pa[0], pb[1]-pa[1], pb[2]-pa[2]
        vx, vy, vz = pc[0]-pa[0], pc[1]-pa[1], pc[2]-pa[2]
        nx, ny, nz = uy*vz - uz*vy, uz*vx - ux*vz, ux*vy - uy*vx
        length = math.sqrt(nx*nx + ny*ny + nz*nz) or 1.0
        light = abs((ny*0.35 + nz*0.94) / length)
        shade = 0.45 + 0.6 * light
        tex = texs[t[6]] if t[6] is not None and 0 <= t[6] < len(texs) else None
        tint = t[7]
        (u0, v0), (u1, v1), (u2, v2) = t[3][:2], t[4][:2], t[5][:2]
        za, zb, zc = pa[2], pb[2], pc[2]
        inv = 1.0 / area
        if tex is None:
            flat = bytes(min(255, int(200 * tint[k] * shade)) for k in range(3))
        else:
            tw, th, data, clamp_u, clamp_v = tex
        for py in range(miny, maxy + 1):
            fy = py + 0.5
            row = py * n
            for px in range(minx, maxx + 1):
                fx = px + 0.5
                w0 = ((bx - fx) * (cyy - fy) - (cx - fx) * (by - fy)) * inv
                w1 = ((cx - fx) * (ay - fy) - (ax - fx) * (cyy - fy)) * inv
                w2 = 1.0 - w0 - w1
                if w0 < 0 or w1 < 0 or w2 < 0:
                    continue
                z = w0*za + w1*zb + w2*zc
                i = row + px
                if z <= depth[i]:
                    continue
                if tex is None:
                    color = flat
                else:
                    u = w0*u0 + w1*u1 + w2*u2
                    v = w0*v0 + w1*v1 + w2*v2
                    tx = int(u * tw)
                    ty = int(v * th)
                    tx = min(max(tx, 0), tw - 1) if clamp_u else tx % tw
                    ty = min(max(ty, 0), th - 1) if clamp_v else ty % th
                    k = (ty * tw + tx) * 4
                    if data[k + 3] < ALPHA_CUTOFF:
                        continue
                    color = (min(255, int(data[k] * tint[0] * shade)),
                             min(255, int(data[k + 1] * tint[1] * shade)),
                             min(255, int(data[k + 2] * tint[2] * shade)))
                depth[i] = z
                rgb[i*3:i*3 + 3] = bytes(color)
    return _downsample(rgb, n, supersample)


def _downsample(rgb, n, f):
    if f == 1:
        return bytes(rgb)
    m = n // f
    out = bytearray(m * m * 3)
    area = f * f
    for y in range(m):
        for x in range(m):
            for c in range(3):
                total = 0
                for dy in range(f):
                    base = ((y*f + dy) * n + x*f) * 3 + c
                    for dx in range(f):
                        total += rgb[base + dx*3]
                out[(y*m + x)*3 + c] = total // area
    return bytes(out)


def png(rgb, size):
    """Encode SIZE x SIZE RGB bytes as a PNG."""
    raw = b"".join(b"\0" + rgb[y*size*3:(y+1)*size*3] for y in range(size))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def thumbnail_png(model_bytes, size=220, background=(244, 244, 244)):
    """PNG of a PB (or LB) file's model."""
    return png(render(decode_model(model_bytes), size, background), size)
