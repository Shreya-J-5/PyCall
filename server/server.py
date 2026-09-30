import logging
import queue
import select
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


class CallServer:
    def __init__(self, port=PORT, audio_port=AUDIO_PORT, input_device=None, output_device=None):
        self.port = port
        self.audio_port = audio_port
        self.input_device = input_device
        self.output_device = output_device
        self.events = queue.Queue()
        self._stopping = threading.Event()
        self._decision_ready = threading.Event()
        self._local_end = threading.Event()
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._connection = None
        self._client_host = None
        self._udp_peer = None
        self._udp_socket = None
        self._listener = None
        self._audio = None
        self._active = False
        self._decision = None
        self._external_busy = False
        self._thread = None

    def set_busy(self, is_busy):
        with self._lock:
            self._external_busy = bool(is_busy)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="pycall-server", daemon=True)
        self._thread.start()

    def _emit(self, name, **data):
        self.events.put((name, data))

    def _run(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        audio_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("0.0.0.0", self.port))
            listener.listen(4)
            audio_socket.bind(("0.0.0.0", self.audio_port))
            listener.setblocking(False)
            audio_socket.setblocking(False)
            self._listener = listener
            self._udp_socket = audio_socket
            self._emit("server_status", text=f"Waiting for calls on port {self.port}...")
            logging.info("Server listening: TCP %s, UDP audio %s", self.port, self.audio_port)
            while not self._stopping.is_set():
                readable, _, _ = select.select([listener, audio_socket], [], [], 0.25)
                for ready_socket in readable:
                    if ready_socket is listener:
                        self._accept_connection(listener)
                    else:
                        self._handle_audio_packet(audio_socket)
        except OSError as error:
            if not self._stopping.is_set():
                logging.exception("Receiver server could not start or continue")
                self._emit("server_error", text=f"Could not listen on port {self.port}. Check the port and firewall.")
        finally:
            self._close_socket(listener)
            self._close_socket(audio_socket)
            self._listener = None
            self._udp_socket = None
            if self._stopping.is_set():
                self._emit("server_status", text="Receiver stopped.")

    def _accept_connection(self, listener):
        try:
            connection, address = listener.accept()
        except OSError:
            return
        with self._lock:
            occupied = self._connection is not None or self._external_busy
            if not occupied:
                self._connection = connection
                self._client_host = address[0]
                self._udp_peer = None
                self._local_end.clear()
        if occupied:
            try:
                connection.sendall(encode_control("BUSY"))
            except OSError:
                pass
            self._close_socket(connection)
            return
        connection.settimeout(1.0)
        threading.Thread(
            target=self._session_loop,
            args=(connection, address[0]),
            name="pycall-session",
            daemon=True,
        ).start()

    def _session_loop(self, connection, client_host):
        buffer = bytearray()
        last_received = time.monotonic()
        last_ping = last_received
        in_call = False
        try:
            self._emit("connection_status", text=f"Connected: {client_host}")
            while not self._stopping.is_set():
                if self._local_end.is_set():
                    break
                try:
                    message_type = receive_control(connection, buffer)
                except socket.timeout:
                    message_type = None
                if message_type is None:
                    now = time.monotonic()
                    if now - last_ping >= 10:
                        self._send(connection, "PING")
                        last_ping = now
                    if now - last_received > 35:
                        raise ConnectionError("Control connection timed out")
                    continue
                last_received = time.monotonic()
                if message_type == "PING":
                    self._send(connection, "PONG")
                    continue
                if message_type == "PONG":
                    continue
                if not in_call and message_type == "CALL":
                    self._decision = None
                    self._decision_ready.clear()
                    self._emit("incoming_call", caller=client_host)
                    if not self._wait_for_decision(connection, buffer):
                        if self._decision != "cancel":
                            self._send(connection, "REJECT")
                        break
                    if self._decision == "reject":
                        self._send(connection, "REJECT")
                        self._emit("call_ended", text="Call rejected.")
                        break
                    self._audio = AudioEngine(self.input_device, self.output_device)
                    try:
                        self._audio.start()
                    except AudioDeviceError as error:
                        self._send(connection, "ERROR")
                        self._emit("server_error", text=str(error))
                        break
                    with self._lock:
                        self._active = True
                    self._send(connection, "ACCEPT")
                    in_call = True
                    self._emit("call_started", text="Connected")
                    threading.Thread(target=self._send_audio_loop, daemon=True).start()
                    continue
                if in_call and message_type == "END":
                    self._send(connection, "END")
                    self._emit("call_ended", text="Call ended by the caller.")
                    break
                if in_call and message_type in ("MUTE", "UNMUTE"):
                    self._emit("remote_mute", muted=message_type == "MUTE")
                    continue
                raise ProtocolError("Unexpected control message for current call state")
        except (OSError, ConnectionError, ProtocolError) as error:
            if not self._stopping.is_set() and not self._local_end.is_set():
                logging.info("Caller connection ended: %s", error)
                self._emit("call_ended" if in_call else "connection_status", text="Connection lost.")
        finally:
            self._stop_audio()
            with self._lock:
                if self._connection is connection:
                    self._connection = None
                    self._client_host = None
                    self._udp_peer = None
                    self._active = False
            self._close_socket(connection)
            if not self._stopping.is_set():
                self._emit("connection_status", text=f"Waiting for calls on port {self.port}...")

    def _wait_for_decision(self, connection, buffer):
        deadline = time.monotonic() + 60
        last_received = time.monotonic()
        last_ping = last_received
        while not self._decision_ready.is_set() and not self._stopping.is_set():
            if time.monotonic() >= deadline:
                return False
            try:
                message_type = receive_control(connection, buffer)
            except socket.timeout:
                message_type = None
            if message_type is None:
                now = time.monotonic()
                if now - last_ping >= 10:
                    self._send(connection, "PING")
                    last_ping = now
                if now - last_received > 35:
                    raise ConnectionError("Control connection timed out while ringing")
                continue
            last_received = time.monotonic()
            if message_type == "PING":
                self._send(connection, "PONG")
            elif message_type == "CANCEL":
                self._decision = "cancel"
                self._emit("call_cancelled", text="Caller cancelled the call.")
                return False
            elif message_type != "PONG":
                raise ProtocolError("Unexpected control message while ringing")
        return self._decision_ready.is_set()

    def _handle_audio_packet(self, audio_socket):
        try:
            packet, address = audio_socket.recvfrom(4096)
        except OSError:
            return
        with self._lock:
            client_host = self._client_host
            active = self._active
            peer = self._udp_peer
            audio = self._audio
        if not active or address[0] != client_host:
            return
        if packet == AUDIO_REGISTER_MAGIC:
            with self._lock:
                self._udp_peer = address
            return
        expected_length = AUDIO_PACKET_HEADER.size + AUDIO_PACKET_BYTES
        if address != peer or len(packet) != expected_length:
            return
        try:
            magic, _sequence = AUDIO_PACKET_HEADER.unpack_from(packet)
        except Exception:
            return
        if magic == AUDIO_PACKET_MAGIC and audio is not None:
            audio.play(packet[AUDIO_PACKET_HEADER.size:])

    def _send_audio_loop(self):
        sequence = 0
        while not self._stopping.is_set():
            with self._lock:
                active = self._active
                audio = self._audio
                peer = self._udp_peer
                audio_socket = self._udp_socket
            if not active or audio is None or audio_socket is None:
                return
            try:
                pcm = audio.get_captured(timeout=0.2)
            except queue.Empty:
                continue
            if peer is None:
                continue
            packet = AUDIO_PACKET_HEADER.pack(AUDIO_PACKET_MAGIC, sequence) + pcm
            try:
                audio_socket.sendto(packet, peer)
            except OSError as error:
                logging.info("Audio send failed: %s", error)
            sequence = (sequence + 1) & 0xFFFFFFFF

    def accept_call(self):
        self._decision = "accept"
        self._decision_ready.set()

    def reject_call(self):
        self._decision = "reject"
        self._decision_ready.set()

    def set_devices(self, input_device=None, output_device=None):
        self.input_device = input_device
        self.output_device = output_device

    def toggle_mute(self):
        audio = self._audio
        if not self._active or audio is None:
            return None
        muted = not audio.muted
        audio.set_muted(muted)
        connection = self._connection
        if connection is not None:
            self._send(connection, "MUTE" if muted else "UNMUTE")
        self._emit("mute_changed", muted=muted)
        return muted

    def end_call(self):
        with self._lock:
            connection = self._connection
        if connection is not None:
            self._local_end.set()
            self._send(connection, "END")
            self._stop_audio()
            with self._lock:
                self._active = False
            self._emit("call_ended", text="Call ended.")

    def _send(self, connection, message_type):
        try:
            with self._send_lock:
                connection.sendall(encode_control(message_type))
        except OSError:
            logging.info("Could not send %s control message", message_type)

    def _stop_audio(self):
        audio = self._audio
        self._audio = None
        if audio is not None:
            audio.stop()

    @staticmethod
    def _close_socket(sock):
        try:
            sock.close()
        except OSError:
            pass

    def stop(self):
        self._stopping.set()
        self._stop_audio()
        for sock in (self._connection, self._listener, self._udp_socket):
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self._close_socket(sock)


if __name__ == "__main__":
    from ui.interface import run_receiver

    run_receiver()