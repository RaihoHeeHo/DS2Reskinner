# DDS3 preview decoder

This is an independent Python decoder for previewing the supplied game dumps.
Binary field layouts were cross-checked against the public DDS3 Model Studio
format template and actual PB/LB data. No Model Studio source code is bundled.

Format references:
- https://github.com/tge-was-taken/DDS3-Model-Studio/blob/master/Documents/DDS3_Model.bt
- https://github.com/tge-was-taken/DDS3-Model-Studio/tree/master/Source/DDS3ModelLibrary

The renderer is Three.js 0.160.0, bundled locally under its MIT license in
`vendor/THREE-LICENSE.txt`. Running the previewer does not contact a CDN.

## Supported

- DDS3 archive folders and ISOs through the existing archive reader.
- Standalone PB and compressed/uncompressed model entries in LB files.
- Bone hierarchy with local position, Euler rotation and scale.
- Rigid VIF meshes (1/8), weighted VIF meshes (2/7), UVs, materials, and TMX
  textures: indexed 4/8 bit, RGB24, RGBA32, RGB5A1.
- Multiple motion packs; each pack retains its own slot numbers.
- Signed key timings, position/scale vector keys, packed quaternion rotations,
  linear position/scale interpolation and quaternion slerp.
- Skinning uses each influence's own bone-local position, rather than assuming
  all influences share a single bind position. Game negative Y is displayed up.

## Current limits

This is an inspection renderer, not an emulation of the PS2 graphics pipeline.
It recomputes mesh normals and uses neutral lighting. It does not reproduce
vertex colors, exact game material effects, texture animation, overlays,
particle effects, morph animation, or hit spheres. Unhandled animation channel
formats appear in the viewer's warning panel; supported skeletal channels still
play. Other mesh types and multiple model/texture chunks are rejected explicitly.
The FPS control is a preview setting (30 by default), not a claim that every
animation in every game uses the same playback clock.

## Validation

`python3 -m unittest discover -s tests` runs dependency-free parser regression
checks. `python3 tests/check_game_models.py GAME_FOLDER [GAME_FOLDER ...]`
checks the actual demon PB files in supplied archives without extracting them.
Game data is not included in the repository.

On the supplied dumps, 488 Nocturne and 259 DS2 demon-folder PB files passed
parsing and per-vertex skin-weight checks. Ten synthetic regression tests cover
section bounds, LB payloads, material records, texture palette decoding, signed
animation timing and multiple motion packs. Browser checks verified textured
Jack Frost models from both games, playback, scrubbing and the skeleton overlay.
The full corpus check validates data structure, not the visual accuracy of every
animation or special effect.
