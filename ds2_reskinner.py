#!/usr/bin/env python3
"""DS2 Reskinner - put Nocturne demons into Devil Summoner 2.

Pick both game ISOs, choose Auto, Manual or Custom, and it writes a modded copy
of the Devil Summoner 2 ISO. The original ISOs are never changed.

Run:  python3 ds2_reskinner.py
"""
import os
import queue
import sys
import threading

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:
    v = f"{sys.version_info.major}.{sys.version_info.minor}"
    sys.exit(f"This Python ({v}, {sys.executable}) has no tkinter, which the window needs.\n"
             f"Homebrew Python: run   brew install python-tk@{v}\n"
             "Or install Python from https://www.python.org (it includes tkinter).")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ds2reskin as r  # noqa: E402

APP = "DS2 Reskinner"
PAD = 12


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP)
        self.geometry("980x680")
        self.minsize(860, 600)
        style = ttk.Style(self)
        if "clam" in style.theme_names() and sys.platform.startswith("linux"):
            style.theme_use("clam")
        style.configure("Title.TLabel", font=("Helvetica", 18, "bold"))
        style.configure("Sub.TLabel", foreground="#555")
        style.configure("Bad.TLabel", foreground="#b00020")
        style.configure("Good.TLabel", foreground="#1b7f3a")
        style.configure("Big.TRadiobutton", font=("Helvetica", 14, "bold"))

        self.ds2_iso = tk.StringVar()
        self.noc_iso = tk.StringVar()
        self.mode = tk.StringVar(value="auto")
        self.plan = []            # list of r.Reskin / r.NewDemon
        self.ds2_ok = self.noc_ok = False

        self.container = ttk.Frame(self, padding=PAD)
        self.container.pack(fill="both", expand=True)
        self.pages = {}
        for cls in (GamesPage, ModePage, ManualPage, CustomPage, BuildPage):
            page = cls(self.container, self)
            self.pages[cls.__name__] = page
            page.grid(row=0, column=0, sticky="nsew")
        self.container.rowconfigure(0, weight=1)
        self.container.columnconfigure(0, weight=1)
        self.show("GamesPage")

    def show(self, name):
        page = self.pages[name]
        if hasattr(page, "on_show"):
            page.on_show()
        page.tkraise()


def header(parent, title, sub):
    ttk.Label(parent, text=title, style="Title.TLabel").pack(anchor="w")
    ttk.Label(parent, text=sub, style="Sub.TLabel", wraplength=900, justify="left").pack(anchor="w", pady=(2, PAD))


def nav(parent, back=None, next_=None, next_text="Next →"):
    bar = ttk.Frame(parent)
    bar.pack(side="bottom", fill="x", pady=(PAD, 0))
    b = n = None
    if back:
        b = ttk.Button(bar, text="← Back", command=back)
        b.pack(side="left")
    if next_:
        n = ttk.Button(bar, text=next_text, command=next_)
        n.pack(side="right")
    return b, n


# ---------------------------------------------------------------- 1. Games

class GamesPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        header(self, "1. Your games",
               "Choose your Devil Summoner 2 ISO (North American, SLUS_218.45) and your Shin Megami "
               "Tensei III: Nocturne ISO. Nothing is changed in either file; the mod is written to a new copy.")
        self.rows = {}
        for key, label in (("ds2", "Devil Summoner 2 ISO"), ("noc", "Nocturne ISO")):
            box = ttk.LabelFrame(self, text=label, padding=PAD)
            box.pack(fill="x", pady=6)
            var = app.ds2_iso if key == "ds2" else app.noc_iso
            entry = ttk.Entry(box, textvariable=var)
            entry.pack(side="left", fill="x", expand=True)
            ttk.Button(box, text="Choose…", command=lambda k=key: self.pick(k)).pack(side="left", padx=(8, 0))
            status = ttk.Label(self, text="", style="Sub.TLabel")
            status.pack(anchor="w", padx=4)
            self.rows[key] = status
        _, self.next_btn = nav(self, None, self.go_next)
        self.next_btn.state(["disabled"])

    def pick(self, key):
        path = filedialog.askopenfilename(
            title="Choose the " + ("Devil Summoner 2" if key == "ds2" else "Nocturne") + " ISO",
            filetypes=[("Disc images", "*.iso *.ISO"), ("All files", "*")])
        if not path:
            return
        (self.app.ds2_iso if key == "ds2" else self.app.noc_iso).set(path)
        self.check(key)

    def check(self, key):
        path = (self.app.ds2_iso if key == "ds2" else self.app.noc_iso).get()
        label = self.rows[key]
        label.configure(text="Checking…", style="Sub.TLabel")
        self.update_idletasks()
        try:
            if key == "ds2":
                r.check_ds2(path)
                n = len(r.ds2_slots(path))
                label.configure(text=f"✓ Devil Summoner 2 (SLUS_218.45), {n} demon models", style="Good.TLabel")
                self.app.ds2_ok = True
            else:
                r.check_nocturne(path)
                n = len(r.nocturne_models(path))
                label.configure(text=f"✓ Nocturne, {n} demon models", style="Good.TLabel")
                self.app.noc_ok = True
        except (ValueError, OSError) as e:
            label.configure(text=f"✗ {e}", style="Bad.TLabel")
            if key == "ds2":
                self.app.ds2_ok = False
            else:
                self.app.noc_ok = False
        self.next_btn.state(["!disabled"] if self.app.ds2_ok and self.app.noc_ok else ["disabled"])

    def go_next(self):
        self.app.show("ModePage")


# ---------------------------------------------------------------- 2. Mode

class ModePage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        header(self, "2. How do you want to swap?", "You can come back and change this later.")
        n_reskin = sum(1 for p in r.CONFIRMED if p.kind == "reskin")
        n_new = len(r.CONFIRMED) - n_reskin
        options = [
            ("auto", "Auto swap",
             f"Everything that has been tested and works: {n_reskin} Nocturne demons replace DS2 demons, "
             f"and {n_new} more are added as new demons in unused slots."),
            ("manual", "Manual swap",
             "Pick which of the tested swaps you want. Anything you leave out stays as the original DS2 demon."),
            ("custom", "Custom swap",
             "Put any Nocturne demon on any DS2 demon. The program compares the two models, warns about "
             "problems, and suggests the animation fixes that worked for the tested swaps. Untested swaps "
             "can still misbehave in game."),
        ]
        for value, title, text in options:
            card = ttk.Frame(self, padding=(4, 10))
            card.pack(fill="x")
            ttk.Radiobutton(card, text=title, value=value, variable=app.mode,
                            style="Big.TRadiobutton").pack(anchor="w")
            ttk.Label(card, text=text, style="Sub.TLabel", wraplength=860,
                      justify="left").pack(anchor="w", padx=(26, 0))
        nav(self, lambda: app.show("GamesPage"), self.go_next)

    def go_next(self):
        mode = self.app.mode.get()
        if mode == "auto":
            self.app.plan = list(r.CONFIRMED)
            self.app.show("BuildPage")
        elif mode == "manual":
            self.app.show("ManualPage")
        else:
            self.app.show("CustomPage")


# ---------------------------------------------------------------- 3a. Manual

class ManualPage(ttk.Frame):
    ON, OFF = "☑", "☐"

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        header(self, "3. Choose swaps", "Click a row to tick or untick it. Every swap here has been tested in game.")
        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Button(bar, text="Select all", command=lambda: self.set_all(True)).pack(side="left")
        ttk.Button(bar, text="Select none", command=lambda: self.set_all(False)).pack(side="left", padx=6)
        self.count = ttk.Label(bar, text="", style="Sub.TLabel")
        self.count.pack(side="right")

        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, pady=(8, 0))
        cols = ("on", "demon", "what", "level", "notes")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="none")
        for c, text, w in (("on", "", 34), ("demon", "Nocturne demon", 150), ("what", "Goes into", 290),
                           ("level", "Level", 60), ("notes", "Notes", 260)):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, anchor="center" if c in ("on", "level") else "w", stretch=c == "notes")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self.toggle)
        self.checked = {}
        for i, p in enumerate(r.CONFIRMED):
            if p.kind == "reskin":
                what = f"replaces {r.ds2_name(p.target)} ({p.target})"
                level = r.ds2_info(p.target)["level"]
            else:
                what = f"new demon (reserve slot {p.reserve})"
                level = p.level
            notes = p.note + ("; fusion lock lifted" if p.unlock else "")
            self.tree.insert("", "end", iid=str(i), values=(self.ON, p.name, what, level, notes.strip("; ")))
            self.checked[str(i)] = True
        self.update_count()
        nav(self, lambda: app.show("ModePage"), self.go_next)

    def toggle(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            self.checked[iid] = not self.checked[iid]
            self.tree.set(iid, "on", self.ON if self.checked[iid] else self.OFF)
            self.update_count()

    def set_all(self, on):
        for iid in self.checked:
            self.checked[iid] = on
            self.tree.set(iid, "on", self.ON if on else self.OFF)
        self.update_count()

    def update_count(self):
        self.count.configure(text=f"{sum(self.checked.values())} of {len(self.checked)} selected")

    def go_next(self):
        self.app.plan = [r.CONFIRMED[int(i)] for i, on in self.checked.items() if on]
        if not self.app.plan:
            messagebox.showinfo(APP, "Tick at least one swap.")
            return
        self.app.show("BuildPage")


# ---------------------------------------------------------------- 3b. Custom

class SearchList(ttk.Frame):
    """A filter box over a list of (key, label) items."""

    def __init__(self, parent, title, on_select):
        super().__init__(parent)
        ttk.Label(self, text=title, font=("Helvetica", 12, "bold")).pack(anchor="w")
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self.refill())
        ttk.Entry(self, textvariable=self.filter).pack(fill="x", pady=(2, 4))
        box = ttk.Frame(self)
        box.pack(fill="both", expand=True)
        self.lb = tk.Listbox(box, exportselection=False, activestyle="none", height=12)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lb.bind("<<ListboxSelect>>", lambda e: on_select(self.selected()))
        self.items, self.shown = [], []

    def set_items(self, items):
        self.items = items
        self.refill()

    def refill(self):
        f = self.filter.get().lower()
        self.shown = [(k, lab) for k, lab in self.items if f in lab.lower()]
        self.lb.delete(0, "end")
        for _, lab in self.shown:
            self.lb.insert("end", lab)

    def selected(self):
        sel = self.lb.curselection()
        return self.shown[sel[0]][0] if sel else None


class CustomPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.analysis = None
        self.loaded_for = None
        header(self, "3. Custom swaps",
               "Pick a Nocturne demon and the DS2 demon it should replace, check the report, then add it "
               "to your list. Tested swaps can be added in one click.")
        nav(self, lambda: app.show("ModePage"), self.go_next)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)

        # Left: pickers
        left = ttk.Frame(body, padding=(0, 0, 8, 0), width=240)
        self.noc_list = SearchList(left, "Nocturne demon", lambda k: self.analyze())
        self.noc_list.pack(fill="both", expand=True)
        self.ds2_list = SearchList(left, "Replaces DS2 demon", lambda k: self.analyze())
        self.ds2_list.pack(fill="both", expand=True, pady=(8, 0))
        body.add(left, weight=1)

        # Middle: report
        mid = ttk.Frame(body, padding=(8, 0))
        self.verdict = ttk.Label(mid, text="Pick a demon on each side.", font=("Helvetica", 13, "bold"),
                                 wraplength=360, justify="left")
        self.verdict.pack(anchor="w")
        self.report = tk.Text(mid, height=5, wrap="word", relief="flat", background="#f4f4f4",
                              foreground="#222222")
        self.report.pack(fill="x", pady=(4, 6))
        self.report.tag_configure("bad", foreground="#b00020")
        self.report.tag_configure("note", foreground="#555")
        form = ttk.Frame(mid)
        form.pack(fill="x", pady=(0, 6))
        ttk.Label(form, text="Name in game").grid(row=0, column=0, sticky="w")
        self.name = tk.StringVar()
        ttk.Entry(form, textvariable=self.name, width=22).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(form, text="Animation fixes").grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.map_text = tk.StringVar()
        ttk.Entry(form, textvariable=self.map_text, width=30).grid(row=1, column=1, sticky="w", padx=6, pady=(4, 0))
        ttk.Label(form, text="slot=source, e.g. 6=7,12=7", style="Sub.TLabel").grid(row=1, column=2, sticky="w")
        self.add_btn = ttk.Button(form, text="Add to my list →", command=self.add)
        self.add_btn.grid(row=0, column=2, sticky="e")
        self.add_btn.state(["disabled"])
        cols = ("slot", "ds2", "noc", "plan")
        self.slots = ttk.Treeview(mid, columns=cols, show="headings", height=10)
        for c, text, w in (("slot", "Slot", 44), ("ds2", "DS2", 60), ("noc", "Nocturne", 72),
                           ("plan", "Fix", 200)):
            self.slots.heading(c, text=text)
            self.slots.column(c, width=w, anchor="w" if c == "plan" else "center", stretch=c == "plan")
        self.slots.tag_configure("fix", foreground="#1b5fbf")
        self.slots.pack(fill="both", expand=True)

        body.add(mid, weight=2)

        # Right: plan
        right = ttk.Frame(body, padding=(8, 0, 0, 0))
        ttk.Label(right, text="My list", font=("Helvetica", 12, "bold")).pack(anchor="w")
        self.plan_tree = ttk.Treeview(right, columns=("demon", "slot"), show="headings")
        self.plan_tree.heading("demon", text="Demon")
        self.plan_tree.heading("slot", text="Slot")
        self.plan_tree.column("demon", width=120)
        self.plan_tree.column("slot", width=110)
        self.plan_tree.pack(fill="both", expand=True, pady=(2, 4))
        ttk.Button(right, text="Remove selected", command=self.remove).pack(fill="x")
        ttk.Button(right, text="Add all tested swaps", command=self.add_confirmed).pack(fill="x", pady=4)
        ttk.Button(right, text="Clear list", command=self.clear).pack(fill="x")
        body.add(right, weight=1)

    # -- data
    def on_show(self):
        key = (self.app.ds2_iso.get(), self.app.noc_iso.get())
        if self.loaded_for == key:
            return
        self.loaded_for = key
        self.app.config(cursor="watch")
        self.update_idletasks()
        try:
            noc_models = r.nocturne_models(key[1])
            self.noc_list.set_items([(i, f"0x{i:02X}  {r.noc_name(i)}") for i in sorted(noc_models)])
            self.ds2_names = r.ds2_slots(key[0])
            self.locks = r.locked_slots(key[0])
            self.refresh_ds2()
        finally:
            self.app.config(cursor="")

    def taken(self):
        return {p.slot: p.name for p in self.app.plan}

    def refresh_ds2(self):
        taken = self.taken()
        items = []
        for tid, name in sorted(self.ds2_names.items()):
            if tid in r.RESERVE_SLOTS:
                continue
            info = r.ds2_info(tid)
            tag = f"  → {taken[tid]}" if tid in taken else ""
            lock = "  (locked)" if tid in self.locks else ""
            items.append((tid, f"{tid}  {name}  (Lv {info['level']}, {info['race']}){lock}{tag}"))
        self.ds2_list.set_items(items)
        self.plan_tree.delete(*self.plan_tree.get_children())
        for i, p in enumerate(self.app.plan):
            where = f"{p.target} {r.ds2_name(p.target)}" if p.kind == "reskin" else f"new ({p.reserve})"
            self.plan_tree.insert("", "end", iid=str(i), values=(p.name, where))

    # -- analysis
    def analyze(self):
        noc_id, target = self.noc_list.selected(), self.ds2_list.selected()
        if noc_id is None or target is None:
            return
        self.app.config(cursor="watch")
        self.update_idletasks()
        try:
            a = r.analyze(self.app.ds2_iso.get(), self.app.noc_iso.get(), noc_id, target)
        except (ValueError, OSError) as e:
            self.verdict.configure(text=f"Can't analyze: {e}")
            self.add_btn.state(["disabled"])
            return
        finally:
            self.app.config(cursor="")
        self.analysis = a
        stars = "★" * a["score"] + "☆" * (3 - a["score"])
        if not a["usable"]:
            verdict = f"{stars}  Not usable"
        else:
            verdict = {3: "Good match", 2: "Should work", 1: "Risky"}[a["score"]]
            verdict = f"{stars}  {verdict}"
        tested = next((p for p in r.CONFIRMED if p.kind == "reskin" and p.noc_id == noc_id
                       and p.target == target), None)
        if tested:
            verdict += "  (tested in game)"
        self.verdict.configure(text=f"{r.noc_name(noc_id)} → {r.ds2_name(target)}:  {verdict}")

        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        for w in a["warnings"]:
            self.report.insert("end", "⚠ " + w + "\n", "bad")
        for n in a["notes"]:
            self.report.insert("end", "• " + n + "\n", "note")
        self.report.insert("end", f"• Skeletons: {a['noc_bones']} bones vs {a['base_bones']} in the DS2 model.\n", "note")
        if target in self.taken():
            self.report.insert("end", f"⚠ {target} is already used by {self.taken()[target]} in your list.\n", "bad")
        if not a["warnings"] and not a["map"]:
            self.report.insert("end", "• No animation fixes needed.\n", "note")
        self.report.configure(state="disabled")

        self.slots.delete(*self.slots.get_children())
        n = max(len(a["base_frames"]), len(a["noc_frames"]))
        for s in range(n):
            b = a["base_frames"][s] if s < len(a["base_frames"]) else None
            c = a["noc_frames"][s] if s < len(a["noc_frames"]) else None
            fix = a["reasons"].get(s, "")
            self.slots.insert("", "end", values=(s, b or "–", c or "–", fix), tags=("fix",) if fix else ())

        mapping = tested.map if tested else a["map"]
        self.map_text.set(",".join(f"{k}={v}" for k, v in sorted(mapping.items())))
        self.name.set(tested.name if tested else r.noc_name(noc_id)[:20])
        self.add_btn.state(["!disabled"] if a["usable"] else ["disabled"])

    def add(self):
        a = self.analysis
        if not a:
            return
        name = self.name.get().strip()
        if not name or len(name.encode("ascii", "replace")) > 20:
            messagebox.showerror(APP, "Give it a name of 1–20 plain letters.")
            return
        try:
            mapping = r.m(self.map_text.get().replace(" ", ""))
        except ValueError:
            messagebox.showerror(APP, "Animation fixes must look like 6=7,12=7.")
            return
        have = {i for i, f in enumerate(a["noc_frames"]) if f}
        bad = [v for v in mapping.values() if v not in have]
        if bad:
            messagebox.showerror(APP, f"The Nocturne model has nothing in slot(s) {bad} to copy from.")
            return
        target = a["target"]
        if target in self.taken():
            if not messagebox.askyesno(APP, f"{target} is already used by {self.taken()[target]}. Replace it?"):
                return
            self.app.plan = [p for p in self.app.plan if p.slot != target]
        self.app.plan.append(r.Reskin(name, a["noc_id"], target, mapping, share=True,
                                      unlock=target in self.locks))
        self.refresh_ds2()

    def remove(self):
        drop = {int(i) for i in self.plan_tree.selection()}
        self.app.plan = [p for i, p in enumerate(self.app.plan) if i not in drop]
        self.refresh_ds2()

    def add_confirmed(self):
        taken = self.taken()
        clash = [p for p in r.CONFIRMED if p.slot in taken and taken[p.slot] != p.name]
        if clash and not messagebox.askyesno(
                APP, "Your list already uses " + ", ".join(p.slot for p in clash) +
                     ". Keep your choices there and add the rest?"):
            return
        self.app.plan += [p for p in r.CONFIRMED if p.slot not in taken]
        self.refresh_ds2()

    def clear(self):
        self.app.plan = []
        self.refresh_ds2()

    def go_next(self):
        if not self.app.plan:
            messagebox.showinfo(APP, "Add at least one swap to your list.")
            return
        self.app.show("BuildPage")


# ---------------------------------------------------------------- 4. Build

class BuildPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        header(self, "4. Build the modded ISO",
               "This copies your Devil Summoner 2 ISO and patches the copy. It takes a few minutes. "
               "Start the game from an in-game save, not a PCSX2 save state, so the new models load.")
        out = ttk.LabelFrame(self, text="Save the modded ISO as", padding=PAD)
        out.pack(fill="x")
        self.out = tk.StringVar()
        ttk.Entry(out, textvariable=self.out).pack(side="left", fill="x", expand=True)
        ttk.Button(out, text="Choose…", command=self.pick).pack(side="left", padx=(8, 0))
        self.summary = ttk.Label(self, text="", wraplength=900, justify="left")
        self.summary.pack(anchor="w", pady=PAD)
        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x")
        self.log = tk.Text(self, height=16, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, pady=(8, 0))
        self.back_btn, self.build_btn = nav(self, self.go_back, self.start, "Build ISO")
        self.q = queue.Queue()
        self.thread = None

    def on_show(self):
        src = self.app.ds2_iso.get()
        if not self.out.get() and src:
            stem, ext = os.path.splitext(src)
            self.out.set(f"{stem}_mod{ext or '.iso'}")
        reskins = [p for p in self.app.plan if p.kind == "reskin"]
        new = [p for p in self.app.plan if p.kind == "new"]
        untested = [p for p in self.app.plan if p not in r.CONFIRMED]
        text = f"{len(reskins)} reskin(s) and {len(new)} new demon(s): " + ", ".join(p.name for p in self.app.plan) + "."
        if untested:
            text += (f"\n{len(untested)} of them are your own untested swaps; if one crashes or misbehaves, "
                     "come back and change or drop it.")
        self.summary.configure(text=text)
        self.progress.configure(value=0, maximum=len(self.app.plan) + 3)

    def go_back(self):
        self.app.show({"auto": "ModePage", "manual": "ManualPage", "custom": "CustomPage"}[self.app.mode.get()])

    def pick(self):
        path = filedialog.asksaveasfilename(title="Save the modded ISO as", defaultextension=".iso",
                                            initialfile=os.path.basename(self.out.get() or "DS2_mod.iso"),
                                            filetypes=[("Disc images", "*.iso")])
        if path:
            self.out.set(path)

    def write(self, line):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def start(self):
        out = self.out.get().strip()
        if not out:
            messagebox.showerror(APP, "Choose where to save the modded ISO.")
            return
        if os.path.abspath(out) in (os.path.abspath(self.app.ds2_iso.get()), os.path.abspath(self.app.noc_iso.get())):
            messagebox.showerror(APP, "Save the mod under a new name; your original ISOs stay untouched.")
            return
        if os.path.exists(out) and not messagebox.askyesno(APP, f"{os.path.basename(out)} exists. Replace it?"):
            return
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.progress.configure(value=0)
        for b in (self.back_btn, self.build_btn):
            b.state(["disabled"])
        plan, ds2, noc = list(self.app.plan), self.app.ds2_iso.get(), self.app.noc_iso.get()

        def work():
            try:
                r.build(plan, ds2, noc, out, log=lambda s: self.q.put(("log", s)))
                self.q.put(("done", out))
            except Exception as e:  # shown to the user, build left unfinished
                self.q.put(("error", str(e)))

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        self.after(100, self.poll)

    def poll(self):
        try:
            while True:
                kind, value = self.q.get_nowait()
                if kind == "log":
                    if value.startswith("[") or value.startswith(("Renaming", "Lifting", "Writing")):
                        self.progress.step(1)
                    self.write(value)
                elif kind == "done":
                    self.progress.configure(value=self.progress["maximum"])
                    self.finish()
                    messagebox.showinfo(APP, f"Done!\n\n{value}\n\nLoad it in PCSX2 and start from an in-game save.")
                    return
                else:
                    self.finish()
                    self.write("ERROR: " + value)
                    messagebox.showerror(APP, f"The build stopped:\n\n{value}")
                    return
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def finish(self):
        for b in (self.back_btn, self.build_btn):
            b.state(["!disabled"])


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    App().mainloop()


if __name__ == "__main__":
    main()
