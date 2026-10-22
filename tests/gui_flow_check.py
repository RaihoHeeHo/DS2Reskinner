"""Drive ds2_reskinner's pages with a fake tkinter (no display needed).

Manual check against real games, not part of the unit tests:
    python3 tests/gui_flow_check.py . NOCTURNE.iso DS2.iso
"""
import sys, types, threading
sys.path.insert(0, sys.argv[1])

class Var:
    def __init__(self, value=None, **k): self.v = value; self.cbs = []
    def get(self): return self.v
    def set(self, v):
        self.v = v
        for cb in self.cbs: cb()
    def trace_add(self, mode, cb): self.cbs.append(cb)

class W:
    def __init__(self, *a, **k): self.kw = dict(k); self.states = set()
    def __getattr__(self, name): return lambda *a, **k: None
    def configure(self, *a, **k): self.kw.update(k)
    config = configure
    def state(self, s=None):
        for x in s or []:
            (self.states.discard(x[1:]) if x.startswith("!") else self.states.add(x))
        return self.states
    def __getitem__(self, k): return self.kw.get(k, 0)

class Listbox(W):
    def __init__(self, *a, **k): super().__init__(*a, **k); self.rows = []; self.sel = ()
    def delete(self, *a): self.rows = []; self.sel = ()
    def insert(self, where, text): self.rows.append(text)
    def curselection(self): return self.sel

class Tree(W):
    def __init__(self, *a, **k): super().__init__(*a, **k); self.rows = {}; self.n = 0; self.sel = ()
    def insert(self, parent, where, iid=None, values=(), tags=()):
        iid = iid or f"I{self.n}"; self.n += 1; self.rows[iid] = {"values": list(values)}; return iid
    def delete(self, *iids):
        for i in iids: self.rows.pop(i, None)
    def get_children(self): return list(self.rows)
    def item(self, iid, key=None, values=None, tags=None):
        if values is not None: self.rows[iid]["values"] = list(values); return
        return self.rows[iid][key] if key else self.rows[iid]
    def selection(self): return self.sel

tk = types.ModuleType("tkinter"); ttk = types.ModuleType("tkinter.ttk")
for n in ("Tk", "Menu", "Text"): setattr(tk, n, W)
class StringVar(Var):
    def __init__(self, value="", **k): super().__init__(value)
class BooleanVar(Var):
    def __init__(self, value=False, **k): super().__init__(value)
tk.Listbox = Listbox; tk.StringVar = StringVar; tk.BooleanVar = BooleanVar
for n in ("Frame", "Label", "Button", "Entry", "LabelFrame", "Radiobutton", "Checkbutton", "Combobox",
          "Scrollbar", "Panedwindow", "Progressbar", "Style"):
    setattr(ttk, n, W)
ttk.Treeview = Tree
class Style(W):
    def theme_names(self): return ()
ttk.Style = Style
answers = []
mb = types.SimpleNamespace(showerror=lambda *a: answers.append(("error",) + a),
                           showinfo=lambda *a: answers.append(("info",) + a), askyesno=lambda *a: True)
fd = types.SimpleNamespace()
tk.ttk, tk.messagebox, tk.filedialog = ttk, mb, fd
sys.modules.update({"tkinter": tk, "tkinter.ttk": ttk, "tkinter.messagebox": mb, "tkinter.filedialog": fd})

import ds2_reskinner as g, ds2reskin as r
app = g.App(); app.ds2_iso.set(sys.argv[3]); app.noc_iso.set(sys.argv[2])
page = app.pages["CustomPage"]; page.on_show()

def pick(lst, key):
    lst.lb.sel = (next(i for i, (k, _) in enumerate(lst.shown) if k == key),); page.analyze()

# reverse: DS2 Angel -> Nocturne Pixie
page.direction.set(r.REVERSE_PRESET); page.on_direction()
assert page.src_list.title_label.kw["text"] == "Devil Summoner 2 demon"
assert all(isinstance(k, str) for k, _ in page.src_list.items)
assert 0x4E not in [k for k, _ in page.dst_list.items], "two-pack Mizuchi must not be offered"
pick(page.src_list, "04A"); pick(page.dst_list, 0x3D)
print("reverse verdict:", page.verdict.kw["text"]); print("reverse map:", page.map_text.get())
assert "add" not in page.add_btn.states and "disabled" not in page.add_btn.states
page.variants.set(True); page.add()
p = app.plan[-1]; assert p.kind == "noc" and p.ds2_id == "04A" and p.noc_id == 0x3D and p.variants, vars(p)
assert any("→ Angel" in lab for _, lab in page.dst_list.items), "taken mark"
# bad map is rejected
page.map_text.set("1=3"); page.add(); assert answers and answers[-1][0] == "error", answers[-1:]
print("bad map rejected:", answers[-1][2])
# forward: Nocturne Pixie -> DS2 Angel
page.direction.set(r.FORWARD_PRESET); page.on_direction()
assert page.animation_preset.get() == "Current suggestions"
pick(page.src_list, 0x3D); pick(page.dst_list, "04A")
print("forward verdict:", page.verdict.kw["text"]); page.add()
assert [q.kind for q in app.plan] == ["noc", "reskin"], [q.kind for q in app.plan]
print("plan:", [row["values"] for row in page.plan_tree.rows.values()])

# build page with the real builds stubbed
calls = []
r.build = lambda plan, ds2, noc, out, log=print, **k: calls.append(("ds2", out, [q.kind for q in plan]))
r.build_nocturne = lambda plan, noc, ds2, out, log=print: calls.append(("noc", out, [q.kind for q in plan]))
bp = app.pages["BuildPage"]; bp.on_show()
print("summary:", bp.summary.kw["text"]); print("outputs:", bp.out.get(), "|", bp.out2.get())
assert bp.targets() == (True, True)
bp.out.set("/tmp/ds2_out.iso"); bp.out2.set("/tmp/noc_out.iso")
bp.start(); bp.thread.join(); print("build calls:", calls)
assert [c[0] for c in calls] == ["ds2", "noc"]
bp.out2.set(bp.out.get()); answers.clear(); bp.start(); assert answers and "different" in answers[-1][2]
print("GUI FLOW OK")
