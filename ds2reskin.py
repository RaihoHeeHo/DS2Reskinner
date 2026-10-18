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


def m(text):
    return {int(a): int(b) for a, b in (p.split("=") for p in text.split(","))} if text else {}


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
        if f"model/devil/{tid}.pb" in g.index:
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
        "noc_id": noc_id, "target": target,
        "base_frames": base_frames, "noc_frames": noc_frames,
        "map": mapping, "reasons": reasons,
        "warnings": warnings, "notes": notes, "usable": usable and score > 0,
        "score": score, "noc_bones": noc_bones, "base_bones": base_bones, "hit_bones": hit_bones,
        "noc_size": len(noc_model), "base_size": len(base_model),
    }


# ---------------------------------------------------------------- Build

def build(plan, ds2_iso, noc_iso, out_iso, log=print, extra_levels=None):
    """Apply PLAN (a list of Reskin/NewDemon) to a copy of DS2_ISO, writing OUT_ISO."""
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
                    args += ["--map", ",".join(f"{k}={v}" for k, v in sorted(p.map.items()))]
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
