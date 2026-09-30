import enum
import logging
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from audio.audio import AudioDeviceError, get_audio_devices, test_microphone, test_speaker
from client.client import PyCallClient
from config.config import AUDIO_PORT, PORT
from server.server import CallServer


class CallState(enum.Enum):
    IDLE = "idle"
    CALLING = "calling"
    RINGING = "ringing"
    CONNECTED = "connected"
    ENDING = "ending"
    DISCONNECTED = "disconnected"


def get_local_ipv4():
    """Detect the laptop's local IPv4 address on the current network."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        probe.close()


class PyCallApp:
    """Unified PyCall application — both caller and receiver in one window.

    Runs a CallServer in the background so incoming calls can be received
    at any time.  When the user presses CALL, a PyCallClient connects outward.
    """

    def __init__(self, root, port=PORT, audio_port=None):
        self.root = root
        self.port = port
        self.audio_port = audio_port if audio_port is not None else (self.port + 1)
        self.root.title(f"PyCall (Port {self.port})")
        # Offset window position slightly if non-default port so dual instances don't completely overlap
        x_offset = 80 if self.port == PORT else 620
        self.root.geometry(f"500x700+{x_offset}+50")
        self.root.minsize(460, 620)
        self.root.configure(background="#f4f6f8")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._state = CallState.IDLE
        self._call_direction = None  # "outgoing" or "incoming"

        # Audio devices
        self.microphones, self.speakers = get_audio_devices()
        self.microphone_ids = {label: device_id for label, device_id in self.microphones}
        self.speaker_ids = {label: device_id for label, device_id in self.speakers}

        # Networking
        self.client = PyCallClient()
        self.server = CallServer(port=self.port, audio_port=self.audio_port)
        self.local_ip = get_local_ipv4()

        # Call timing
        self.call_started_at = None
        self.muted = False

        # Build the full UI
        self._apply_style()
        self._build_ui()

        # Start the server listener
        self.server.start()

        # Begin polling events
        self.root.after(100, self._poll_events)

    # ──────────────────────────────────────────────
    # Style
    # ──────────────────────────────────────────────

    def _apply_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f4f6f8")
        style.configure("TLabel", background="#f4f6f8", foreground="#18212b", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"), foreground="#172f3b")
        style.configure("Subtitle.TLabel", font=("Segoe UI", 9), foreground="#6b8a99")
        style.configure("Section.TLabel", font=("Segoe UI", 12, "bold"), foreground="#172f3b")
        style.configure("Status.TLabel", foreground="#43606d", font=("Segoe UI", 10))
        style.configure("IP.TLabel", font=("Consolas", 13, "bold"), foreground="#087e78")
        style.configure("Duration.TLabel", font=("Segoe UI", 20), foreground="#172f3b", background="#f4f6f8")
        style.configure("Connected.TLabel", font=("Segoe UI", 13, "bold"), foreground="#0b9e3a")
        style.configure("TButton", font=("Segoe UI", 10), padding=(14, 8))
        style.configure("Call.TButton", font=("Segoe UI", 11, "bold"), padding=(18, 10))
        style.configure("TEntry", padding=8, font=("Segoe UI", 11))
        style.configure("TCombobox", padding=6)

    # ──────────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────────

    def _build_ui(self):
        self.outer = ttk.Frame(self.root, padding=(32, 24, 32, 20))
        self.outer.pack(fill="both", expand=True)

        # ── Header ──
        header = ttk.Frame(self.outer)
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(header, text="PyCall", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="PRIVATE LAN VOICE", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))

        # ── Your IP & Port ──
        ip_frame = ttk.Frame(self.outer)
        ip_frame.pack(fill="x", pady=(10, 6))
        ttk.Label(ip_frame, text="Your Address:").pack(anchor="w")
        ttk.Label(ip_frame, text=f"{self.local_ip}  (Port {self.port})", style="IP.TLabel").pack(anchor="w", pady=(2, 0))

        # ── Status bar ──
        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(self.outer, textvariable=self.status_var, style="Status.TLabel", wraplength=420)
        self.status_label.pack(fill="x", pady=(10, 8))

        # ── IDLE panel (call form + device selection) ──
        self.idle_panel = ttk.Frame(self.outer)
        self._build_idle_panel(self.idle_panel)
        self.idle_panel.pack(fill="x", pady=(4, 0))

        # ── CALLING panel ──
        self.calling_panel = ttk.Frame(self.outer, padding=(0, 12))
        self._build_calling_panel(self.calling_panel)

        # ── RINGING panel (incoming call) ──
        self.ringing_panel = ttk.Frame(self.outer, padding=(0, 12))
        self._build_ringing_panel(self.ringing_panel)

        # ── CONNECTED panel ──
        self.connected_panel = ttk.Frame(self.outer, padding=(0, 12))
        self._build_connected_panel(self.connected_panel)

        # ── Footer ──
        footer = ttk.Label(
            self.outer,
            text="Calls are unencrypted. LAN only — not for use over the Internet.",
            style="Subtitle.TLabel",
            wraplength=420,
        )
        footer.pack(side="bottom", anchor="w", pady=(20, 0))

    def _build_idle_panel(self, parent):
        # Device selection
        device_frame = ttk.LabelFrame(parent, text="Audio Devices", padding=(12, 8))
        device_frame.pack(fill="x", pady=(0, 14))
        ttk.Label(device_frame, text="Microphone").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.microphone_var = tk.StringVar(value=self.microphones[0][0])
        self.microphone_combo = ttk.Combobox(
            device_frame,
            textvariable=self.microphone_var,
            values=[item[0] for item in self.microphones],
            state="readonly",
        )
        self.microphone_combo.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(device_frame, text="Speaker").grid(row=2, column=0, sticky="w", pady=(0, 4))
        self.speaker_var = tk.StringVar(value=self.speakers[0][0])
        self.speaker_combo = ttk.Combobox(
            device_frame,
            textvariable=self.speaker_var,
            values=[item[0] for item in self.speakers],
            state="readonly",
        )
        self.speaker_combo.grid(row=3, column=0, sticky="ew")
        device_frame.columnconfigure(0, weight=1)
        ttk.Button(device_frame, text="Test devices", command=self._test_devices).grid(
            row=4, column=0, sticky="w", pady=(10, 0)
        )

        # Call form
        call_frame = ttk.LabelFrame(parent, text="Call another PyCall device", padding=(12, 8))
        call_frame.pack(fill="x", pady=(0, 0))

        target_grid = ttk.Frame(call_frame)
        target_grid.pack(fill="x", pady=(0, 8))

        # Remote IP
        ttk.Label(target_grid, text="Remote IP").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.ip_var = tk.StringVar(value="127.0.0.1" if self.port != PORT else "")
        self.ip_entry = ttk.Entry(target_grid, textvariable=self.ip_var, font=("Consolas", 11))
        self.ip_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.ip_entry.bind("<Return>", lambda _: self._initiate_call())

        # Remote Port
        ttk.Label(target_grid, text="Port").grid(row=0, column=1, sticky="w", pady=(0, 4))
        default_target_port = 5002 if self.port == PORT else PORT
        self.target_port_var = tk.StringVar(value=str(default_target_port))
        self.target_port_entry = ttk.Entry(target_grid, textvariable=self.target_port_var, width=8, font=("Consolas", 11))
        self.target_port_entry.grid(row=1, column=1, sticky="w")
        self.target_port_entry.bind("<Return>", lambda _: self._initiate_call())

        target_grid.columnconfigure(0, weight=3)
        target_grid.columnconfigure(1, weight=1)

        self.call_button = ttk.Button(
            call_frame, text="CALL", style="Call.TButton", command=self._initiate_call
        )
        self.call_button.pack(fill="x", pady=(4, 4))

    def _build_calling_panel(self, parent):
        self.calling_ip_var = tk.StringVar(value="Calling...")
        ttk.Label(parent, textvariable=self.calling_ip_var, style="Section.TLabel").pack(anchor="w", pady=(0, 16))
        ttk.Button(parent, text="CANCEL", command=self._cancel_call).pack(anchor="w")

    def _build_ringing_panel(self, parent):
        ttk.Label(parent, text="Incoming Call", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        self.caller_ip_var = tk.StringVar(value="From: —")
        ttk.Label(parent, textvariable=self.caller_ip_var, style="IP.TLabel").pack(anchor="w", pady=(0, 18))
        btn_row = ttk.Frame(parent)
        btn_row.pack(anchor="w")
        ttk.Button(btn_row, text="ACCEPT", style="Call.TButton", command=self._accept_call).pack(side="left")
        ttk.Button(btn_row, text="REJECT", command=self._reject_call).pack(side="left", padx=(12, 0))

    def _build_connected_panel(self, parent):
        ttk.Label(parent, text="● Connected", style="Connected.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(parent, text="Call Duration:").pack(anchor="w")
        self.duration_var = tk.StringVar(value="00:00")
        ttk.Label(parent, textvariable=self.duration_var, style="Duration.TLabel").pack(anchor="w", pady=(2, 16))
        btn_row = ttk.Frame(parent)
        btn_row.pack(anchor="w")
        self.mute_button = ttk.Button(btn_row, text="MUTE", command=self._toggle_mute)
        self.mute_button.pack(side="left")
        ttk.Button(btn_row, text="END CALL", command=self._end_call).pack(side="left", padx=(12, 0))

    # ──────────────────────────────────────────────
    # Panel switching (state machine)
    # ──────────────────────────────────────────────

    def _set_state(self, new_state, status_text=None):
        self._state = new_state

        # Hide all panels
        self.idle_panel.pack_forget()
        self.calling_panel.pack_forget()
        self.ringing_panel.pack_forget()
        self.connected_panel.pack_forget()

        # Show the panel for the new state
        if new_state == CallState.IDLE:
            self.idle_panel.pack(fill="x", pady=(4, 0))
            self._call_direction = None
            self.call_started_at = None
            self.muted = False
            self.mute_button.configure(text="MUTE")
            self.server.set_busy(False)
            if status_text:
                self.status_var.set(status_text)
            else:
                self.status_var.set("Ready")
        elif new_state == CallState.CALLING:
            self.calling_panel.pack(fill="x", pady=(4, 0))
            self.server.set_busy(True)
            if status_text:
                self.status_var.set(status_text)
        elif new_state == CallState.RINGING:
            self.ringing_panel.pack(fill="x", pady=(4, 0))
            if status_text:
                self.status_var.set(status_text)
        elif new_state == CallState.CONNECTED:
            self.connected_panel.pack(fill="x", pady=(4, 0))
            self.call_started_at = time.monotonic()
            self.muted = False
            self.mute_button.configure(text="MUTE")
            if status_text:
                self.status_var.set(status_text)
            else:
                self.status_var.set("Connected")
        elif new_state in (CallState.ENDING, CallState.DISCONNECTED):
            if status_text:
                self.status_var.set(status_text)
            # Transition to IDLE after a brief moment
            self.root.after(1200, lambda: self._set_state(CallState.IDLE))

    # ──────────────────────────────────────────────
    # User actions
    # ──────────────────────────────────────────────

    def _selected_devices(self):
        return (
            self.microphone_ids.get(self.microphone_var.get()),
            self.speaker_ids.get(self.speaker_var.get()),
        )

    def _test_devices(self):
        mic, spk = self._selected_devices()
        self.status_var.set("Testing microphone and speaker...")

        def _run():
            try:
                heard_input = test_microphone(mic)
                test_speaker(spk)
                text = "Device test complete." if heard_input else "Speaker OK. No microphone input detected."
            except AudioDeviceError as error:
                text = str(error)
            self.root.after(0, lambda: self.status_var.set(text))

        threading.Thread(target=_run, daemon=True).start()

    def _initiate_call(self):
        if self._state != CallState.IDLE:
            return
        raw_ip = self.ip_var.get().strip()
        raw_port = self.target_port_var.get().strip()

        # Handle IP:Port format if typed into IP field
        if ":" in raw_ip:
            parts = raw_ip.split(":", 1)
            raw_ip = parts[0].strip()
            raw_port = parts[1].strip()

        if not raw_ip:
            self.status_var.set("Please enter an IP address first.")
            messagebox.showwarning(
                "Enter IP Address",
                "Please enter an IP address before clicking CALL.\n\n"
                "- On the same laptop: enter 127.0.0.1\n"
                "- Between two laptops: enter the other laptop's IP (e.g. 192.168.1.25)"
            )
            return

        try:
            target_port = int(raw_port)
            if not 1 <= target_port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Invalid Port",
                f"'{raw_port}' is not a valid port number (1-65535)."
            )
            return

        import ipaddress
        try:
            ipaddress.IPv4Address(raw_ip)
        except ValueError:
            messagebox.showerror(
                "Invalid IP Address",
                f"'{raw_ip}' is not a valid IPv4 address.\n\nUse 127.0.0.1 for local testing, or a LAN IP like 192.168.1.25"
            )
            return

        # Check self-collision on same port
        if raw_ip in (self.local_ip, "127.0.0.1", "localhost") and target_port == self.port:
            other_port = 5002 if self.port == PORT else PORT
            messagebox.showinfo(
                "Port Conflict",
                f"You cannot call your own port ({self.port})!\n\n"
                f"To call the other instance on this laptop, set Port to {other_port}."
            )
            return

        target_audio_port = target_port + 1
        mic, spk = self._selected_devices()
        self._call_direction = "outgoing"
        self.calling_ip_var.set(f"Calling {raw_ip}:{target_port}...")
        self._set_state(CallState.CALLING, f"Calling {raw_ip}:{target_port}...")
        self.client = PyCallClient()
        self.client.start_call(raw_ip, target_port, target_audio_port, mic, spk)

    def _cancel_call(self):
        if self._state == CallState.CALLING:
            self.client.cancel_call()
            self._set_state(CallState.IDLE, "Call cancelled.")

    def _accept_call(self):
        if self._state != CallState.RINGING:
            return
        mic, spk = self._selected_devices()
        self.server.set_devices(mic, spk)
        self.server.accept_call()
        self.status_var.set("Starting audio...")

    def _reject_call(self):
        if self._state != CallState.RINGING:
            return
        self.server.reject_call()
        self._set_state(CallState.IDLE, "Call rejected.")

    def _toggle_mute(self):
        if self._state != CallState.CONNECTED:
            return
        if self._call_direction == "outgoing":
            muted = self.client.toggle_mute()
        else:
            muted = self.server.toggle_mute()
        if muted is not None:
            self.muted = muted
            self.mute_button.configure(text="UNMUTE" if muted else "MUTE")

    def _end_call(self):
        if self._state != CallState.CONNECTED:
            return
        self._set_state(CallState.ENDING, "Ending call...")
        if self._call_direction == "outgoing":
            self.client.end_call()
        else:
            self.server.end_call()

    # ──────────────────────────────────────────────
    # Event polling (non-blocking bridge from threads)
    # ──────────────────────────────────────────────

    def _poll_events(self):
        # Poll client events
        self._drain_queue(self.client.events, "client")
        # Poll server events
        self._drain_queue(self.server.events, "server")
        # Update call timer
        if self.call_started_at is not None and self._state == CallState.CONNECTED:
            elapsed = int(time.monotonic() - self.call_started_at)
            self.duration_var.set(f"{elapsed // 60:02d}:{elapsed % 60:02d}")
        self.root.after(100, self._poll_events)

    def _drain_queue(self, q, source):
        while True:
            try:
                name, data = q.get_nowait()
            except queue.Empty:
                break
            self._handle_event(name, data, source)

    def _handle_event(self, name, data, source):
        logging.info("Event [%s] %s: %s", source, name, data)

        # ── Server events ──
        if name == "incoming_call":
            if self._state == CallState.IDLE:
                self._call_direction = "incoming"
                caller_ip = data.get("caller", "unknown")
                self.caller_ip_var.set(f"From: {caller_ip}")
                self._set_state(CallState.RINGING, "Incoming call")
            return

        if name == "call_started" and source == "server":
            if self._state == CallState.RINGING:
                self._set_state(CallState.CONNECTED, "Connected")
            return

        if name == "call_ended" and source == "server":
            if self._state in (CallState.RINGING, CallState.CONNECTED, CallState.ENDING):
                text = data.get("text", "Call ended.")
                self._set_state(CallState.DISCONNECTED, text)
            return

        if name == "call_cancelled" and source == "server":
            if self._state == CallState.RINGING:
                text = data.get("text", "Caller cancelled.")
                self._set_state(CallState.IDLE, text)
            return

        if name == "server_status":
            if self._state == CallState.IDLE:
                # Don't overwrite useful idle status with server chatter
                pass
            return

        if name == "server_error":
            text = data.get("text", "Server error.")
            self.status_var.set(text)
            logging.error("Server error: %s", text)
            return

        if name == "connection_status":
            # Server connection status updates
            return

        # ── Client events ──
        if name == "call_started" and source == "client":
            if self._state == CallState.CALLING:
                self._set_state(CallState.CONNECTED, "Connected")
            return

        if name == "call_ended" and source == "client":
            if self._state in (CallState.CALLING, CallState.CONNECTED, CallState.ENDING):
                text = data.get("text", "Call ended.")
                self._set_state(CallState.DISCONNECTED, text)
            return

        if name == "rejected":
            if self._state == CallState.CALLING:
                self._set_state(CallState.IDLE, data.get("text", "Call rejected."))
            return

        if name == "call_cancelled" and source == "client":
            if self._state == CallState.CALLING:
                self._set_state(CallState.IDLE, data.get("text", "Call cancelled."))
            return

        if name == "error":
            text = data.get("text", "Error.")
            if self._state in (CallState.CALLING, CallState.CONNECTED):
                self._set_state(CallState.IDLE, text)
            else:
                self.status_var.set(text)
            return

        if name == "status":
            self.status_var.set(data.get("text", ""))
            return

        if name == "mute_changed":
            self.muted = data.get("muted", False)
            self.mute_button.configure(text="UNMUTE" if self.muted else "MUTE")
            return

        if name == "remote_mute":
            if data.get("muted"):
                self.status_var.set("Other participant muted their mic.")
            else:
                self.status_var.set("Connected")
            return

    # ──────────────────────────────────────────────
    # Cleanup
    # ──────────────────────────────────────────────

    def _on_close(self):
        try:
            if self._call_direction == "outgoing":
                self.client.end_call()
            elif self._call_direction == "incoming":
                self.server.end_call()
            self.server.stop()
        except Exception:
            logging.exception("Error during shutdown")
        self.root.destroy()


# ── Legacy entry points (kept for backward compatibility) ──

def run_caller():
    """Legacy: run as caller only. Use main.py instead."""
    root = tk.Tk()
    PyCallApp(root)
    root.mainloop()


def run_receiver():
    """Legacy: run as receiver only. Use main.py instead."""
    root = tk.Tk()
    PyCallApp(root)
    root.mainloop()