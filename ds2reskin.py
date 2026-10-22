"""Engine behind the DS2 Reskinner GUI: the confirmed recipes, analysis of
custom swaps, and the build. Works straight from the two game ISOs.

Everything here calls the same code as the dds3tool commands, so a build from
the GUI matches what the command-line steps produced.
"""
import contextlib
import io
import os
import shutil
import struct
import tempfile

import dds3tool as t

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- Confirmed recipes
#
# Every entry below was built and checked in-game (field, battle, menus).
# map: empty animation slot -> Nocturne slot that plays there.

class Reskin:
    kind = "reskin"

    def __init__(self, name, noc_id, target, map=None, share=False, unlock=False, note=""):
        self.name, self.noc_id, self.target = name, noc_id, target
        self.map = dict(map or {})
        self.share, self.unlock, self.note = share, unlock, note

    @property
    def slot(self):
        return self.target

    def describe(self):
        return f"{self.name} (Nocturne 0x{self.noc_id:02X}) replaces {ds2_name(self.target)} ({self.target})"


class NewDemon:
    kind = "new"

    def __init__(self, name, noc_id, template, reserve, level, note=""):
        self.name, self.noc_id, self.template, self.reserve = name, noc_id, template, reserve
        self.level, self.note = level, note
        self.map, self.share, self.unlock = {}, False, False

    @property
    def slot(self):
        return self.reserve

    def describe(self):
        return (f"{self.name} (Nocturne 0x{self.noc_id:02X}) as a new demon in reserve slot "
                f"{self.reserve}, level {self.level}, based on {ds2_name(self.template)}")


class NocReskin:
    """A Devil Summoner 2 demon put into Nocturne (the reverse direction)."""
    kind = "noc"

    def __init__(self, name, ds2_id, noc_id, map=None, share=True, variants=False, note=""):
        self.name, self.ds2_id, self.noc_id = name, ds2_id, noc_id
        self.map = dict(map or {})
        self.share, self.variants, self.note = share, variants, note
        self.unlock = False

    @property
    def slot(self):
        return f"N{self.noc_id:03X}"   # never clashes with a DS2 slot ID

    def describe(self):
        extra = " and its boss/story versions" if self.variants else ""
        return (f"{self.name} (DS2 {self.ds2_id}) replaces Nocturne {noc_name(self.noc_id)} "
                f"(0x{self.noc_id:02X}){extra}")


def m(text):
    return {int(a): None if b == "-" else int(b)
            for a, b in (p.split("=") for p in text.split(","))} if text else {}


CONFIRMED = [
    Reskin("Principality", 0x42, "04A", note="Divine; floats"),
    Reskin("Virtue", 0x40, "04B", note="Divine; floats"),
    Reskin("Kodama", 0x5C, "02C"),
    Reskin("Hua Po", 0x5B, "095"),
    Reskin("Succubus", 0x75, "07C"),
    Reskin("Apsaras", 0x33, "088", m("6=7,12=7")),
    Reskin("Karasu Tengu", 0x30, "046"),
    Reskin("Yatagarasu", 0x99, "00B"),
    Reskin("Dakini", 0x63, "099", m("6=7,12=7"), unlock=True),
    Reskin("Queen Mab", 0x74, "098", m("6=7,12=7"), unlock=True),
    Reskin("Sarasvati", 0x09, "031", m("6=7,12=7,14=3,15=1")),
    Reskin("Skadi", 0x11, "078", m("6=7,12=7,9=1,14=0,15=2"), share=True, note="glides in battle"),
    Reskin("Kushinada", 0x13, "08D", m("6=7,12=7,14=0,15=2")),
    Reskin("Koppa Tengu", 0x34, "043", m("12=6,7=3,9=0"), note="glides in battle"),
    Reskin("Kin-Ki", 0xA9, "058", m("6=7,9=1"), share=True, note="glides in battle"),
    Reskin("Sui-Ki", 0xAA, "063", m("6=7,9=1"), share=True, note="glides in battle"),
    Reskin("Fuu-Ki", 0xAB, "064", m("6=7"), share=True),
    Reskin("Shiisaa", 0x21, "036", note="walks properly"),
    Reskin("Unicorn", 0x23, "037", m("6=7,12=7"), share=True),
    Reskin("Bishamon", 0x15, "060", m("6=7,9=1,14=0,15=2"), share=True, note="glides in battle"),
    Reskin("Troll", 0x37, "05F", m("6=7,9=1,12=7"), share=True, note="glides in battle"),
    Reskin("Ongyo-Ki", 0xAC, "05C", m("6=7,10=1,15=2"), share=True, note="glides in battle"),
    Reskin("Titan", 0x58, "066", m("6=7,9=1"), share=True, unlock=True, note="glides in battle"),
    Reskin("Pazuzu", 0x6B, "075", m("12=7"), share=True),
    Reskin("Surt", 0x6F, "00A", m("6=7,9=1"), share=True, note="glides in battle"),
    Reskin("Loki", 0x71, "03B", m("6=7,9=1,10=1,12=7"), share=True, unlock=True, note="glides in battle"),
    Reskin("Naga", 0x4F, "01B", m("6=7,9=1"), share=True, note="glides in battle"),
    Reskin("Nozuchi", 0x50, "025", m("6=4,7=8,9=1,12=4"), share=True, note="glides in battle"),
    Reskin("Hanuman", 0x92, "05B", m("6=7,14=0,15=2"), share=True),
    NewDemon("Raphael", 0x8C, "04B", "012", 26),
    NewDemon("Uriel", 0x8D, "04E", "013", 36),
    NewDemon("Gabriel", 0x8B, "048", "029", 30),
    NewDemon("Mothman", 0x7A, "031", "03D", 43),
    NewDemon("Garuda", 0x98, "043", "0A8", 25),
]

RESERVE_SLOTS = {"012", "013", "029", "03D", "0A8"}


# ---------------------------------------------------------------- Names

def _read_id_list(filename):
    out = {}
    path = os.path.join(HERE, filename)
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        parts = line.split()
        if not parts:
            continue
        try:
            n = int(parts[0], 16)
        except ValueError:
            continue
        out[n] = parts
    return out


_NOC = {k: " ".join(v[1:]) for k, v in _read_id_list("Nocturne_demon_ids.txt").items()}
_DS2 = {k: {"level": v[1], "race": v[2], "name": " ".join(v[3:])}
        for k, v in _read_id_list("DS2_demon_ids.txt").items() if len(v) >= 4}


def noc_name(noc_id):
    return _NOC.get(noc_id, f"Nocturne 0x{noc_id:02X}")


def ds2_name(target):
    info = _DS2.get(int(target, 16))
    return info["name"] if info else target


def ds2_info(target):
    return _DS2.get(int(target, 16), {"level": "?", "race": "?", "name": target})


# ---------------------------------------------------------------- Game checks

def quiet(fn, *args, **kw):
    """Run a dds3tool function, turning its exits into ValueError and hiding its prints."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            return fn(*args, **kw)
    except SystemExit as e:
        raise ValueError(str(e.code).replace("error: ", "")) from None


def check_ds2(path):
    g = quiet(t.game, path)
    if not g.index.get(t.SB_DATA.lower()):
        raise ValueError("This doesn't look like Devil Summoner 2 (no battle/SB_DATA.TBL).")
    prog = g.program_file()
    if not prog or prog[0] != "SLUS_218.45":
        raise ValueError("This needs the North American Devil Summoner 2 disc (SLUS_218.45).")
    return g


def check_nocturne(path):
    g = quiet(t.game, path)
    if not any(f.path.lower().startswith("model/devil/0x") for f in g.files):
        raise ValueError("This doesn't look like Nocturne (no model/devil/0x.. folders).")
    return g


def nocturne_models(noc):
    """{noc_id: path} for every demon model in the Nocturne archive."""
    out = {}
    for f in t.game(noc).files:
        parts = f.path.lower().split("/")
        if len(parts) == 5 and parts[0] == "model" and parts[1] == "devil" and parts[4].endswith(".pb"):
            try:
                a, b = int(parts[3], 16), int(parts[4][:-3], 16)
            except ValueError:
                continue
            if a == b:
                out[a] = f.path
    return out


def ds2_slots(ds2):
    """Playable DS2 demon IDs that have a model, with their names from the game."""
    g = t.game(ds2)
    tbl = t.read_archive_file(ds2, t.SB_DATA)
    base, count = t.find_name_table(tbl)
    out = {}
    for demon in range(1, min(count, 0xC0)):
        tid = f"{demon:03X}"
        if f"model/devil/{tid}.pb".lower() in g.index:   # the index is lower-case (04a)
            name = tbl[base + demon * t.NAME_LEN: base + (demon + 1) * t.NAME_LEN].split(b"\0")[0]
            out[tid] = name.decode("ascii", "replace") or tid
    return out


def locked_slots(ds2):
    _, data = quiet(t.load_fusion_locks, ds2, "")
    return {f"{struct.unpack_from('<I', data, i + 4)[0]:03X}" for i in range(0, len(data) - 11, 12)}


# ---------------------------------------------------------------- Custom-swap analysis

WALK_SLOTS = (9, 10)
ATTACK_SLOTS = (6, 12)
OPTIONAL_SLOTS = (5, 8)   # left empty on many confirmed reskins without trouble


def slot_frames(model):
    _, slots = t.motion_slots(model)
    return [t.motion_frames(model, s) if s else None for s in slots]


FORWARD_PRESET = "Nocturne → Devil Summoner 2"
REVERSE_PRESET = "Devil Summoner 2 → Nocturne"

# Per preset: "prefs" {destination slot: source slots in order of preference};
# "distinct" {destination: other destinations whose picks it should avoid
# repeating while another candidate exists}; "fallback": what a populated
# destination slot with no rule gets when the incoming model leaves that slot
# empty (None: stays empty; "closest": the source animation closest in length).
#
# Slot meanings (preview labels): DS2 0 idle, 1 walk, 2 injured, 4 hit,
# 5 staggered long, 6 physical attack, 7/8 cast, 9 lunge, 11 concentrating,
# 12 staggered short, 13 summoned, 14 returned, 15 victory. Nocturne 0 idle,
# 1 hit, 2 injured, 3/8/12 physical attacks, 4/5/7/11 casts, 13 idle 2,
# 14/15 negotiation; 6, 9, 10 and 16+ are unlabeled.
ANIMATION_PRESETS = {
    FORWARD_PRESET: {
        "prefs": {
            0: (0,), 1: (2,), 2: (2,), 3: (3,), 4: (1,), 5: (1,),
            6: (3, 8, 12), 7: (4, 5, 7, 11), 8: (4, 5, 7, 11),
            9: (3, 8, 12), 10: (9, 10), 11: (4, 5, 7, 11),
            13: (0, 12), 14: (0, 12), 15: (3, 4, 5, 7, 8, 11),
        },
        "distinct": {11: (7, 8)},
        "fallback": None,
    },
    REVERSE_PRESET: {
        "prefs": {
            0: (0,), 1: (4, 12, 5), 2: (2,), 3: (6, 9), 4: (7, 8, 11), 5: (8, 7, 11),
            7: (11, 7, 8), 8: (9, 6), 11: (7, 8, 11), 12: (6, 9),
            13: (0, 15), 14: (13, 15, 0), 15: (15, 13, 0),
        },
        "distinct": {5: (4,), 7: (4, 5), 11: (4, 5, 7), 8: (3,), 12: (3, 8)},
        "fallback": "closest",
    },
}


def preset_map(name, base_frames, noc_frames):
    """Resolve destination=source entries against the original source table.

    BASE_FRAMES is the destination game's original table: its empty slots
    stay empty. None explicitly clears an incoming animation from that slot.
    NOC_FRAMES is the incoming model's table (whichever game it comes from).
    """
    spec = ANIMATION_PRESETS[name]
    preferences, distinct, fallback = spec["prefs"], spec.get("distinct", {}), spec.get("fallback")
    mapping, reasons = {}, {}

    def occupied(frames, slot):
        return slot < len(frames) and frames[slot] is not None

    have = [i for i in range(len(noc_frames)) if occupied(noc_frames, i)]
    for dst in range(max(len(base_frames), len(noc_frames))):
        if not occupied(base_frames, dst):
            mapping[dst] = None
            reasons[dst] = "kept empty by preset"
            continue
        if dst not in preferences:
            if fallback == "closest" and not occupied(noc_frames, dst) and have:
                want = base_frames[dst]
                source = min(have, key=lambda j: abs(noc_frames[j] - want))
                mapping[dst] = source
                reasons[dst] = f"no rule; closest length: plays slot {source}"
            continue
        candidates = [src for src in preferences[dst] if occupied(noc_frames, src)]
        if dst in distinct:
            used = {mapping.get(other) for other in distinct[dst]}
            candidates = [src for src in candidates if src not in used] or candidates
        source = candidates[0] if candidates else None
        what = "Nocturne" if name == FORWARD_PRESET else "DS2"
        if source is None and fallback == "closest" and have:
            source = min(have, key=lambda j: abs(noc_frames[j] - base_frames[dst]))
            mapping[dst] = source
            reasons[dst] = f"no preferred {what} animation; closest length: plays slot {source}"
            continue
        mapping[dst] = source
        reasons[dst] = (f"preset: plays {what} slot {source}" if source is not None
                        else f"left empty: no preferred {what} animation available")
    return mapping, reasons


def suggest_map(base_frames, noc_frames):
    """Pick a Nocturne animation for every slot DS2 uses that the model leaves empty,
    following what worked on the confirmed reskins."""
    have = [i for i, f in enumerate(noc_frames) if f]
    mapping, reasons = {}, {}

    def closest(want):
        return min(have, key=lambda j: abs(noc_frames[j] - want))

    for slot, want in enumerate(base_frames):
        if not want or (slot < len(noc_frames) and noc_frames[slot]) or slot >= 16:
            continue
        if slot in OPTIONAL_SLOTS:
            reasons[slot] = "left empty (fine on every reskin so far)"
            continue
        if slot in ATTACK_SLOTS:
            src = next((s for s in (7, 6) if s in have), closest(want))
            why = "attack"
        elif slot in WALK_SLOTS:
            src = next((s for s in (1, 0) if s in have), closest(want))
            why = "walk/run in battle (demon glides)"
        elif slot == 14:
            src = 0 if 0 in have else closest(want)
            why = "reaction"
        elif slot == 15:
            src = 2 if 2 in have else closest(want)
            why = "reaction"
        else:
            src = closest(want)
            why = "closest length"
        mapping[slot] = src
        reasons[slot] = f"{why}: plays slot {src}"
    return mapping, reasons


def analyze(ds2, noc, noc_id, target):
    """Everything the custom-swap screen shows about one pairing."""
    models = nocturne_models(noc)
    if noc_id not in models:
        raise ValueError(f"Nocturne has no model for 0x{noc_id:02X}.")
    noc_model = t.read_archive_file(noc, models[noc_id])
    base_model = t.read_archive_file(ds2, f"model/devil/{target}.PB")
    base_frames, noc_frames = slot_frames(base_model), slot_frames(noc_model)
    mapping, reasons = suggest_map(base_frames, noc_frames)

    warnings, notes = [], []
    n_anims = sum(1 for f in noc_frames if f)
    usable = n_anims >= 3
    if not usable:
        warnings.append(f"The Nocturne model has only {n_anims} animation(s); it would play the same "
                        "motion for everything. Not usable.")
    walks = any(base_frames[s] for s in WALK_SLOTS if s < len(base_frames))
    if walks and not any(noc_frames[s] for s in WALK_SLOTS if s < len(noc_frames)):
        notes.append("The DS2 demon walks in battle; this one will glide to its target instead.")
    if target in locked_slots(ds2):
        notes.append("This slot is story-locked in fusion; the build lifts the lock.")
    if target in RESERVE_SLOTS:
        warnings.append("This is a reserve slot used by the new demons; pick a regular demon.")

    noc_bones = len(t.pb_skeleton(noc_model))
    base_bones = len(t.pb_skeleton(base_model))
    hit_path = f"battle/mdlhit/{target}.MHT"
    hit_bones = []
    if t.archive_has(ds2, hit_path):
        hit_bones = sorted({b for _, b in t.mht_records(t.read_archive_file(ds2, hit_path))})
        bad = [b for b in hit_bones if b >= noc_bones]
        if bad:
            warnings.append(f"Basic attacks hit from bone(s) {bad}, which this skeleton doesn't have "
                            f"({noc_bones} bones). Attacks may never connect.")
    score = 3
    if not usable or any("reserve" in w for w in warnings):
        score = 0
    else:
        if any("bone" in w for w in warnings):
            score -= 1
        if walks:
            score -= 1
        if len(mapping) > 5:
            score -= 1
        score = max(score, 1)
    return {
        "direction": "forward", "noc_id": noc_id, "target": target,
        "base_frames": base_frames, "noc_frames": noc_frames,
        "dst_frames": base_frames, "src_frames": noc_frames,
        "map": mapping, "reasons": reasons,
        "warnings": warnings, "notes": notes, "usable": usable and score > 0,
        "score": score, "noc_bones": noc_bones, "base_bones": base_bones, "hit_bones": hit_bones,
        "noc_size": len(noc_model), "base_size": len(base_model),
    }


def nocturne_targets(noc):
    """{noc_id: path} for Nocturne demons a DS2 model can replace (one animation pack)."""
    out = {}
    for noc_id, path in nocturne_models(noc).items():
        if t.chunk_count(t.read_archive_file(noc, path), "MT00") == 1:
            out[noc_id] = path
    return out


def analyze_reverse(ds2, noc, ds2_id, noc_id):
    """What the custom-swap screen shows for DS2 demon DS2_ID -> Nocturne demon NOC_ID."""
    models = nocturne_models(noc)
    if noc_id not in models:
        raise ValueError(f"Nocturne has no model for 0x{noc_id:02X}.")
    base_model = t.read_archive_file(noc, models[noc_id])
    _, src_model = quiet(t.find_ds2_model, ds2, int(ds2_id, 16))
    dst_frames, src_frames = slot_frames(base_model), slot_frames(src_model)
    mapping, reasons = preset_map(REVERSE_PRESET, dst_frames, src_frames)

    warnings, notes = [], []
    n_anims = sum(1 for f in src_frames if f)
    usable = n_anims >= 3
    if not usable:
        warnings.append(f"The DS2 model has only {n_anims} animation(s); it would play the same "
                        "motion for everything. Not usable.")
    if t.chunk_count(src_model, "MT00") > 1:
        usable = False
        warnings.append("The DS2 model has two animation packs, which isn't supported yet.")
    if t.chunk_count(base_model, "MT00") > 1:
        usable = False
        warnings.append("This Nocturne demon plays a second animation pack on top of its normal one "
                        "(Aquans, Mizuchi, Gogmagog, Hresvelgr); it can't be replaced yet.")
    if len(dst_frames) > len(src_frames):
        notes.append(f"This Nocturne model has {len(dst_frames)} animation slots (DS2 has "
                     f"{len(src_frames)}); the extra ones get the closest-length DS2 animation.")
    guessed = [d for d, why in reasons.items() if "closest length" in why]
    if guessed:
        notes.append(f"Slot(s) {guessed} have no matching DS2 action; they play the closest-length animation.")
    grow = len(src_model) - len(base_model)
    if grow > 0:
        notes.append(f"The DS2 model is {grow // 1024} KB bigger than the Nocturne one; if battles "
                     "with it crash, it is over Nocturne's memory budget.")
    if noc_id >= 0x100:
        notes.append("This is a boss/story version.")
    score = 3
    if not usable:
        score = 0
    else:
        if guessed:
            score -= 1
        if grow > 0:
            score -= 1
        score = max(score, 1)
    return {
        "direction": "reverse", "noc_id": noc_id, "target": ds2_id,
        "dst_frames": dst_frames, "src_frames": src_frames,
        "map": mapping, "reasons": reasons,
        "warnings": warnings, "notes": notes, "usable": usable and score > 0, "score": score,
        "noc_bones": len(t.pb_skeleton(base_model)), "base_bones": len(t.pb_skeleton(src_model)),
        "noc_size": len(base_model), "base_size": len(src_model),
    }


def check_nocturne_iso(path):
    g = check_nocturne(path)
    if not any(f.path.startswith("npackl/BU") for f in g.files):
        raise ValueError("This Nocturne copy has no npackl/ battle packs (expected the North American SLUS_209.11).")
    return g


def build_nocturne(plan, noc_iso, ds2_iso, out_iso, log=print):
    """Apply the NocReskin entries in PLAN to a copy of NOC_ISO, writing OUT_ISO."""
    plan = [p for p in plan if p.kind == "noc"]
    check_nocturne_iso(noc_iso)
    check_ds2(ds2_iso)
    slots = [p.slot for p in plan]
    dupes = sorted({s for s in slots if slots.count(s) > 1})
    if dupes:
        raise ValueError(f"Two swaps replace the same Nocturne demon: {', '.join(dupes)}")
    if os.path.abspath(out_iso) == os.path.abspath(noc_iso):
        raise ValueError("Choose a different file for the modded ISO; the original stays untouched.")
    work = tempfile.mkdtemp(prefix="nocreskin_")
    mod = os.path.join(work, "mod")
    run = _runner(log)
    try:
        for i, p in enumerate(plan, 1):
            log(f"[{i}/{len(plan)}] {p.describe()}")
            args = [noc_iso, ds2_iso, p.ds2_id, f"0x{p.noc_id:x}", mod,
                    "--map", ",".join(f"{k}={v if v is not None else '-'}" for k, v in sorted(p.map.items()))]
            if not p.share:
                args.append("--copy")
            if p.variants:
                args.append("--variants")
            run(t.cmd_noc_reskin, args)
        log("Writing the modded Nocturne ISO (this copies the whole disc; a few minutes) ...")
        if os.path.exists(out_iso):
            os.remove(out_iso)
        run(t.cmd_isopatch, [noc_iso, mod, out_iso])
        log(f"Done: {out_iso}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _runner(log):
    """run(cmd, args): call a dds3tool command, sending its output to LOG line by line."""
    class Writer(io.TextIOBase):
        def write(self, text):
            for line in text.splitlines():
                if line.strip():
                    log(line)
            return len(text)

    def run(cmd, args):
        try:
            with contextlib.redirect_stdout(Writer()):
                cmd(args)
        except SystemExit as e:
            if e.code not in (None, 0):
                raise ValueError(str(e.code).replace("error: ", "")) from None
    return run


# ---------------------------------------------------------------- Build

def build(plan, ds2_iso, noc_iso, out_iso, log=print, extra_levels=None):
    """Apply PLAN (a list of Reskin/NewDemon) to a copy of DS2_ISO, writing OUT_ISO.
    NocReskin entries (DS2 -> Nocturne) are left to build_nocturne."""
    plan = [p for p in plan if p.kind != "noc"]
    check_ds2(ds2_iso)
    check_nocturne(noc_iso)
    slots = [p.slot for p in plan]
    dupes = sorted({s for s in slots if slots.count(s) > 1})
    if dupes:
        raise ValueError(f"Two swaps use the same DS2 slot: {', '.join(dupes)}")
    if os.path.abspath(out_iso) == os.path.abspath(ds2_iso):
        raise ValueError("Choose a different file for the modded ISO; the original stays untouched.")

    work = tempfile.mkdtemp(prefix="ds2reskin_")
    mod = os.path.join(work, "mod")

    class Writer(io.TextIOBase):
        def write(self, text):
            for line in text.splitlines():
                if line.strip():
                    log(line)
            return len(text)

    def run(cmd, args):
        try:
            with contextlib.redirect_stdout(Writer()):
                cmd(args)
        except SystemExit as e:
            if e.code not in (None, 0):
                raise ValueError(str(e.code).replace("error: ", "")) from None

    try:
        renames, unlocks = [], []
        for i, p in enumerate(plan, 1):
            log(f"[{i}/{len(plan)}] {p.describe()}")
            if p.kind == "reskin":
                args = [ds2_iso, noc_iso, f"0x{p.noc_id:x}", p.target, mod]
                if p.map:
                    args += ["--map", ",".join(f"{k}={v if v is not None else '-'}" for k, v in sorted(p.map.items()))]
                if p.share:
                    args.append("--share")
                run(t.cmd_reskin, args)
                renames.append(f"{p.target}={p.name}")
                if p.unlock:
                    unlocks.append(p.target)
            else:
                run(t.cmd_add_demon, [ds2_iso, noc_iso, f"0x{p.noc_id:x}", p.template, p.reserve,
                                      p.name, mod, "--level", str(p.level)])
        if renames:
            log("Renaming demons ...")
            run(t.cmd_rename, [ds2_iso, mod] + renames)
        if unlocks:
            log("Lifting fusion locks ...")
            run(t.cmd_unlock, [ds2_iso, mod] + unlocks)
        if extra_levels:
            run(t.cmd_set_level, [ds2_iso, mod] + [f"{k}={v}" for k, v in extra_levels.items()])
        log("Writing the modded ISO (this copies the whole disc; a few minutes) ...")
        if os.path.exists(out_iso):
            os.remove(out_iso)
        run(t.cmd_isopatch, [ds2_iso, mod, out_iso])
        log(f"Done: {out_iso}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
