from __future__ import annotations

import queue
import struct
import threading
import time
from dataclasses import dataclass

import serial

from .audio_resampler import PCM16StreamingResampler
from .sia_protocol import (
    Packet,
    PacketDecoder,
    PacketType,
    Route,
    encode_packet,
)

_DEVICE_HELLO = struct.Struct("<III")
_AUDIO_FORMAT = struct.Struct("<IHH")
_STATS = struct.Struct("<15I")


@dataclass(slots=True, frozen=True)
class SIADeviceHello:
    firmware_semver: int
    sample_rate: int
    features: int

    @property
    def firmware_version(self) -> str:
        major = (self.firmware_semver >> 16) & 0xFF
        minor = (self.firmware_semver >> 8) & 0xFF
        patch = self.firmware_semver & 0xFF
        return f"{major}.{minor}.{patch}"


@dataclass(slots=True, frozen=True)
class SIAStats:
    uptime_ms: int
    free_heap: int
    free_psram: int
    usb_rx_overflow: int
    usb_tx_drop: int
    protocol_crc_error: int
    protocol_length_error: int
    playback_underflow: int
    playback_overflow: int
    reference_drop: int
    mic_i2s_error: int
    spk_i2s_error: int
    afe_feed_frames: int
    afe_fetch_frames: int
    mic_packets_sent: int


class SIAESP32:
    """
    Persistent single-owner USB bridge for the ESP32-S3.

    Do not open COM9 from any other SIA module while this object is alive.
    """

    def __init__(
        self,
        port: str = "COM9",
        baud: int = 921600,
        read_size: int = 8192,
    ):
        self.port = str(port)
        self.baud = int(baud)
        self.read_size = int(read_size)

        self._ser: serial.Serial | None = None
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None

        self._decoder = PacketDecoder()
        self._tx_sequence = 1
        self._tx_lock = threading.Lock()

        self._responses: dict[PacketType, queue.Queue[Packet]] = {
            t: queue.Queue()
            for t in PacketType
            if t not in (PacketType.MIC_PCM, PacketType.VAD_EVENT)
        }

        # Bounded queues stop a stalled consumer from exhausting PC RAM.
        self.mic_packets: queue.Queue[Packet] = queue.Queue(maxsize=256)
        self.vad_events: queue.Queue[Packet] = queue.Queue(maxsize=64)

        self.reader_exception: BaseException | None = None

    @property
    def connected(self) -> bool:
        return bool(self._ser and self._ser.is_open)

    def connect(self, handshake: bool = True) -> SIADeviceHello | None:
        if self.connected:
            return self.host_hello() if handshake else None

        self._ser = serial.Serial(
            port=self.port,
            baudrate=self.baud,
            timeout=0.05,
            write_timeout=3.0,
        )

        try:
            self._ser.dtr = False
            self._ser.rts = False
        except Exception:
            pass

        self._stop.clear()
        self.reader_exception = None

        self._reader = threading.Thread(
            target=self._reader_loop,
            name="SIA-USB-RX",
            daemon=True,
        )
        self._reader.start()

        # Give native CDC a short settle period, then negotiate protocol.
        time.sleep(0.20)

        return self.host_hello() if handshake else None

    def close(self):
        self._stop.set()

        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=2.0)

        self._reader = None

        if self._ser is not None:
            try:
                self._ser.close()
            finally:
                self._ser = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _check_reader(self):
        if self.reader_exception is not None:
            raise RuntimeError(
                "SIA USB reader stopped unexpectedly."
            ) from self.reader_exception

    def _reader_loop(self):
        assert self._ser is not None

        try:
            while not self._stop.is_set():
                data = self._ser.read(self.read_size)
                if not data:
                    continue

                for packet in self._decoder.feed(data):
                    self._dispatch(packet)

        except BaseException as exc:
            if not self._stop.is_set():
                self.reader_exception = exc
                self._stop.set()

    @staticmethod
    def _put_latest(q: queue.Queue, packet: Packet):
        try:
            q.put_nowait(packet)
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(packet)
            except queue.Full:
                pass

    def _dispatch(self, packet: Packet):
        if packet.type == PacketType.MIC_PCM:
            self._put_latest(self.mic_packets, packet)
            return

        if packet.type == PacketType.VAD_EVENT:
            self._put_latest(self.vad_events, packet)
            return

        q = self._responses.get(packet.type)
        if q is not None:
            q.put(packet)

    def _clear_response(self, packet_type: PacketType):
        q = self._responses[packet_type]
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                return

    def _send(
        self,
        packet_type: PacketType,
        payload: bytes = b"",
        flags: int = 0,
    ):
        self._check_reader()

        if not self.connected:
            raise RuntimeError("SIA ESP32 is not connected.")

        assert self._ser is not None

        with self._tx_lock:
            seq = self._tx_sequence
            self._tx_sequence = (self._tx_sequence + 1) & 0xFFFFFFFF

            packet = encode_packet(
                packet_type=packet_type,
                sequence=seq,
                timestamp_ms=int(time.monotonic() * 1000),
                payload=payload,
                flags=flags,
            )

            self._ser.write(packet)
            self._ser.flush()

    def _wait(
        self,
        packet_type: PacketType,
        timeout: float,
    ) -> Packet:
        self._check_reader()

        q = self._responses[packet_type]

        try:
            packet = q.get(timeout=timeout)
        except queue.Empty as exc:
            self._check_reader()
            raise TimeoutError(
                f"Timed out waiting for {packet_type.name}."
            ) from exc

        if packet.type == PacketType.ERROR:
            raise RuntimeError(
                packet.payload.rstrip(b"\0").decode(
                    "utf-8",
                    errors="replace",
                )
            )

        return packet

    def _send_wait(
        self,
        request: PacketType,
        response: PacketType,
        payload: bytes = b"",
        timeout: float = 3.0,
    ) -> Packet:
        # Stale response must never satisfy a new command.
        self._clear_response(response)
        self._clear_response(PacketType.ERROR)

        self._send(request, payload)

        deadline = time.monotonic() + timeout

        while True:
            self._check_reader()

            try:
                error = self._responses[PacketType.ERROR].get_nowait()
            except queue.Empty:
                error = None

            if error is not None:
                raise RuntimeError(
                    error.payload.rstrip(b"\0").decode(
                        "utf-8",
                        errors="replace",
                    )
                )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"{request.name} -> {response.name} timed out."
                )

            try:
                return self._responses[response].get(
                    timeout=min(0.05, remaining)
                )
            except queue.Empty:
                pass

    # --------------------------------------------------------
    # CONTROL
    # --------------------------------------------------------

    def host_hello(self) -> SIADeviceHello:
        packet = self._send_wait(
            PacketType.HOST_HELLO,
            PacketType.DEVICE_HELLO,
            timeout=4.0,
        )

        if len(packet.payload) != _DEVICE_HELLO.size:
            raise RuntimeError("Invalid DeviceHello payload.")

        fw, sample_rate, features = _DEVICE_HELLO.unpack(packet.payload)

        return SIADeviceHello(
            firmware_semver=fw,
            sample_rate=sample_rate,
            features=features,
        )

    def ping(self, timeout: float = 2.0) -> float:
        start = time.perf_counter()

        self._send_wait(
            PacketType.PING,
            PacketType.PONG,
            timeout=timeout,
        )

        return (time.perf_counter() - start) * 1000.0

    def set_route(self, route: Route) -> Route:
        packet = self._send_wait(
            PacketType.SET_ROUTE,
            PacketType.ROUTE_ACK,
            payload=struct.pack("<B", int(route)),
            timeout=4.0,
        )

        if len(packet.payload) != 1:
            raise RuntimeError("Invalid RouteAck payload.")

        return Route(packet.payload[0])

    def get_stats(self) -> SIAStats:
        packet = self._send_wait(
            PacketType.GET_STATS,
            PacketType.STATS,
            timeout=3.0,
        )

        if len(packet.payload) != _STATS.size:
            raise RuntimeError(
                f"Invalid Stats payload size={len(packet.payload)}."
            )

        return SIAStats(*_STATS.unpack(packet.payload))

    # --------------------------------------------------------
    # MICROPHONE
    # --------------------------------------------------------

    def clear_mic_queue(self):
        while True:
            try:
                self.mic_packets.get_nowait()
            except queue.Empty:
                break

        while True:
            try:
                self.vad_events.get_nowait()
            except queue.Empty:
                break

    def mic_start(self):
        self.clear_mic_queue()
        self._send(PacketType.MIC_START)

    def mic_stop(self):
        self._send(PacketType.MIC_STOP)

    # --------------------------------------------------------
    # TTS
    # --------------------------------------------------------

    def tts_start(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        bits_per_sample: int = 16,
    ):
        payload = _AUDIO_FORMAT.pack(
            int(sample_rate),
            int(channels),
            int(bits_per_sample),
        )

        self._send_wait(
            PacketType.TTS_START,
            PacketType.TTS_READY,
            payload=payload,
            timeout=5.0,
        )

    def tts_pcm(self, pcm16_le: bytes):
        if not pcm16_le:
            return

        if len(pcm16_le) & 1:
            raise ValueError("PCM16 byte count must be even.")

        # Firmware protocol maximum payload is 16 KiB. Keep each audio packet
        # comfortably below that boundary.
        frame = 8192

        for offset in range(0, len(pcm16_le), frame):
            self._send(
                PacketType.TTS_PCM,
                pcm16_le[offset:offset + frame],
            )

    def tts_end(self):
        self._send_wait(
            PacketType.TTS_END,
            PacketType.TTS_DONE,
            timeout=8.0,
        )


class SIAHardwareAudioPlayer:
    """
    Drop-in playback object for CosyVoicePersistentClient.

    API intentionally mirrors the current PCMAudioPlayer:
        start()
        play(pcm_bytes)
        wait()
        stop()

    It converts CosyVoice 24 kHz mono PCM16 to the firmware's 16 kHz
    full-duplex AEC format with a continuous SoXR streaming state.
    """

    def __init__(
        self,
        hardware: SIAESP32,
        input_rate: int = 24000,
        output_rate: int = 16000,
    ):
        self.hardware = hardware
        self.input_rate = int(input_rate)
        self.output_rate = int(output_rate)

        self._resampler = PCM16StreamingResampler(
            input_rate=self.input_rate,
            output_rate=self.output_rate,
            quality="HQ",
        )

        self._queue: queue.Queue = queue.Queue(maxsize=128)
        self._thread: threading.Thread | None = None
        self._running = False
        self._stream_open = False
        self._worker_error: BaseException | None = None

    def start(self):
        if self._running:
            return

        if not self.hardware.connected:
            self.hardware.connect()

        self._running = True
        self._worker_error = None

        self._thread = threading.Thread(
            target=self._worker,
            name="SIA-TTS-TX",
            daemon=True,
        )
        self._thread.start()

    def _raise_worker_error(self):
        if self._worker_error is not None:
            raise RuntimeError(
                "SIA hardware audio worker failed."
            ) from self._worker_error

    def _begin_if_needed(self):
        if self._stream_open:
            return

        self._resampler.reset()
        self.hardware.tts_start(
            sample_rate=self.output_rate,
            channels=1,
            bits_per_sample=16,
        )
        self._stream_open = True

    def _flush_stream(self):
        if not self._stream_open:
            return

        tail = self._resampler.process(
            b"",
            last=True,
        )

        if tail:
            self.hardware.tts_pcm(tail)

        self.hardware.tts_end()
        self._stream_open = False

    def _worker(self):
        try:
            while True:
                item = self._queue.get()

                try:
                    kind, payload = item

                    if kind == "stop":
                        self._flush_stream()
                        return

                    if kind == "flush":
                        self._flush_stream()
                        payload.set()
                        continue

                    if kind != "pcm":
                        continue

                    self._begin_if_needed()

                    converted = self._resampler.process(
                        payload,
                        last=False,
                    )

                    if converted:
                        self.hardware.tts_pcm(converted)

                finally:
                    self._queue.task_done()

        except BaseException as exc:
            self._worker_error = exc
            self._running = False

    def play(self, pcm: bytes):
        if not pcm:
            return

        self._raise_worker_error()

        if not self._running:
            self.start()

        try:
            self._queue.put(
                ("pcm", bytes(pcm)),
                timeout=3.0,
            )
        except queue.Full as exc:
            raise RuntimeError(
                "SIA TTS queue overflow; host cannot keep up with CosyVoice."
            ) from exc

    def wait(self):
        if not self._running:
            return

        self._raise_worker_error()

        done = threading.Event()
        self._queue.put(("flush", done), timeout=3.0)

        if not done.wait(timeout=15.0):
            self._raise_worker_error()
            raise TimeoutError("SIA TTS flush timed out.")

        self._raise_worker_error()

    def stop(self):
        if not self._running:
            self._raise_worker_error()
            return

        self._queue.put(("stop", None), timeout=3.0)
        self._queue.join()

        if self._thread:
            self._thread.join(timeout=5.0)

        self._thread = None
        self._running = False
        self._raise_worker_error()
