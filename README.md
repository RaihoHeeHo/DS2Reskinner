# DS2 Reskinner (GUI)

Double-click **DS2 Reskinner.command** (or run `python3 ds2_reskinner.py`).

1. Choose your Devil Summoner 2 ISO (North American, SLUS_218.45) and your
   Nocturne ISO. Neither file is changed.
2. Pick a mode:
   - **Auto swap**: every tested swap (29 reskins and 5 new demons).
   - **Manual swap**: tick the tested swaps you want.
   - **Custom swap**: put any Nocturne demon on any DS2 demon. The program
     compares both models' animation slots, warns about one-animation models,
     missing hit bones, walking demons and story locks, and fills in the
     animation fixes that worked for the tested swaps. You can edit them.
3. Choose where to save the modded ISO and press **Build ISO**.

Needs Python 3 with tkinter (python.org Python has it; Homebrew Python needs
`brew install python-tk@3.X`, matching your `python3 --version`). Start the game from an in-game save, not a PCSX2
save state.

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

## Add a new demon in an unused reserve slot

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
