import struct
import unittest

from model_preview import FormatError, Reader, chunks, decode_motions, decode_materials, decode_textures, unpack_lb


def chunk(kind,magic,payload=b''):
    return struct.pack('<II4sI',kind,16+len(payload),magic,0)+payload


class DecoderTests(unittest.TestCase):
    def test_truncation_is_rejected(self):
        with self.assertRaises(FormatError):Reader(b'\x00').read('I')
        with self.assertRaises(FormatError):Reader(b'',1)

    def test_chunk_may_not_cross_file_end(self):
        data=struct.pack('<II4sI',6,1024,b'MD00',0)
        with self.assertRaises(FormatError):chunks(data)

    def test_repeated_effect_chunks_are_valid(self):
        data=chunk(6,b'MD00').ljust(64,b'\0')
        data+=chunk(2,b'D3P\0').ljust(64,b'\0')
        data+=chunk(2,b'D3P\0')
        self.assertIn('MD00',chunks(data))

    def test_multiple_motion_packs_are_retained(self):
        data=chunk(6,b'MD00').ljust(64,b'\0')
        data+=chunk(8,b'MT00').ljust(64,b'\0')+chunk(8,b'MT00')
        self.assertEqual(len(chunks(data)['motion_sections']),2)

    def test_negative_key_times_and_empty_slot(self):
        # MT00 base at 32; two slots, one controller. Motion starts at base+24.
        data=bytearray(32)
        data+=struct.pack('<HHI',2,1,16)+struct.pack('<4H',0,0,0,0)
        data+=struct.pack('<II',24,0)
        data+=struct.pack('<I',10)
        data+=struct.pack('<IHHhh6f',36,2,12,-10,0,1,2,3,4,5,6)
        warnings=set(); motions=decode_motions(data,(0,len(data)),warnings)
        self.assertEqual(motions[0]['tracks'][0]['times'],[-10,0])
        self.assertEqual(motions[0]['tracks'][0]['values'][1],[4,5,6])
        self.assertIsNone(motions[1]);self.assertFalse(warnings)

    def test_truncated_track_values_are_rejected(self):
        data=bytearray(32)+struct.pack('<HHI',1,1,16)+struct.pack('<4H',3,0,0,0)
        data+=struct.pack('<I',20)+struct.pack('<I',10)+struct.pack('<IHH',8,1,8)
        with self.assertRaises(FormatError):decode_motions(data,(0,len(data)),set())

    def test_lb_model_payload_and_invalid_bounds(self):
        payload=b'example model'
        data=bytes([0,0,0,0])+struct.pack('<I4sI',16+len(payload),b'PBN\0',len(payload))+payload
        self.assertEqual(unpack_lb(data),payload)
        with self.assertRaises(FormatError):unpack_lb(data[:-1])

    def test_material_index_is_not_a_flags_word(self):
        # Nonzero material indices precede the property mask.
        data=bytes(16)+struct.pack('<IIIi',1,17,1<<18,3)
        self.assertEqual(decode_materials(data,0,len(data),16),[{'texture':3,'color':None}])

    def test_tmx_low_nibble_first_and_ps2_alpha(self):
        texture=bytearray(64)
        struct.pack_into('<II4sI',texture,0,3,64+64+1,b'TMX0',0)
        struct.pack_into('<BBHHBB',texture,16,1,0,2,1,20,0)
        palette=b''.join(bytes((i,0,0,128)) for i in range(16))
        texture+=palette+bytes([0x21])
        data=bytearray(64)+texture
        struct.pack_into('<II4sI',data,0,2,len(data),b'TXP0',0)
        struct.pack_into('<II',data,16,1,64)
        result=decode_textures(data,(0,len(data)),set())
        import base64
        self.assertEqual(base64.b64decode(result[0]['rgba']),bytes([1,0,0,255,2,0,0,255]))

    def test_vif_packet_then_command_remains_aligned(self):
        data=struct.pack('<HBB3fHBB',0,1,0x68,1,2,3,0,0,0x14)
        r=Reader(data)
        self.assertEqual(r.packet(),[[1,2,3]])
        r.kick();self.assertEqual(r.pos,len(data))


if __name__=='__main__':unittest.main()
