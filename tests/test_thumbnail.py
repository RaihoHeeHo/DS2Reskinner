"""Demon pictures (software renderer) and the settings file."""
import base64
import os
import struct
import tempfile
import unittest
import zlib
from unittest import mock

import ds2reskin as reskin
import thumbnail


def model(texture_rgba=None, color=None, bone_offset=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0)):
    """A decoded model holding one big triangle on one bone, like decode_model returns."""
    tex = []
    if texture_rgba is not None:
        tex = [{"width": 1, "height": 1, "rgba": base64.b64encode(bytes(texture_rgba)).decode(), "wrap": 0}]
    return {
        "nodes": [{"parent": -1, "position": list(bone_offset), "rotation": list(rotation), "scale": [1, 1, 1]}],
        "meshes": [{"influences": [{"bone": 0, "positions": [[-1, 1, 0, 1], [1, 1, 0, 1], [0, -1, 0, 1]]}],
                    "triangles": [(0, 1, 2)], "uv": [(0, 0), (0, 0), (0, 0)], "material": 0}],
        "materials": [{"texture": 0 if tex else None, "color": color}],
        "textures": tex, "motions": [],
    }


def pixel(rgb, size, x, y):
    i = (y * size + x) * 3
    return tuple(rgb[i:i + 3])


class RenderTests(unittest.TestCase):
    BG = (10, 20, 30)

    def test_texture_colour_reaches_the_picture(self):
        rgb = thumbnail.render(model([200, 40, 40, 255]), 40, self.BG, supersample=1)
        r, g, b = pixel(rgb, 40, 20, 20)
        self.assertGreater(r, 2 * g)          # red texture, lit
        self.assertEqual(pixel(rgb, 40, 0, 0), self.BG)

    def test_transparent_texels_are_skipped(self):
        rgb = thumbnail.render(model([200, 40, 40, 10]), 40, self.BG, supersample=1)
        self.assertEqual(set(pixel(rgb, 40, x, y) for x in range(40) for y in range(40)), {self.BG})

    def test_material_tint(self):
        rgb = thumbnail.render(model([255, 255, 255, 255], color=[0, 255, 0, 128]), 40, self.BG, supersample=1)
        r, g, b = pixel(rgb, 40, 20, 20)
        self.assertEqual((r, b), (0, 0))
        self.assertGreater(g, 100)

    def test_game_down_is_picture_down(self):
        # Game negative Y is up: the triangle's single vertex at y=-1 is its top.
        rgb = thumbnail.render(model([255, 255, 255, 255]), 40, self.BG, supersample=1)
        top = [x for x in range(40) if pixel(rgb, 40, x, 6) != self.BG]
        bottom = [x for x in range(40) if pixel(rgb, 40, x, 33) != self.BG]
        self.assertLess(len(top), len(bottom))

    def test_bone_matrices_follow_the_hierarchy(self):
        m = model()
        m["nodes"].append({"parent": 0, "position": [0, 2, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1]})
        m["nodes"][0]["position"] = [5, 0, 0]
        m["nodes"][0]["rotation"] = [0, 0, 1.5707963267948966]   # 90 degrees about Z
        world = thumbnail.bone_matrices(m)
        self.assertAlmostEqual(world[1][3], 3.0)    # child's (0,2,0) rotated to (-2,0,0), plus (5,0,0)
        self.assertAlmostEqual(world[1][7], 0.0, places=6)

    def test_empty_model_gives_background(self):
        m = model()
        m["meshes"] = []
        self.assertEqual(set(thumbnail.render(m, 8, self.BG)), set(self.BG))

    def test_png_encoding(self):
        data = thumbnail.png(bytes([1, 2, 3]) * 4, 2)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", data[16:24]), (2, 2))
        raw = zlib.decompress(data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8])
        self.assertEqual(raw, (b"\0" + bytes([1, 2, 3]) * 2) * 2)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(reskin, "settings_dir", return_value=os.path.join(self.dir.name, "app"))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.dir.cleanup()

    def test_missing_file_is_empty(self):
        self.assertEqual(reskin.load_settings(), {})

    def test_save_merges(self):
        self.assertTrue(reskin.save_settings(ds2_iso="/games/ds2.iso"))
        self.assertTrue(reskin.save_settings(noc_iso="/games/noc.iso"))
        self.assertEqual(reskin.load_settings(), {"ds2_iso": "/games/ds2.iso", "noc_iso": "/games/noc.iso"})

    def test_corrupt_file_is_ignored(self):
        os.makedirs(reskin.settings_dir())
        with open(reskin.settings_path(), "w") as f:
            f.write("{not json")
        self.assertEqual(reskin.load_settings(), {})
        self.assertTrue(reskin.save_settings(ds2_iso="x"))
        self.assertEqual(reskin.load_settings(), {"ds2_iso": "x"})


if __name__ == "__main__":
    unittest.main()
