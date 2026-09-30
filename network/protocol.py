import json

from config.config import CONTROL_MESSAGE_TYPES, MAX_CONTROL_MESSAGE_BYTES


class ProtocolError(Exception):
    pass


def encode_control(message_type):
    if message_type not in CONTROL_MESSAGE_TYPES:
        raise ProtocolError("Unsupported control message")
    payload = json.dumps({"type": message_type}, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(payload) > MAX_CONTROL_MESSAGE_BYTES:
        raise ProtocolError("Control message is too large")
    return payload


def receive_control(sock, buffer):
    newline = buffer.find(b"\n")
    if newline < 0:
        try:
            chunk = sock.recv(512)
        except TimeoutError:
            return None
        if not chunk:
            raise ConnectionError("Peer disconnected")
        buffer.extend(chunk)
        if len(buffer) > MAX_CONTROL_MESSAGE_BYTES and b"\n" not in buffer:
            raise ProtocolError("Control message is too large")
        newline = buffer.find(b"\n")
        if newline < 0:
            return None

    if newline + 1 > MAX_CONTROL_MESSAGE_BYTES:
        raise ProtocolError("Control message is too large")
    line = bytes(buffer[:newline])
    del buffer[:newline + 1]
    try:
        message = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError("Invalid control message") from error
    if not isinstance(message, dict) or set(message) != {"type"}:
        raise ProtocolError("Invalid control message fields")
    if not isinstance(message["type"], str) or message["type"] not in CONTROL_MESSAGE_TYPES:
        raise ProtocolError("Unknown control message type")
    return message["type"]