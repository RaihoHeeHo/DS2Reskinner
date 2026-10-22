"""Preset preference resolution and real motion-table rewrite regressions."""
import struct
import unittest

import dds3tool as tool
import ds2reskin as reskin

PRESET = 'Nocturne → Devil Summoner 2'


def model_with_slots(frames):
    """Minimal MT00 with independently identifiable animation payloads."""
    chunk = bytearray(32)
    chunk += struct.pack('<HHI', len(frames), 0, 8)
    table = len(chunk)
    chunk += bytes(4 * len(frames))
    chunk += bytes(-len(chunk) % 16)
    for slot, length in enumerate(frames):
        if length is None:
            continue
        struct.pack_into('<I', chunk, table + slot * 4, len(chunk) - 32)
        chunk += struct.pack('<I', length) + bytes([slot]) * 12
    struct.pack_into('<II4sI', chunk, 0, 8, len(chunk), b'MT00', 0)
    struct.pack_into('<II', chunk, 16, len(chunk) - 32, 0)
    tool.rebuild_motion_reloc(chunk)
    chunk += bytes(-len(chunk) % 64)
    return bytes(chunk) + struct.pack('<II4sI', 255, 16, b'END0', 0)


class PresetTests(unittest.TestCase):
    def test_full_preference_map_and_distinct_concentration(self):
        mapping, _ = reskin.preset_map(PRESET, [60]*17, [60]*16)
        self.assertEqual(mapping, {0:0, 1:2, 2:2, 3:3, 4:1, 5:1, 6:3,
                                   7:4, 8:4, 9:3, 10:9, 11:5, 13:0, 14:0, 15:3})
        self.assertNotIn(12, mapping)
        self.assertNotIn(16, mapping)

    def test_target_empties_override_populated_source(self):
        target = [60]*17
        for i in (1, 7, 8, 10, 12, 16):
            target[i] = None
        mapping, _ = reskin.preset_map(PRESET, target, [60]*17)
        for i in (1, 7, 8, 10, 12, 16):
            self.assertIsNone(mapping[i])

    def test_source_empty_same_index_does_not_block_fallback(self):
        source = [None]*16
        source[8], source[11], source[12] = 30, 40, 50
        mapping, _ = reskin.preset_map(PRESET, [60]*17, source)
        self.assertEqual(mapping[6], 8)
        self.assertEqual(mapping[9], 8)
        self.assertEqual(mapping[7], 11)
        self.assertEqual(mapping[13], 12)
        self.assertEqual(mapping[14], 12)
        self.assertEqual(mapping[15], 8)
        self.assertIsNone(mapping[0])

    def test_concentration_reuses_cast_only_when_no_alternative(self):
        source = [None]*16
        source[7] = 60
        mapping, _ = reskin.preset_map(PRESET, [60]*17, source)
        self.assertEqual([mapping[i] for i in (7, 8, 11)], [7, 7, 7])

    def test_keep_empty_map_text_roundtrip(self):
        self.assertEqual(reskin.m('0=0,4=1,10=-'), {0:0, 4:1, 10:None})

    def test_rewrite_uses_original_sources_even_after_overwriting_them(self):
        original = model_with_slots([100+i for i in range(16)])
        target = [60]*17
        target[3], target[10], target[16] = None, None, None
        base = model_with_slots(target)
        mapping, _ = reskin.preset_map(PRESET, target, reskin.slot_frames(original))
        for share in (False, True):
            with self.subTest(share=share):
                rewritten, changes = tool.fill_motion_slots(original, base, mapping, share=share)
                result = reskin.slot_frames(rewritten)
                for dst, src in mapping.items():
                    self.assertEqual(result[dst], None if src is None else 100+src)
                self.assertEqual(result[6], 103)  # Slot 3 was cleared, but its source survives.
                self.assertEqual(result[4], 101)  # Slot 1 was remapped to 2, not used recursively.
                self.assertEqual(reskin.slot_frames(original), list(range(100,116)))
                self.assertEqual(dict(changes), mapping)


if __name__ == '__main__':
    unittest.main()
