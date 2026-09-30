import socket
import unittest

from network.protocol import ProtocolError, encode_control, receive_control


class ControlProtocolTests(unittest.TestCase):
    def setUp(self):
        self.reader, self.writer = socket.socketpair()
        self.buffer = bytearray()

    def tearDown(self):
        self.reader.close()
        self.writer.close()

    def test_round_trip(self):
        self.writer.sendall(encode_control("CALL"))
        self.assertEqual(receive_control(self.reader, self.buffer), "CALL")

    def test_required_call_messages_round_trip(self):
        for message_type in ("CALL", "ACCEPT", "REJECT", "CANCEL", "END", "MUTE", "UNMUTE"):
            with self.subTest(message_type=message_type):
                self.writer.sendall(encode_control(message_type))
                self.assertEqual(receive_control(self.reader, self.buffer), message_type)

    def test_fragmented_message(self):
        self.writer.sendall(b'{"ty')
        self.assertIsNone(receive_control(self.reader, self.buffer))
        self.writer.sendall(b'pe":"ACCEPT"}\n')
        self.assertEqual(receive_control(self.reader, self.buffer), "ACCEPT")

    def test_rejects_unknown_type(self):
        self.writer.sendall(b'{"type":"EXEC"}\n')
        with self.assertRaises(ProtocolError):
            receive_control(self.reader, self.buffer)

    def test_rejects_unexpected_fields(self):
        self.writer.sendall(b'{"type":"CALL","command":"bad"}\n')
        with self.assertRaises(ProtocolError):
            receive_control(self.reader, self.buffer)

    def test_rejects_non_string_type(self):
        self.writer.sendall(b'{"type":[]}\n')
        with self.assertRaises(ProtocolError):
            receive_control(self.reader, self.buffer)


if __name__ == "__main__":
    unittest.main()