from __future__ import annotations

import queue
import struct
import threading
import time
from dataclasses import dataclass

import serial
from serial.tools import list_ports


# ============================================================
# PROTOCOL CONSTANTS
# ============================================================

MAGIC = 0x31414953
VERSION = 1

HEADER_FMT = "<IBBHIIII"
HEADER_SIZE = struct.calcsize(HEADER_FMT)


class Type:
    HOST_HELLO = 0x01
    SET_ROUTE = 0x02
    PING = 0x03
    GET_STATS = 0x04

    TTS_START = 0x10
    TTS_PCM = 0x11
    TTS_END = 0x12

    MIC_START = 0x20
    MIC_STOP = 0x21

    DEVICE_HELLO = 0x81
    ROUTE_ACK = 0x82
    PONG = 0x83
    STATS = 0x84

    TTS_READY = 0x90
    TTS_DONE = 0x91

    MIC_PCM = 0xA0
    VAD_EVENT = 0xA1

    ERROR = 0xFF


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class DeviceInfo:
    firmware_semver: int
    sample_rate: int
    features: int


@dataclass
class MicFrame:
    pcm: bytes
    speech: bool
    flags: int = 0


# ============================================================
# ESP CRC32
# ============================================================

def esp_crc32_le(
    crc: int,
    data: bytes,
) -> int:

    crc = (~crc) & 0xFFFFFFFF

    for byte in data:
        crc ^= byte

        for _ in range(8):
            if crc & 1:
                crc = (
                    (crc >> 1)
                    ^ 0xEDB88320
                )
            else:
                crc >>= 1

    return (~crc) & 0xFFFFFFFF


# ============================================================
# SIA HARDWARE DRIVER
# ============================================================

class SIAHardware:
    """
    Persistent ESP32-S3 transport.

    One instance owns the discovered SIA serial port for the whole runtime.

    Handles:
        HostHello / DeviceHello
        MicStart / MicStop
        MicPcm
        VadEvent
        SetRoute / RouteAck
        TtsStart / TtsPcm / TtsEnd
        TtsReady / TtsDone
        Ping / Pong
        protocol CRC
    """

    def __init__(
        self,
        port: str | None = None,
        baud: int = 921600,
        mic_queue_frames: int = 128,
    ):
        self.port = (
            str(port).strip()
            if port is not None
            else ""
        )
        self.baud = baud

        self.ser: serial.Serial | None = None

        self._running = threading.Event()

        self._reader_thread: (
            threading.Thread | None
        ) = None

        self._tx_lock = threading.Lock()

        self._sequence = 1

        # ----------------------------------------
        # protocol events
        # ----------------------------------------

        self._device_event = threading.Event()
        self._route_event = threading.Event()
        self._tts_ready_event = threading.Event()
        self._tts_done_event = threading.Event()
        self._pong_event = threading.Event()

        # ----------------------------------------
        # device state
        # ----------------------------------------

        self.device_info: (
            DeviceInfo | None
        ) = None

        self.current_route: (
            str | None
        ) = None

        self.vad_speech = False

        self.last_error: (
            str | None
        ) = None

        # ----------------------------------------
        # microphone queue
        # ----------------------------------------

        self.mic_queue: queue.Queue[
            MicFrame
        ] = queue.Queue(
            maxsize=mic_queue_frames
        )

    # ========================================================
    # CONNECTION
    # ========================================================

    @property
    def connected(self) -> bool:
        return bool(
            self.ser
            and self.ser.is_open
            and self.device_info is not None
        )


    @staticmethod
    def _candidate_ports() -> list[str]:
        """
        Return likely SIA ESP32-S3 serial ports first.

        Espressif USB CDC validated device:
            VID:PID = 303A:4001
        """
        preferred: list[str] = []
        fallback: list[str] = []

        for info in list_ports.comports():
            device = str(info.device)

            if (
                info.vid == 0x303A
                and info.pid == 0x4001
            ):
                preferred.append(device)
            else:
                fallback.append(device)

        return preferred + fallback

    def _open_and_handshake(
        self,
        port: str,
        timeout: float,
    ) -> DeviceInfo:
        self.port = port

        print(
            f"[SIA HW] Opening "
            f"{self.port}..."
        )

        self.ser = serial.Serial(
            self.port,
            self.baud,
            timeout=0.5,
            write_timeout=2.0,
        )

        # Give Windows + TinyUSB a short settle window.
        time.sleep(0.25)

        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

        self._running.set()

        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="sia-usb-rx",
            daemon=True,
        )
        self._reader_thread.start()

        self._device_event.clear()
        self.device_info = None

        self._send_packet(
            Type.HOST_HELLO
        )

        if not self._device_event.wait(timeout):
            self._running.clear()

            try:
                self.ser.close()
            except Exception:
                pass

            self.ser = None
            self._reader_thread = None

            raise TimeoutError(
                "No SIA DeviceHello"
            )

        assert self.device_info is not None
        return self.device_info

    def connect(
        self,
        timeout: float = 2.5,
    ) -> DeviceInfo:

        if self.connected:
            assert self.device_info is not None
            return self.device_info

        explicit = self.port.strip()

        if (
            explicit
            and explicit.lower() not in {
                "auto",
                "discover",
            }
        ):
            candidates = [explicit]
        else:
            candidates = self._candidate_ports()

        if not candidates:
            raise RuntimeError(
                "No serial ports found. "
                "Connect/power the ESP32-S3 and retry."
            )

        errors: list[str] = []

        for candidate in candidates:
            try:
                device = self._open_and_handshake(
                    candidate,
                    timeout,
                )

                print(
                    "[SIA HW] Connected "
                    f"port={self.port} "
                    f"sample_rate="
                    f"{device.sample_rate} "
                    f"features="
                    f"0x{device.features:08X}"
                )

                return device

            except Exception as exc:
                errors.append(
                    f"{candidate}: {exc}"
                )

                self._running.clear()

                if self.ser is not None:
                    try:
                        self.ser.close()
                    except Exception:
                        pass

                self.ser = None
                self._reader_thread = None
                self.device_info = None

        detail = "; ".join(errors[:6])

        raise RuntimeError(
            "Could not find a responding SIA ESP32-S3. "
            f"Tried: {detail}"
        )

    def close(self):
        if not self.ser:
            return

        try:
            if self.ser.is_open:

                try:
                    self.stop_mic()
                except Exception:
                    pass

                try:
                    self.set_route_bluetooth(
                        timeout=1.0
                    )
                except Exception:
                    pass

        finally:

            self._running.clear()

            try:
                self.ser.close()
            except Exception:
                pass

            self.ser = None

        print(
            "[SIA HW] Disconnected"
        )

    # ========================================================
    # MICROPHONE
    # ========================================================

    def start_mic(self):
        if not self.connected:
            raise RuntimeError(
                "SIA hardware is not connected"
            )

        self._clear_mic_queue()

        self._send_packet(
            Type.MIC_START
        )

        print(
            "[SIA HW] Mic stream ON"
        )

    def stop_mic(self):
        if (
            not self.ser
            or not self.ser.is_open
        ):
            return

        self._send_packet(
            Type.MIC_STOP
        )

        print(
            "[SIA HW] Mic stream OFF"
        )

    def get_mic_frame(
        self,
        timeout: float = 1.0,
    ) -> MicFrame | None:

        try:
            return self.mic_queue.get(
                timeout=timeout
            )

        except queue.Empty:
            return None

    def _clear_mic_queue(self):

        while True:
            try:
                self.mic_queue.get_nowait()

            except queue.Empty:
                break

    # ========================================================
    # RELAY / AUDIO ROUTE
    # ========================================================

    def set_route_sia(
        self,
        timeout: float = 3.0,
    ):

        self._set_route(
            route=1,
            name="sia",
            timeout=timeout,
        )

    def set_route_bluetooth(
        self,
        timeout: float = 3.0,
    ):

        self._set_route(
            route=0,
            name="bluetooth",
            timeout=timeout,
        )

    def _set_route(
        self,
        route: int,
        name: str,
        timeout: float,
    ):

        if not self.connected:
            raise RuntimeError(
                "SIA hardware is not connected"
            )

        if self.current_route == name:
            return

        self._route_event.clear()

        payload = struct.pack(
            "<B",
            route,
        )

        self._send_packet(
            Type.SET_ROUTE,
            payload,
        )

        if not self._route_event.wait(
            timeout
        ):
            raise TimeoutError(
                f"No RouteAck for {name}"
            )

        if self.current_route != name:
            raise RuntimeError(
                "Unexpected relay route ACK"
            )

        print(
            "[SIA HW] Speaker route -> "
            f"{name.upper()}"
        )

    # ========================================================
    # TTS PLAYBACK
    # ========================================================

    def tts_start(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        bits_per_sample: int = 16,
        timeout: float = 3.0,
    ):

        if not self.connected:
            raise RuntimeError(
                "SIA hardware is not connected"
            )

        if sample_rate != 16000:
            raise ValueError(
                "ESP32 playback requires "
                "16000 Hz"
            )

        if channels != 1:
            raise ValueError(
                "ESP32 playback requires mono"
            )

        if bits_per_sample != 16:
            raise ValueError(
                "ESP32 playback requires PCM16"
            )

        payload = struct.pack(
            "<IHH",
            sample_rate,
            channels,
            bits_per_sample,
        )

        self._tts_ready_event.clear()

        self._send_packet(
            Type.TTS_START,
            payload,
        )

        if not self._tts_ready_event.wait(
            timeout
        ):
            raise TimeoutError(
                "ESP32 did not send TtsReady"
            )

    def tts_write(
        self,
        pcm16: bytes,
        chunk_bytes: int = 4096,
    ):

        if not pcm16:
            return

        if len(pcm16) % 2:
            pcm16 = pcm16[:-1]

        offset = 0

        while offset < len(pcm16):

            chunk = pcm16[
                offset:
                offset + chunk_bytes
            ]

            self._send_packet(
                Type.TTS_PCM,
                chunk,
            )

            offset += len(chunk)

    def tts_end(
        self,
        timeout: float = 8.0,
    ):

        self._tts_done_event.clear()

        self._send_packet(
            Type.TTS_END
        )

        if not self._tts_done_event.wait(
            timeout
        ):
            raise TimeoutError(
                "ESP32 did not send TtsDone"
            )

    def play_pcm16(
        self,
        pcm16: bytes,
        sample_rate: int = 16000,
    ):

        # Speaker must be connected
        # to MAX98357A.
        self.set_route_sia()

        self.tts_start(
            sample_rate=sample_rate
        )

        self.tts_write(
            pcm16
        )

        self.tts_end()

    # ========================================================
    # PING
    # ========================================================

    def ping(
        self,
        timeout: float = 2.0,
    ) -> bool:

        self._pong_event.clear()

        self._send_packet(
            Type.PING
        )

        return self._pong_event.wait(
            timeout
        )

    # ========================================================
    # PROTOCOL TRANSMIT
    # ========================================================

    def _send_packet(
        self,
        packet_type: int,
        payload: bytes = b"",
        flags: int = 0,
    ):

        if (
            not self.ser
            or not self.ser.is_open
        ):
            raise RuntimeError(
                "SIA hardware is not connected"
            )

        with self._tx_lock:

            sequence = self._sequence

            self._sequence += 1

            timestamp_ms = (
                int(
                    time.monotonic()
                    * 1000
                )
                & 0xFFFFFFFF
            )

            # CRC field must be zero
            # during calculation.
            zero_crc_header = struct.pack(
                HEADER_FMT,
                MAGIC,
                VERSION,
                packet_type,
                flags,
                sequence,
                timestamp_ms,
                len(payload),
                0,
            )

            crc = esp_crc32_le(
                0,
                zero_crc_header,
            )

            if payload:
                crc = esp_crc32_le(
                    crc,
                    payload,
                )

            header = struct.pack(
                HEADER_FMT,
                MAGIC,
                VERSION,
                packet_type,
                flags,
                sequence,
                timestamp_ms,
                len(payload),
                crc,
            )

            written = self.ser.write(
                header + payload
            )

            if written != len(header) + len(payload):
                raise serial.SerialTimeoutException(
                    "Incomplete SIA packet write"
                )

    # ========================================================
    # READER THREAD
    # ========================================================

    def _reader_loop(self):

        print(
            "[SIA HW] RX thread started"
        )

        while self._running.is_set():

            try:
                packet = (
                    self._read_packet()
                )

                if packet is None:
                    continue

                (
                    packet_type,
                    flags,
                    payload,
                ) = packet

                self._handle_packet(
                    packet_type,
                    flags,
                    payload,
                )

            except serial.SerialException as exc:

                if self._running.is_set():
                    print(
                        "[SIA HW] Serial error: "
                        f"{exc}"
                    )

                break

            except Exception as exc:

                if self._running.is_set():
                    print(
                        "[SIA HW] RX error: "
                        f"{exc}"
                    )

    # ========================================================
    # PACKET RECEIVE
    # ========================================================

    def _read_packet(
        self,
    ) -> tuple[
        int,
        int,
        bytes,
    ] | None:

        if not self.ser:
            return None

        if not self._find_magic():
            return None

        rest = self._read_exact(
            HEADER_SIZE - 4
        )

        if rest is None:
            return None

        header_bytes = (
            struct.pack(
                "<I",
                MAGIC,
            )
            + rest
        )

        (
            magic,
            version,
            packet_type,
            flags,
            sequence,
            timestamp_ms,
            payload_size,
            received_crc,
        ) = struct.unpack(
            HEADER_FMT,
            header_bytes,
        )

        if version != VERSION:
            raise RuntimeError(
                "Protocol version mismatch: "
                f"{version}"
            )

        if payload_size > (
            16 * 1024
        ):
            raise RuntimeError(
                "Invalid payload size: "
                f"{payload_size}"
            )

        if payload_size:

            payload = self._read_exact(
                payload_size
            )

            if payload is None:
                return None

        else:
            payload = b""

        zero_crc_header = struct.pack(
            HEADER_FMT,
            magic,
            version,
            packet_type,
            flags,
            sequence,
            timestamp_ms,
            payload_size,
            0,
        )

        expected_crc = (
            esp_crc32_le(
                0,
                zero_crc_header,
            )
        )

        if payload:
            expected_crc = (
                esp_crc32_le(
                    expected_crc,
                    payload,
                )
            )

        if (
            expected_crc
            != received_crc
        ):
            raise RuntimeError(
                "RX CRC mismatch"
            )

        return (
            packet_type,
            flags,
            payload,
        )

    # ========================================================
    # MAGIC SYNCHRONIZATION
    # ========================================================

    def _find_magic(
        self,
    ) -> bool:

        if not self.ser:
            return False

        target = struct.pack(
            "<I",
            MAGIC,
        )

        window = bytearray()

        while self._running.is_set():

            byte = self.ser.read(1)

            if not byte:
                continue

            window.extend(
                byte
            )

            if len(window) > 4:
                del window[0]

            if bytes(window) == target:
                return True

        return False

    # ========================================================
    # EXACT SERIAL READ
    # ========================================================

    def _read_exact(
        self,
        size: int,
    ) -> bytes | None:

        if not self.ser:
            return None

        data = bytearray()

        while (
            len(data) < size
            and self._running.is_set()
        ):

            chunk = self.ser.read(
                size - len(data)
            )

            if not chunk:
                continue

            data.extend(
                chunk
            )

        if len(data) != size:
            return None

        return bytes(
            data
        )

    # ========================================================
    # PACKET DISPATCH
    # ========================================================

    def _handle_packet(
        self,
        packet_type: int,
        flags: int,
        payload: bytes,
    ):

        # ----------------------------------------
        # DEVICE HELLO
        # ----------------------------------------

        if (
            packet_type
            == Type.DEVICE_HELLO
        ):

            if len(payload) >= 12:

                (
                    firmware_semver,
                    sample_rate,
                    features,
                ) = struct.unpack(
                    "<III",
                    payload[:12],
                )

                self.device_info = (
                    DeviceInfo(
                        firmware_semver=
                        firmware_semver,
                        sample_rate=
                        sample_rate,
                        features=
                        features,
                    )
                )

                self._device_event.set()

        # ----------------------------------------
        # MICROPHONE PCM
        # ----------------------------------------

        elif (
            packet_type
            == Type.MIC_PCM
        ):

            frame = MicFrame(
                pcm=payload,
                speech=bool(
                    flags & 0x0001
                ),
                flags=flags,
            )

            try:
                self.mic_queue.put_nowait(
                    frame
                )

            except queue.Full:

                # USB RX must never block.
                # If consumer falls behind,
                # discard oldest frame.
                try:
                    self.mic_queue.get_nowait()

                except queue.Empty:
                    pass

                try:
                    self.mic_queue.put_nowait(
                        frame
                    )

                except queue.Full:
                    pass

        # ----------------------------------------
        # VAD EVENT
        # ----------------------------------------

        elif (
            packet_type
            == Type.VAD_EVENT
        ):

            if payload:

                new_state = bool(
                    payload[0]
                )

                if (
                    new_state
                    != self.vad_speech
                ):

                    self.vad_speech = (
                        new_state
                    )

                    print(
                        "[SIA VAD]",
                        "SPEECH"
                        if new_state
                        else "SILENCE",
                    )

        # ----------------------------------------
        # ROUTE ACK
        # ----------------------------------------

        elif (
            packet_type
            == Type.ROUTE_ACK
        ):

            if payload:

                self.current_route = (
                    "sia"
                    if payload[0] == 1
                    else "bluetooth"
                )

                self._route_event.set()

        # ----------------------------------------
        # TTS READY
        # ----------------------------------------

        elif (
            packet_type
            == Type.TTS_READY
        ):

            self._tts_ready_event.set()

        # ----------------------------------------
        # TTS DONE
        # ----------------------------------------

        elif (
            packet_type
            == Type.TTS_DONE
        ):

            self._tts_done_event.set()

        # ----------------------------------------
        # PONG
        # ----------------------------------------

        elif (
            packet_type
            == Type.PONG
        ):

            self._pong_event.set()

        # ----------------------------------------
        # ESP ERROR
        # ----------------------------------------

        elif (
            packet_type
            == Type.ERROR
        ):

            self.last_error = (
                payload
                .rstrip(b"\x00")
                .decode(
                    "utf-8",
                    errors="replace",
                )
            )

            print(
                "[SIA ESP ERROR] "
                f"{self.last_error}"
            )