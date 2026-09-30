# 📞 PyCall

> **Private, peer-to-peer voice calling over your local Wi-Fi network!** 🎙️✨  
> No servers, no sign-ups, no internet required. Just pure local audio magic. 🚀

---

## 🌟 What is PyCall?

Ever wanted to talk to someone in the other room or across the office without relying on WhatsApp, Discord, or an active internet connection? **PyCall** makes that happen! 🎉

PyCall is a lightweight, zero-cloud desktop voice calling app built with Python and Tkinter. It connects computers directly over your local Wi-Fi or LAN. Both computers run the exact same app, listen for incoming calls automatically, and let you dial each other using just a local IP address. 💻⚡💻

---

## ✨ Features That Make It Cool

- 🔄 **Unified App:** No separate "caller" or "receiver" scripts! Both computers run the exact same app and can both make and take calls.
- ⚡ **Real-Time Voice Streaming:** Crisp low-latency voice streaming using raw UDP audio packets with NumPy and SoundDevice.
- 🎯 **Reliable TCP Signaling:** Call setup, ringing, accept, reject, busy status, mute notifications, and hang-ups are all handled smoothly over TCP.
- 🎨 **Sleek Modern UI:** Clean, modern Tkinter interface with real-time call duration timers, device selection, and live status updates.
- 🎙️ **Audio Device Chooser:** Pick your favorite microphone and speakers right from the dropdown and test them before jumping on a call.
- 🤫 **Mute / Unmute Support:** Toggle your microphone on the fly with live sync to the other caller.
- 🧪 **Single-Laptop Testing Mode:** Test everything on a single machine using two different ports side by side!
- 🛡️ **100% Private:** Audio never leaves your local Wi-Fi. No data tracking, no third-party cloud servers, no account creation.

---

## 🏗️ How It Works (Behind the Scenes)

PyCall splits its duties smartly between two protocols:

```
Laptop A                                         Laptop B
 (Caller)                                       (Receiver)
    │                                               │
    │──────── TCP Port 5000: "CALL" ───────────────>│ (Rings!)
    │<─────── TCP Port 5000: "ACCEPT" ──────────────│ (Accepted)
    │                                               │
    │<═══════ UDP Port 5001: Live Audio Stream ════>│ (Talking!)
    │                                               │
    │──────── TCP Port 5000: "END" ────────────────>│ (Hang up)
```

1. **TCP (Port 5000):** Used for handshake control messages (CALL, ACCEPT, REJECT, BUSY, MUTE, END, PING/PONG).
2. **UDP (Port 5001):** Used for high-speed, low-latency audio transmission directly between microphones and speakers.

---

## 🚀 Quick Start Guide

### 1. Requirements 📋

- Python 3.10 or newer installed on your machine(s).
- A working microphone and speaker / headphones. 🎧
- Both devices connected to the **SAME Wi-Fi network**. 📶

---

### 2. Installation 📦

Clone the repository and set up your virtual environment:

```bash
git clone https://github.com/Shreya-J-5/PyCall.git
cd PyCall
```

Create and activate your virtual environment:

**On Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**On Windows (Command Prompt):**
```cmd
python -m venv .venv
.\.venv\Scripts\activate.bat
pip install -r requirements.txt
```

---

## 🎮 How to Use PyCall

### Scenario A: Testing on a Single Laptop (Dual Port Mode) 🧪

Want to try it out right now on just one machine? Easy!

**Option 1: The 1-Click Launcher (Windows)**
- Simply double-click `run_dual_test.bat`.
- Two windows will pop up side by side automatically!
  - **Window 1:** Running on Port 5000
  - **Window 2:** Running on Port 5002

**Option 2: Terminal Commands**
- Open Terminal 1:
  ```powershell
  python main.py --port 5000
  ```
- Open Terminal 2:
  ```powershell
  python main.py --port 5002
  ```

In Window 1, enter `127.0.0.1` and Port `5002`, then hit **CALL**! Click **ACCEPT** on Window 2 and you are in a live call! 🥳

---

### Scenario B: Calling Between Two Physical Laptops on Wi-Fi 💻🤝💻

1. **Connect both laptops to the same Wi-Fi.** Make sure it is a private home or office network (not a restricted guest network with client isolation).
2. **Launch PyCall on both laptops:**
   - Double-click `run.bat` or run:
     ```powershell
     python main.py
     ```
3. **Find your IP address:**
   - Look at the top of the app window under **Your Address**. It shows your current local IP (for example: `192.168.1.25`).
4. **Make the call:**
   - On Laptop A, type Laptop B's IP address into the **Remote IP** box.
   - Click the green **CALL** button. 📞
5. **Accept & Chat:**
   - Laptop B will show an incoming call screen. Click **ACCEPT**! 🎉
   - Talk freely with low latency!
   - Use **MUTE** whenever you need to cough or take a pause, and click **END CALL** when you are done. 👋

---

## 🛠️ Project Structure

```text
PyCall/
│
├── audio/            # Audio recording, playback, and device management
│   └── audio.py      # SoundDevice and NumPy stream engine
│
├── client/           # Outgoing call handler
│   └── client.py     # TCP signaling client and UDP audio sender
│
├── server/           # Incoming call listener
│   └── server.py     # TCP signaling server and UDP audio receiver
│
├── network/          # Communication protocol
│   └── protocol.py   # Packet encoding, framing, and validation
│
├── config/           # Application configuration
│   └── config.py     # Ports, audio buffer sizes, sample rates
│
├── ui/               # Modern graphical interface
│   └── interface.py  # Tkinter UI with state management
│
├── tests/            # Automated test suite
│   └── test_protocol.py # Protocol and framing unit tests
│
├── main.py           # Unified entry point
├── run.bat           # 1-click single launcher
├── run_dual_test.bat # 1-click dual test launcher
├── requirements.txt  # Python package dependencies
└── README.md         # You are here! 📖
```

---

## 🔧 Windows Firewall Tips

When you run PyCall for the first time, Windows Defender Firewall might pop up asking for permissions:

- ✅ Check the box for **Private networks** (home or work).
- ✅ Click **Allow access**.

If two laptops cannot connect to each other, you can quickly allow the ports via PowerShell (Run as Administrator):

```powershell
New-NetFirewallRule -DisplayName "PyCall TCP" -Direction Inbound -LocalPort 5000,5002 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "PyCall UDP" -Direction Inbound -LocalPort 5001,5003 -Protocol UDP -Action Allow
```

---

## 🧪 Running Unit Tests

PyCall includes a test suite to ensure network protocol serialization and message framing work reliably:

```powershell
python -m unittest discover tests
```

---

## 💡 Tech Stack

- **Language:** Python 3.10+ 🐍
- **Audio Capture & Playback:** `sounddevice` 🔊
- **Signal Processing:** `numpy` 🧮
- **GUI:** `tkinter` 🖼️
- **Networking:** Native Python `socket` & `threading` 🌐

---

## 💖 Made with Passion

Built for seamless, private, and simple voice communication without bloated apps or internet dependencies. Enjoy calling! 🚀🎉
