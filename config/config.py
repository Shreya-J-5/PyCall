import logging
import os
import struct


PORT = int(os.environ.get("PYCALL_PORT", "5000"))
AUDIO_PORT = int(os.environ.get("PYCALL_AUDIO_PORT", str(PORT + 1)))
AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_CHUNK_SIZE = 1024
AUDIO_SAMPLE_WIDTH = 2
AUDIO_PACKET_HEADER = struct.Struct("!4sI")
AUDIO_PACKET_MAGIC = b"PCA1"
AUDIO_REGISTER_MAGIC = b"PYC1"
AUDIO_PACKET_BYTES = AUDIO_CHUNK_SIZE * AUDIO_SAMPLE_WIDTH
MAX_CONTROL_MESSAGE_BYTES = 1024
CONTROL_MESSAGE_TYPES = {
    "CALL", "ACCEPT", "REJECT", "CANCEL", "END", "MUTE", "UNMUTE",
    "PING", "PONG", "ERROR", "BUSY",
}


logging.basicConfig(
    filename="pycall.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)