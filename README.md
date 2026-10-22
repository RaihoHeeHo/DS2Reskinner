# DS2 Reskinner (GUI)

## Download (no Python needed)

Get the zip for your system from the [Releases](../../releases) page, unzip it
and open **DS2 Reskinner**.

- **macOS:** take `macOS-AppleSilicon` for M1/M2/M3/M4 Macs and `macOS-Intel`
  for older Intel Macs (Apple menu → About This Mac shows which). The first
  time, right-click the app and choose **Open** (it isn't signed by Apple).
- **Windows:** if SmartScreen warns about an unknown app, click
  **More info → Run anyway**.
- **Linux:** run `./"DS2 Reskinner"` (it needs Tk, which most desktops have).

## Run from source

Needs Python 3.9 or newer with tkinter. Download the code, then:

| System | Start it with | If tkinter is missing |
|---|---|---|
| macOS | double-click `DS2 Reskinner.command` | `brew install python-tk@3.X` (your Python version), or use python.org Python |
| Windows | double-click `DS2 Reskinner.bat` | install Python from python.org with "Add python.exe to PATH" ticked |
| Linux | `./ds2-reskinner.sh` | `sudo apt install python3-tk` (Debian/Ubuntu), `sudo dnf install python3-tkinter` (Fedora), `sudo pacman -S tk` (Arch) |

Or run `python3 ds2_reskinner.py` anywhere.

## Using it

1. Choose your Devil Summoner 2 ISO (North American, SLUS_218.45) and your
   Nocturne ISO. Neither file is changed.
2. Pick a mode:
   - **Auto swap**: every tested swap (29 reskins and 5 new demons).
   - **Manual swap**: tick the tested swaps you want.
   - **Custom swap**: put any Nocturne demon on any DS2 demon, or (with
     **Direction → Devil Summoner 2 → Nocturne**) any DS2 demon on any
     Nocturne demon; see [DS2 demons in Nocturne](#ds2-demons-in-nocturne). The program
     compares both models' animation slots, warns about one-animation models,
     missing hit bones, walking demons and story locks, and fills in the
     animation fixes that worked for the tested swaps. You can edit them.
3. Choose where to save the modded ISO and press **Build ISO**.

In **Custom swap**, select **Nocturne → Devil Summoner 2** under **Animation
preset** and press **Apply preset**. It follows the preset's source preference
order, skips missing Nocturne animations, and prefers a different cast for DS2
slot 11 than the ones assigned to slots 7/8. Original DS2 empty slots stay
empty, even when the incoming Nocturne slot is populated. If all preferred
sources are missing, the destination is left empty. Populated slots without a
preset rule (12 and 16) retain their incoming contents. The preset stays
selected for subsequent pairings; **Current suggestions** restores the existing
suggestion behavior. Tested Auto/Manual recipes are unchanged.

The editable mapping field uses **DS2 destination = Nocturne source**, so
`6=3` puts Nocturne's slot 3 in DS2's slot 6. `10=-` explicitly empties DS2
slot 10. The slot report shows the resolved mapping before you add the swap.

Start the game from an in-game save, not a PCSX2 save state.

## DS2 demons in Nocturne

In **Custom swap**, choose **Direction → Devil Summoner 2 → Nocturne**, pick a
DS2 demon and the Nocturne demon it replaces. Both games use the same model
format, so the model and its textures go over unchanged; what changes is the
animation table, because the slot numbers mean different things (DS2 slot 1 is
a walk, Nocturne slot 1 is getting hit). The **Devil Summoner 2 → Nocturne**
preset fills every slot the Nocturne demon uses:

| Nocturne slot | DS2 source, in order of preference |
|---|---|
| 0 idle | 0 idle |
| 1 hit | 4 hit, 12 staggered short, 5 staggered long |
| 2 injured | 2 injured |
| 3 / 12 physical attack | 6 physical attack, 9 lunge |
| 8 physical attack 2 | 9 lunge, 6 physical attack |
| 4 / 5 / 7 / 11 casts | 7, 8, 11 (different ones where possible) |
| 13 idle 2 | 0 idle, 15 victory |
| 14 / 15 negotiation | 13 summoned / 15 victory, then idle |
| anything else it uses | DS2's own slot if filled, else the closest-length animation |

Nocturne's empty slots stay empty, and the table is sized to the Nocturne
model (16 slots for most, up to 26 for some). Nocturne keeps three copies of
each model and all three are replaced: `model/devil/0xH0/0xID/0xID.PB`, the
battle pack `npackl/BU<ID>.LB`, and `model/devil/on/0xID_on.PB`, which the
compendium and party status screens show. **Also replace its
boss/story versions** puts it into the packs of boss and story versions that
share the model (Thor 0x12E and 0x151, for example). Aquans, Mizuchi, Gogmagog
and Hresvelgr play a second animation pack on top of their normal one and
can't be replaced yet. If a list has swaps in both directions, the build writes
one modded ISO per game.

The **Name in game** field renames the Nocturne demon (14 characters at most)
in battle, the compendium and menus. Names live in a pointer table in the
program file (`SLUS_209.11`). A name another Nocturne demon already has costs
nothing; new names go into about 128 bytes of unused space in the program file
(roughly ten names), and after that only into the old name's own space.
Dialogue that mentions a demon by name is not changed.

Every command below also accepts a game ISO wherever it asks for a game
folder (`ds2`, `nocturne`), so nothing has to be extracted first.

# dds3tool (command line)

List, extract and patch the `DDS3.IMG` / `DDS3.DDT` archive used by Atlus's
PS2 games on this engine (Nocturne, Digital Devil Saga 1/2, Devil Summoner 1/2).
Pure Python 3, no dependencies, runs on macOS.

## List

```
python3 dds3tool.py list DDS3.DDT                 # everything
python3 dds3tool.py list DDS3.DDT model/devil/    # one folder
```

## Extract

```
python3 dds3tool.py extract DDS3.DDT DDS3.IMG extracted                       # all ~10,000 files
python3 dds3tool.py extract DDS3.DDT DDS3.IMG extracted model/devil battle    # just these folders
```

## Patch

Put replacement files in a folder that mirrors the archive paths:

```
mod/
  model/devil/000.PB
  battle/SB_DATA.TBL
```

Then:

```
python3 dds3tool.py patch DDS3.DDT DDS3.IMG mod patched
```

This writes `patched/DDS3.IMG` and `patched/DDS3.DDT`. Files that still fit in
their original space are overwritten there; bigger files are appended to the
end of the IMG. Your original files are not touched.

## Reskin a DS2 demon with a Nocturne model (one command)

With each game's `DDS3.DDT` and `DDS3.IMG` in its own folder (`ds2/`, `nocturne/`):

```
python3 dds3tool.py reskin ds2 nocturne 0x42 04A mod    # Principality -> Angel
python3 dds3tool.py isopatch DS2.ISO mod ~/Desktop/DS2_mod.iso
```

The IDs come from `Nocturne_demon_ids.txt` and `DS2_demon_ids.txt`. Several
reskins can go into the same `mod` folder before running `isopatch` once.
Test from an in-game save, not a PCSX2 save state: a save state brings back
models that were already loaded.

## Put a DS2 demon into Nocturne (one command)

```
python3 dds3tool.py noc-reskin nocturne ds2 04A 0x3D mod     # DS2 Angel -> Nocturne Pixie
python3 dds3tool.py isopatch Nocturne.iso mod ~/Desktop/Nocturne_mod.iso
```

Without `--map` the "Devil Summoner 2 → Nocturne" preset maps the animations
(see the GUI section above). `--map 1=4,3=6,9=-` uses **Nocturne slot = DS2
slot** instead. Remapped slots share the existing animation data, so the model
doesn't grow; `--copy` gives each its own copy. `--variants` also writes the
model into boss/story packs and `model/devil/boss/` files that carried the same
Nocturne model (it unpacks every pack, so it takes longer).

```
python3 dds3tool.py noc-names nocturne                    # IDs and names
python3 dds3tool.py noc-rename nocturne mod 0x3D=Angel    # writes mod/SLUS_209.11
```

Nocturne battles load demons from `npackl/BU<ID>.LB`: one `PAC` entry holding
a `BPAC` pack whose entry 0 is a byte-for-byte copy of the demon's PB (true for
all 189 demon models) and whose other entries are the demon's battle effects:

```
+0x00 u32 0      +0x04 u32 size after the header   +0x08 "BPAC"   +0x0C u32 0
+0x10 u32 count  +0x14 u32 1, u32 0, u32 0
+0x20 count × { u32 tag (0 model, 1/2 effects), u32 size, u32 1, u32 offset }
header padded to 16 bytes; entries follow back to back
```



DS2's demon list has unused "reserve" slots (Pyro reserve 1 = 012, Frost
reserve 1 = 029, Volt reserve 1 = 03D, Spirit reserve 1 = 0A8...). This turns
one into a new demon: it copies a template demon's stats, skills, race,
battle settings, sounds and hit data, puts the Nocturne model on it and names
it. The template demon stays as it is.

```
python3 dds3tool.py add-demon ds2 nocturne 0x40 04A 012 Virtue mod --level 20
```

Stats come from the template, so pick one near the level you give it.

The game's program file has per-demon file-name tables (menu models, models,
battle textures and HP-bar icons) where reserve slots point at placeholders or
nothing; a missing icon crashes the game when the demon takes damage. Copy the
program file into your DS2 folder once (`cp /Volumes/<disc>/SLUS_218.45 ds2/`)
and `add-demon` fixes all of these, writing `mod/SLUS_218.45`; `isopatch` puts
it on the disc. New names go into unused padding in the program file, which
has room for the five reserve slots that have model files (012, 013, 029,
03D, 0A8).

## Demons that don't move in battle

Nocturne models have no walk/run animations, and DS2 moves ground demons in
battle with exactly those. Reskin onto demons that float instead; this lists them:

```
python3 dds3tool.py bases ds2
```

Animations sit in numbered slots. `reskin` and `add-demon` extend Nocturne's
16-slot table to DS2's 17 and otherwise leave the animations alone; the game
copes with empty slots. All copies of a model (menu/field/battle) must match.

The animation section ends with a packed list of which slot entries the game
converts to pointers when it loads the model. The tool rewrites that list
whenever it fills slots, so filled slots work. `--fill` copies the
closest-length animation into each empty slot the DS2 original uses; `--map`
picks them yourself:

```
python3 dds3tool.py reskin ds2 nocturne 0x33 088 mod --map 6=7,12=7
```

Filled slots get their own copy of the animation by default, which makes the
model bigger. A model that gets too big overruns its battle memory and crashes.
`--share` points the filled slots at the existing animation instead, adding
no bytes.

To inspect slots (and their lengths in frames):

```
python3 dds3tool.py motions model.PB                     # - = empty slot
python3 dds3tool.py compare ds2 nocturne 0x42 04A        # both models side by side
```

## Rename demons

Names live in `battle/SB_DATA.TBL` (20 characters max). This writes the
changed table into the mod folder, keeping earlier edits:

```
python3 dds3tool.py names ds2                            # list IDs and names
python3 dds3tool.py rename ds2 mod 04A=Principality 0B5=Eligor
```

Enemy versions of a demon (IDs 0C0 and up) keep their own names.

## Fusion locks

Some demons can't be fused until a story or side-quest event sets a flag
(Oberon 098, Titania 099, the Fiends and others). A reskin on one of those
slots inherits the lock. List them, or lift a lock:

```
python3 dds3tool.py locks ds2                 # demon ID and the flag it waits for
python3 dds3tool.py unlock ds2 mod 099        # fusable without the event
```

## Fix attacks that animate but don't hit

Basic attacks hit through spheres attached to bones, listed in
`battle/mdlhit/<ID>.MHT` (and entry 2 of the battle LB). After a reskin, those
bone numbers refer to the old skeleton. List both skeletons, pick the new
model's matching bones (usually the weapon tip or hand), and rewrite them:

```
python3 dds3tool.py bones model.PB                     # bones with rest-pose positions
python3 dds3tool.py mht-list 08D.MHT                    # which bones the hits use
python3 dds3tool.py mht-bones 08D.MHT mod/battle/mdlhit/08D.MHT 0=113 1=115
python3 dds3tool.py lb-replace mod/model_lb/devil_b/08D.LB 2 mod/battle/mdlhit/08D.MHT mod/model_lb/devil_b/08D.LB
```

## LB containers (battle models)

Some models live inside compressed `.LB` containers. In Devil Summoner 2:

| File | Used for |
|---|---|
| `model/devil/<ID>.PB` | not seen on screen so far |
| `model/devil_hi/<ID>_hi.PB` | fusion and status menus |
| `model_lb/devil_b/<ID>.LB` | battle (entry 0 is the model) |
| `model/devil_lb/DEVIL<ID>.LB` | field (entry 0 is the model) |

(`model/field_lb/FIELD<ID>.LB` is unrelated: field effects that share the number.)

```
python3 dds3tool.py lb-list    04A.LB                       # show entries
python3 dds3tool.py lb-extract 04A.LB out04A                # unpack all entries
python3 dds3tool.py lb-replace 04A.LB 0 new.PB mod/model_lb/devil_b/04A.LB
```

`lb-replace` swaps one or more entries and recompresses the container.

## Patch the ISO directly (use this for PCSX2)

```
python3 dds3tool.py isopatch Game.iso mod Game_mod.iso
```

This copies your ISO and patches the archive inside the copy. Every file on
the disc stays at its original position: replacements that fit are written in
place, larger ones go after the end of the disc, and only the archive index,
the IMG size and the volume size are updated. Always patch from your clean
original ISO, not from an already patched one.

Don't rebuild the disc from extracted files with xorriso/mkisofs: that moves
files around, and the game then fails to boot.

Always test with a copy of your save data.

# Model and animation preview (experimental)

Open **Tools → Model / animation preview…** in the reskinner, double-click
**DDS3 Preview.command** (macOS) / **DDS3 Preview.bat** (Windows), or run:

```
python3 ds2_previewer.py "/path/to/Nocturne" "/path/to/Devil Summoner 2"
```

Each source can be a game dump folder containing `DDS3.DDT` and `DDS3.IMG`,
or a game ISO. With no arguments, the previewer looks for the `Nocturne` and
`Devil Summoner 2` dump folders in Downloads, then offers a folder picker if
neither is present. The Tools menu uses the game sources selected in the
reskinner, or offers a dump folder picker.

The preview opens in your browser. Keep the reskinner (or the command above)
running while using it. It needs a browser with WebGL; no additional Python
packages are needed. Rendering dependencies are included locally.

- Filter by game, demon name, ID, or archive path. Battle and field LB files,
  regular PB models, and menu PB models are listed separately.
- Drag to orbit, scroll to zoom, right-drag or Shift-drag to pan.
- Select an animation slot, press Play, or scrub/step through frames. Slots use
  game-specific action labels. **Labels → Automatic** follows the source archive;
  choose a game explicitly for standalone files. Unlisted slots stay numbered.
- Toggle textures, wireframe, the skeleton, or highlight a bone by ID.
- **Open local PB / LB…** previews an extracted or modified file.

This viewer reads the files and never patches the game archives. The service
listens only on `127.0.0.1`, uses a fresh private URL for each session, and
serves only its viewer assets and selected game models.

This first version supports skeletal animations and the mesh types used by the
Nocturne and DS2 demon libraries. It does not yet reproduce morph animation,
texture animation, special game shading, particles, or hit spheres. Unsupported
animation channels are reported in the viewer. See
[format notes](preview/FORMAT_NOTES.md) for details and validation commands.
