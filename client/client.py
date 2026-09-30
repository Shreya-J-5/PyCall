import ipaddress
import logging
import queue
import socket
import threading
import time

from audio.audio import AudioDeviceError, AudioEngine
from config.config import (
    AUDIO_PACKET_BYTES,
    AUDIO_PACKET_HEADER,
    AUDIO_PACKET_MAGIC,
    AUDIO_PORT,
    AUDIO_REGISTER_MAGIC,
    PORT,
)
from network.protocol import ProtocolError, encode_control, receive_control


class PyCallClient:
    def __init__(self):
        self.events = queue.Queue()
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._finish_lock = threading.Lock()
        self._connection = None
        self._udp_socket = None
        self._audio = None
        self._active = False
        self._finished = True
        self._host = None
        self._port = PORT
        self._audio_port = AUDIO_PORT
        self._thread = None

    def start_call(self, host, port=PORT, audio_port=AUDIO_PORT, input_device=None, output_device=None):
        try:
            host = str(ipaddress.IPv4Address(host.strip()))
            port = int(port)
            if not 1 <= port <= 65535:
                raise ValueError
        except (ValueError, AttributeError):
            self.events.put(("error", {"text": "Invalid IP address or port."}))
            return
        if self._thread and self._thread.is_alive():
            self.events.put(("error", {"text": "A call is already in progress."}))
            return
        self._finished = False
        self._host = host
        self._port = port
        self._audio_port = audio_port
        self._thread = threading.Thread(
            target=self._call_loop,
            args=(host, port, audio_port, input_device, output_device),
            name="pycall-client",
            daemon=True,
        )
        self._thread.start()

    def _call_loop(self, host, port, audio_port, input_device, output_device):
        self.events.put(("status", {"text": "Connecting..."}))
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._connection = connection
        try:
            connection.settimeout(8)
            connection.connect((host, port))
            connection.settimeout(1.0)
            self._send("CALL")
            buffer = bytearray()
            last_received = time.monotonic()
            last_ping = last_received
            while not self._finished:
                try:
                    message_type = receive_control(connection, buffer)
                except socket.timeout:
                    message_type = None
                if message_type is None:
                    now = time.monotonic()
                    if now - last_ping >= 10:
                        self._send("PING")
                        last_ping = now
                    if now - last_received > 35:
                        raise ConnectionError("Receiver did not respond")
                    continue
                last_received = time.monotonic()
                if message_type == "PING":
                    self._send("PONG")
                    continue
                if message_type == "PONG":
                    continue
                if message_type == "REJECT":
                    self._finish("Call rejected.", send_end=False, event_name="rejected")
                    return
                if message_type == "BUSY":
                    self._finish("Receiver is already handling a call.", event_name="error")
                    return
                if message_type == "ERROR":
                    self._finish("Receiver could not start audio.", event_name="error")
                    return
                if message_type != "ACCEPT":
                    raise ProtocolError("Unexpected control message")
                break

            if self._finished:
                return
            self._udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp_socket.settimeout(0.5)
            self._udp_socket.sendto(AUDIO_REGISTER_MAGIC, (host, audio_port))
            self._audio = AudioEngine(input_device, output_device)
            try:
                self._audio.start()
            except AudioDeviceError as error:
                self._send("END")
                self._finish(str(error), event_name="error")
                return
            self._active = True
            self.events.put(("call_started", {"text": "Connected"}))
            threading.Thread(target=self._send_audio_loop, daemon=True).start()
            threading.Thread(target=self._receive_audio_loop, daemon=True).start()
            self._control_loop(connection, buffer)
        except (OSError, ConnectionError, ProtocolError) as error:
            logging.info("Caller connection failed: %s", error)
            if not self._finished:
                message = "Unable to connect to device." if not self._active else "Connection lost."
                self._finish(message, event_name="error" if not self._active else "call_ended")

    def _control_loop(self, connection, buffer):
        last_received = time.monotonic()
        last_ping = last_received
        while self._active:
            try:
                message_type = receive_control(connection, buffer)
            except socket.timeout:
                message_type = None
            if message_type is None:
                now = time.monotonic()
                if now - last_ping >= 10:
                    self._send("PING")
                    last_ping = now
                if now - last_received > 35:
                    self._finish("Connection lost.", event_name="call_ended")
                    return
                continue
            last_received = time.monotonic()
            if message_type == "PING":
                self._send("PONG")
            elif message_type == "END":
                self._finish("Call ended by the receiver.", event_name="call_ended")
                return
            elif message_type == "ERROR":
                self._finish("Connection lost.", event_name="call_ended")
                return
            elif message_type in ("MUTE", "UNMUTE"):
                self.events.put(("remote_mute", {"muted": message_type == "MUTE"}))
            elif message_type == "PONG":
                continue
            else:
                raise ProtocolError("Unexpected control message during call")

    def _send_audio_loop(self):
        sequence = 0
        while self._active:
            audio = self._audio
            udp_socket = self._udp_socket
            if audio is None or udp_socket is None:
                return
            try:
                pcm = audio.get_captured(timeout=0.2)
            except queue.Empty:
                continue
            packet = AUDIO_PACKET_HEADER.pack(AUDIO_PACKET_MAGIC, sequence) + pcm
            try:
                udp_socket.sendto(packet, (self._host, self._audio_port))
            except OSError as error:
                logging.info("Audio send failed: %s", error)
                self._finish("Connection lost.", event_name="call_ended")
                return
            sequence = (sequence + 1) & 0xFFFFFFFF

    def _receive_audio_loop(self):
        expected_length = AUDIO_PACKET_HEADER.size + AUDIO_PACKET_BYTES
        while self._active:
            udp_socket = self._udp_socket
            if udp_socket is None:
                return
            try:
                packet, address = udp_socket.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            if address != (self._host, self._port) or len(packet) != expected_length:
                continue
            try:
                magic, _sequence = AUDIO_PACKET_HEADER.unpack_from(packet)
            except Exception:
                continue
            audio = self._audio
            if magic == AUDIO_PACKET_MAGIC and audio is not None:
                audio.play(packet[AUDIO_PACKET_HEADER.size:])

    def _send(self, message_type):
        connection = self._connection
        if connection is None:
            return
        try:
            with self._send_lock:
                connection.sendall(encode_control(message_type))
        except OSError:
            logging.info("Could not send %s control message", message_type)

    def cancel_call(self):
        with self._finish_lock:
            if self._finished:
                return
        self._send("CANCEL")
        self._finish("Call cancelled.", send_end=False, event_name="call_cancelled")

    def toggle_mute(self):
        audio = self._audio
        if not self._active or audio is None:
            return None
        muted = not audio.muted
        audio.set_muted(muted)
        self._send("MUTE" if muted else "UNMUTE")
        self.events.put(("mute_changed", {"muted": muted}))
        return muted

    def end_call(self):
        self._finish("Call ended.", send_end=True, event_name="call_ended")

    def _finish(self, text, send_end=False, event_name="call_ended"):
        with self._finish_lock:
            if self._finished:
                return
            self._finished = True
        if send_end:
            self._send("END")
        self._active = False
        audio, self._audio = self._audio, None
        if audio is not None:
            audio.stop()
        udp_socket, self._udp_socket = self._udp_socket, None
        if udp_socket is not None:
            udp_socket.close()
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        self.events.put((event_name, {"text": text}))


if __name__ == "__main__":
    from ui.interface import run_caller

    run_caller()