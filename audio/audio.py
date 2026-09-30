import logging
import queue
import threading

import numpy as np
import sounddevice as sd

from config.config import AUDIO_CHANNELS, AUDIO_CHUNK_SIZE, AUDIO_SAMPLE_RATE


class AudioDeviceError(Exception):
    pass


def get_audio_devices():
    microphones = [("Default microphone", None)]
    speakers = [("Default speaker", None)]
    try:
        for index, device in enumerate(sd.query_devices()):
            if device["max_input_channels"] > 0:
                microphones.append((f"{device['name']} (device {index})", index))
            if device["max_output_channels"] > 0:
                speakers.append((f"{device['name']} (device {index})", index))
    except Exception:
        logging.exception("Could not enumerate audio devices")
    return microphones, speakers


def test_microphone(device=None):
    try:
        recording = sd.rec(
            int(AUDIO_SAMPLE_RATE * 0.5),
            samplerate=AUDIO_SAMPLE_RATE,
            channels=AUDIO_CHANNELS,
            dtype="int16",
            device=device,
            blocking=True,
        )
        return bool(np.any(recording))
    except Exception as error:
        logging.exception("Microphone test failed")
        raise AudioDeviceError("Microphone unavailable.") from error


def test_speaker(device=None):
    try:
        sample_count = int(AUDIO_SAMPLE_RATE * 0.35)
        time = np.arange(sample_count, dtype=np.float32) / AUDIO_SAMPLE_RATE
        tone = (np.sin(2 * np.pi * 440 * time) * 0.15).astype(np.float32)
        sd.play(tone, samplerate=AUDIO_SAMPLE_RATE, device=device, blocking=True)
    except Exception as error:
        logging.exception("Speaker test failed")
        raise AudioDeviceError("Speaker unavailable.") from error


class AudioEngine:
    def __init__(self, input_device=None, output_device=None):
        self.input_device = input_device
        self.output_device = output_device
        self.captured = queue.Queue(maxsize=25)
        self.playback = queue.Queue(maxsize=25)
        self._muted = threading.Event()
        self._input_stream = None
        self._output_stream = None

    @property
    def muted(self):
        return self._muted.is_set()

    def set_muted(self, muted):
        if muted:
            self._muted.set()
        else:
            self._muted.clear()

    def start(self):
        try:
            self._output_stream = sd.OutputStream(
                samplerate=AUDIO_SAMPLE_RATE,
                channels=AUDIO_CHANNELS,
                dtype="int16",
                blocksize=AUDIO_CHUNK_SIZE,
                device=self.output_device,
                callback=self._playback_callback,
            )
            self._output_stream.start()
        except Exception as error:
            self.stop()
            logging.exception("Could not start speaker output")
            raise AudioDeviceError("Speaker unavailable.") from error
        try:
            self._input_stream = sd.InputStream(
                samplerate=AUDIO_SAMPLE_RATE,
                channels=AUDIO_CHANNELS,
                dtype="int16",
                blocksize=AUDIO_CHUNK_SIZE,
                device=self.input_device,
                callback=self._capture_callback,
            )
            self._input_stream.start()
        except Exception as error:
            self.stop()
            logging.exception("Could not start microphone input")
            raise AudioDeviceError("Microphone unavailable.") from error

    def _capture_callback(self, indata, frames, timing, status):
        if status:
            logging.warning("Audio capture status: %s", status)
        if self.muted:
            return
        pcm = indata[:, 0].tobytes()
        try:
            self.captured.put_nowait(pcm)
        except queue.Full:
            try:
                self.captured.get_nowait()
                self.captured.put_nowait(pcm)
            except queue.Empty:
                pass

    def _playback_callback(self, outdata, frames, timing, status):
        if status:
            logging.warning("Audio playback status: %s", status)
        try:
            pcm = self.playback.get_nowait()
            outdata[:, 0] = np.frombuffer(pcm, dtype=np.int16)
        except queue.Empty:
            outdata.fill(0)

    def get_captured(self, timeout=0.2):
        return self.captured.get(timeout=timeout)

    def play(self, pcm):
        if len(pcm) != AUDIO_CHUNK_SIZE * 2:
            return
        try:
            self.playback.put_nowait(pcm)
        except queue.Full:
            try:
                self.playback.get_nowait()
                self.playback.put_nowait(pcm)
            except queue.Empty:
                pass

    def stop(self):
        for stream in (self._input_stream, self._output_stream):
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    logging.debug("Audio stream was not running during cleanup", exc_info=True)
                try:
                    stream.close()
                except Exception:
                    logging.exception("Error closing audio stream")
        self._input_stream = None
        self._output_stream = None