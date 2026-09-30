"""PyCall — LAN voice calling between two laptops or two local instances.

Run on BOTH laptops:

    python main.py

Or test on the SAME laptop with two different ports:

    python main.py --port 5000
    python main.py --port 5002
"""

import argparse
import sys
import tkinter as tk
from tkinter import messagebox

from config.config import AUDIO_PORT, PORT
from ui.interface import PyCallApp


def main():
    parser = argparse.ArgumentParser(description="PyCall — LAN Voice Calling")
    parser.add_argument("--port", "-p", type=int, default=PORT, help=f"TCP signaling port (default: {PORT})")
    parser.add_argument("--audio-port", "-a", type=int, default=None, help="UDP audio port (default: port + 1)")
    args = parser.parse_args()

    audio_port = args.audio_port if args.audio_port is not None else (args.port + 1)

    root = tk.Tk()
    try:
        app = PyCallApp(root, port=args.port, audio_port=audio_port)
    except Exception as error:
        root.withdraw()
        messagebox.showerror("PyCall", f"Failed to start on port {args.port}: {error}")
        sys.exit(1)
    root.mainloop()


if __name__ == "__main__":
    main()
