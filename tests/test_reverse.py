"""DS2 -> Nocturne direction: slot-table resizing, the reverse preset and battle packs."""
import struct
import unittest

import dds3tool as tool
import ds2reskin as reskin
from test_animation_presets import model_with_slots

REVERSE = reskin.REVERSE_PRESET


def frames(model):
    return reskin.slot_frames(model)


def reloc_consistent(model):
    mt = tool.pb_chunks(model)["MT00"]
    chunk = bytearray(model[mt:mt + struct.unpack_from("<i", model, mt + 4)[0]])
    before = bytes(chunk)
    tool.rebuild_motion_reloc(chunk)
    return bytes(chunk) == before


class SlotTableTests(unittest.TestCase):
    def test_shrink_drops_tail_and_keeps_other_animations(self):
        ds2 = model_with_slots([100 + i for i in range(17)])
        cut = tool.shrink_motion_slots(ds2, 16)
        self.assertEqual(frames(cut), [100 + i for i in range(16)])
        self.assertTrue(reloc_consistent(cut))
        self.assertEqual(tool.shrink_motion_slots(ds2, 17), ds2)   # nothing to cut

    def test_retarget_to_16_17_and_18_slot_targets(self):
        ds2 = model_with_slots([100 + i if i != 3 else None for i in range(17)])
        for size in (16, 17, 18, 26):
            with self.subTest(size=size):
                base = model_with_slots([60] * size)
                mapping, _ = reskin.preset_map(REVERSE, frames(base), frames(ds2))
                out, _ = tool.retarget_motion_table(ds2, base, mapping)
                got = frames(out)
                self.assertEqual(len(got), size)
                self.assertNotIn(None, got, "every slot the target uses gets an animation")
                self.assertTrue(reloc_consistent(out))

    def test_retarget_reads_original_slots(self):
        ds2 = model_with_slots([100 + i for i in range(17)])
        base = model_with_slots([60] * 16)
        out, _ = tool.retarget_motion_table(ds2, base, {1: 4, 4: 1, 3: 6, 6: None})
        got = frames(out)
        self.assertEqual((got[1], got[4], got[3], got[6]), (104, 101, 106, None))

    def test_chunk_count(self):
        model = model_with_slots([10, 20])
        self.assertEqual(tool.chunk_count(model, "MT00"), 1)
        self.assertEqual(tool.chunk_count(model, "MD00"), 0)


class ReversePresetTests(unittest.TestCase):
    def test_slots_follow_their_meaning(self):
        ds2 = [120, 50, 110, None, 40, 100, 60, 61, 62, 65, None, 38, 59, 50, 45, 66, None]
        mapping, _ = reskin.preset_map(REVERSE, [60] * 16, ds2)
        self.assertEqual(mapping[0], 0)     # idle
        self.assertEqual(mapping[1], 4)     # hit, not DS2's walk
        self.assertEqual(mapping[2], 2)     # injured
        self.assertEqual(mapping[3], 6)     # physical attack
        self.assertEqual(mapping[8], 9)     # second attack: the lunge
        self.assertEqual(mapping[12], 6)    # only two DS2 attacks, so one repeats
        self.assertEqual([mapping[i] for i in (4, 5, 7)], [7, 8, 11])   # three different casts
        self.assertEqual(mapping[15], 15)   # negotiation <- victory pose
        self.assertNotIn(6, mapping)        # unlabeled: keeps DS2's slot 6 (an attack)

    def test_nocturne_empty_slots_stay_empty(self):
        base = [60] * 16
        for i in (5, 6, 9, 10, 12):
            base[i] = None
        mapping, _ = reskin.preset_map(REVERSE, base, [60] * 17)
        for i in (5, 6, 9, 10, 12, 16):
            self.assertIsNone(mapping[i])

    def test_missing_preferences_fall_back_to_closest_length(self):
        ds2 = [120, None, 110, None, 40, None, 60, None, None, None, None, None, None, None, None, None, None]
        base = [60] * 16
        base[4] = 112
        mapping, reasons = reskin.preset_map(REVERSE, base, ds2)
        self.assertEqual(mapping[4], 2)          # no casts at all: 110 frames is nearest to 112
        self.assertIn("closest length", reasons[4])
        self.assertEqual(mapping[9], 6)          # unlabeled and empty in DS2: nearest is 60

    def test_forward_preset_keeps_unruled_slots_empty_source(self):
        mapping, _ = reskin.preset_map(reskin.FORWARD_PRESET, [60] * 17, [60] * 16)
        self.assertNotIn(16, mapping)


def pac(*blobs):
    """A BPAC pack holding BLOBS, the way Nocturne lays them out."""
    entries = [(0 if i == 0 else 1, 1, b) for i, b in enumerate(blobs)]
    template = bytearray(0x20)
    template[8:12] = b"BPAC"
    struct.pack_into("<I", template, 0x14, 1)
    return tool.write_pac(entries, bytes(template))


class BattlePackTests(unittest.TestCase):
    def test_layout_and_round_trip(self):
        data = pac(b"M" * 0x40, b"E" * 0x30, b"F" * 0x20)
        self.assertEqual(data[8:12], b"BPAC")
        count = struct.unpack_from("<I", data, 0x10)[0]
        head = (0x20 + 16 * count + 15) & ~15
        self.assertEqual(struct.unpack_from("<I", data, 4)[0] + head, len(data))
        self.assertEqual(struct.unpack_from("<4I", data, 0x20), (0, 0x40, 1, head))
        self.assertEqual(tool.write_pac(tool.read_pac(data), data), data)

    def test_bigger_model_moves_the_other_entries(self):
        data = pac(b"M" * 0x40, b"E" * 0x30)
        entries = tool.read_pac(data)
        entries[0] = (entries[0][0], entries[0][1], b"N" * 0x100)
        out = tool.read_pac(tool.write_pac(entries, data))
        self.assertEqual([e[2] for e in out], [b"N" * 0x100, b"E" * 0x30])


if __name__ == "__main__":
    unittest.main()
