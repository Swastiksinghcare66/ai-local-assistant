import asyncio
import json
import queue
import threading
import time
import uuid

import sounddevice as sd
import websockets


class PCMAudioPlayer:
    """
    Background PCM playback with immediate queue interruption.

    Audio is written in ~20 ms slices. This bounds playback-stop reaction time
    to roughly one slice instead of waiting for an entire queued PCM packet.
    """

    def __init__(
        self,
        sample_rate=24000,
        channels=1,
        dtype="int16",
        slice_ms=20,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        self.slice_ms = max(10, int(slice_ms))

        self.audio_queue = queue.Queue()
        self.thread = None
        self.running = False
        self.stream = None

        self._generation = 0
        self._generation_lock = threading.Lock()
        self._pause_event = threading.Event()
        self._pause_event.set()

        bytes_per_sample = 2  # int16
        self._slice_bytes = max(
            bytes_per_sample * self.channels,
            int(
                self.sample_rate
                * self.channels
                * bytes_per_sample
                * self.slice_ms
                / 1000.0
            ),
        )

    def _get_generation(self):
        with self._generation_lock:
            return self._generation

    def start(self):
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(
            target=self._worker,
            daemon=True,
            name="sara-pcm-player",
        )
        self.thread.start()

    def _worker(self):
        try:
            self.stream = sd.RawOutputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                blocksize=0,
            )
            self.stream.start()

            while self.running:
                item = self.audio_queue.get()

                try:
                    if item is None:
                        break

                    generation, pcm = item
                    if generation != self._get_generation():
                        continue

                    for offset in range(0, len(pcm), self._slice_bytes):
                        if (
                            not self.running
                            or generation != self._get_generation()
                        ):
                            break

                        # Soft pause is used to classify a potential barge-in.
                        # It keeps queued PCM intact so a short "hmm"/"yeah"
                        # can resume without restarting TTS.
                        while (
                            self.running
                            and generation == self._get_generation()
                            and not self._pause_event.wait(timeout=0.01)
                        ):
                            pass

                        if (
                            not self.running
                            or generation != self._get_generation()
                        ):
                            break

                        chunk = pcm[
                            offset:
                            offset + self._slice_bytes
                        ]

                        if chunk:
                            self.stream.write(chunk)

                finally:
                    self.audio_queue.task_done()

        except Exception as exc:
            print("[AUDIO PLAYER ERROR]", repr(exc))

        finally:
            if self.stream is not None:
                try:
                    self.stream.stop()
                except Exception:
                    pass

                try:
                    self.stream.close()
                except Exception:
                    pass

                self.stream = None

    def play(self, pcm: bytes):
        if not pcm:
            return

        if not self.running:
            self.start()

        self.audio_queue.put(
            (
                self._get_generation(),
                bytes(pcm),
            )
        )

    def wait(self):
        self.audio_queue.join()

    def pause(self):
        """Pause speaker output quickly while preserving queued PCM."""
        self._pause_event.clear()

    def resume(self):
        """Resume a soft-paused speaker queue."""
        self._pause_event.set()

    def interrupt(self):
        """
        Drop queued/current-generation speech immediately.

        The worker checks the generation every ~20 ms, so interruption is fast
        without killing/recreating the audio device.
        """
        with self._generation_lock:
            self._generation += 1

        self._pause_event.set()

        while True:
            try:
                item = self.audio_queue.get_nowait()
            except queue.Empty:
                break
            else:
                self.audio_queue.task_done()

    def stop(self, drain=False):
        if not self.running:
            return

        if drain:
            self.audio_queue.join()
        else:
            self.interrupt()

        self.running = False
        self.audio_queue.put(None)

        if self.thread is not None:
            self.thread.join(timeout=5)

        self.thread = None


class CosyVoicePersistentClient:
    """
    Persistent Windows client for Sara's WSL CosyVoice server.

    One WebSocket connection can carry multiple sequential
    TTS requests.

    Designed for:
        Qwen phrase 1 -> TTS
        Qwen phrase 2 -> TTS
        Qwen phrase 3 -> TTS

    without reconnecting for every phrase.
    """

    def __init__(
        self,
        url="ws://127.0.0.1:5051/tts",
        default_style="warm_conversational",
        default_flow_steps=5,
        playback=True,
        player=None,
    ):

        self.url = url

        self.default_style = (
            default_style
        )

        self.default_flow_steps = (
            default_flow_steps
        )

        self.playback = playback

        self.websocket = None

        self.speak_lock = (
            asyncio.Lock()
        )

        # Playback backend injection:
        #   player=None + playback=True -> existing PC speaker player
        #   player=SIAAudioPlayer(...)   -> ESP32-S3/MAX98357A
        #   playback=False              -> no local playback
        self.player = (
            player
            if player is not None
            else (
                PCMAudioPlayer()
                if playback
                else None
            )
        )

        self._interrupt_epoch = 0
        self._interrupt_lock = threading.Lock()


    # ========================================================
    # CONNECTION
    # ========================================================

    async def connect(self):

        if self.websocket is not None:
            return

        start = time.perf_counter()

        self.websocket = (
            await websockets.connect(
                self.url,
                max_size=None,
                open_timeout=10,
                ping_interval=20,
                ping_timeout=20,
            )
        )

        elapsed_ms = (
            time.perf_counter()
            - start
        ) * 1000.0

        if self.player is not None:
            self.player.start()

        print(
            f"[COSYVOICE] Connected in "
            f"{elapsed_ms:.1f} ms"
        )


    async def ensure_connected(self):

        if self.websocket is None:
            await self.connect()


    # ========================================================
    # PING
    # ========================================================

    async def ping(self):

        await self.ensure_connected()

        start = time.perf_counter()

        await self.websocket.send(
            json.dumps(
                {
                    "type": "ping"
                }
            )
        )

        raw = (
            await self.websocket.recv()
        )

        elapsed_ms = (
            time.perf_counter()
            - start
        ) * 1000.0

        if isinstance(raw, bytes):

            raise RuntimeError(
                "Unexpected binary response "
                "to ping."
            )

        data = json.loads(raw)

        if data.get("type") != "pong":

            raise RuntimeError(
                f"Unexpected ping response: "
                f"{data}"
            )

        return {
            "latency_ms":
                elapsed_ms,

            "server":
                data.get("server"),
        }


    # ========================================================
    # SPEAK
    # ========================================================

    async def speak(
        self,
        text,
        style=None,
        flow_steps=None,
    ):

        text = str(text).strip()

        if not text:
            return None

        if style is None:

            style = (
                self.default_style
            )

        if flow_steps is None:

            flow_steps = (
                self.default_flow_steps
            )

        await self.ensure_connected()

        with self._interrupt_lock:
            request_epoch = self._interrupt_epoch

        # Server currently performs one serialized inference
        # at a time. Protect the connection from overlapping
        # receive loops.

        async with self.speak_lock:

            request_id = (
                uuid.uuid4().hex[:12]
            )

            payload = {
                "type":
                    "tts",

                "request_id":
                    request_id,

                "text":
                    text,

                "style":
                    style,

                "mode":
                    "stream",

                "flow_steps":
                    flow_steps,
            }

            request_start = (
                time.perf_counter()
            )

            await self.websocket.send(
                json.dumps(payload)
            )

            start_received = None
            first_audio_received = None

            packet_count = 0
            pcm_bytes = 0

            server_report = None

            while True:

                message = (
                    await self.websocket.recv()
                )

                now = (
                    time.perf_counter()
                )


                # ============================================
                # PCM
                # ============================================

                if isinstance(
                    message,
                    bytes,
                ):

                    if (
                        first_audio_received
                        is None
                    ):

                        first_audio_received = (
                            now
                        )

                    packet_count += 1

                    pcm_bytes += len(
                        message
                    )

                    with self._interrupt_lock:
                        interrupted = (
                            request_epoch
                            != self._interrupt_epoch
                        )

                    if (
                        self.player is not None
                        and not interrupted
                    ):
                        self.player.play(message)

                    continue


                # ============================================
                # JSON
                # ============================================

                data = json.loads(
                    message
                )

                message_type = (
                    data.get("type")
                )


                if message_type == "start":

                    if (
                        data.get("request_id")
                        != request_id
                    ):

                        raise RuntimeError(
                            "CosyVoice request ID "
                            "mismatch."
                        )

                    start_received = (
                        now
                    )

                    continue


                if message_type == "end":

                    if (
                        data.get("request_id")
                        != request_id
                    ):

                        raise RuntimeError(
                            "CosyVoice end request ID "
                            "mismatch."
                        )

                    server_report = data

                    break


                if message_type == "error":

                    raise RuntimeError(
                        data.get(
                            "message",
                            "Unknown CosyVoice error",
                        )
                    )


            end_time = (
                time.perf_counter()
            )


            # ================================================
            # CLIENT TIMINGS
            # ================================================

            client_ttfa_ms = None

            if (
                first_audio_received
                is not None
            ):

                client_ttfa_ms = (
                    first_audio_received
                    - request_start
                ) * 1000.0


            start_response_ms = None

            if start_received is not None:

                start_response_ms = (
                    start_received
                    - request_start
                ) * 1000.0


            client_total_seconds = (
                end_time
                - request_start
            )


            result = {
                "request_id":
                    request_id,

                "text":
                    text,

                "style":
                    style,

                "flow_steps":
                    flow_steps,

                "client_start_ms":
                    start_response_ms,

                "client_ttfa_ms":
                    client_ttfa_ms,

                "client_total_seconds":
                    client_total_seconds,

                "packets":
                    packet_count,

                "pcm_bytes":
                    pcm_bytes,

                "server":
                    server_report,
            }


            return result


    def pause_playback(self):
        if self.player is not None:
            self.player.pause()

    def resume_playback(self):
        if self.player is not None:
            self.player.resume()

    async def interrupt(self):
        """
        Immediately silence current/queued playback and reset the TTS
        WebSocket so the next request starts from a clean protocol state.
        """
        with self._interrupt_lock:
            self._interrupt_epoch += 1

        if self.player is not None:
            self.player.interrupt()

        ws = self.websocket
        self.websocket = None

        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass

    # ========================================================
    # WAIT FOR PLAYBACK
    # ========================================================

    def wait_for_playback(self):

        if self.player is not None:
            self.player.wait()


    # ========================================================
    # CLOSE
    # ========================================================

    async def close(self):

        if self.websocket is not None:

            try:

                await self.websocket.send(
                    json.dumps(
                        {
                            "type":
                                "close"
                        }
                    )
                )

                response = (
                    await self.websocket.recv()
                )

                if not isinstance(
                    response,
                    bytes,
                ):

                    data = json.loads(
                        response
                    )

                    if (
                        data.get("type")
                        == "closing"
                    ):

                        pass

            except Exception:
                pass


            try:

                await self.websocket.close()

            except Exception:
                pass


            self.websocket = None


        if self.player is not None:

            self.player.stop(drain=False)


        print(
            "[COSYVOICE] Disconnected"
        )


# ============================================================
# STANDALONE PERSISTENT CONNECTION TEST
# ============================================================

async def main():

    client = (
        CosyVoicePersistentClient(
            playback=True
        )
    )


    try:

        # ----------------------------------------------------
        # CONNECT ONCE
        # ----------------------------------------------------

        await client.connect()


        # ----------------------------------------------------
        # PING
        # ----------------------------------------------------

        ping_result = (
            await client.ping()
        )

        print()

        print(
            f"Server: "
            f"{ping_result['server']}"
        )

        print(
            f"Persistent WS ping: "
            f"{ping_result['latency_ms']:.1f} ms"
        )


        # ----------------------------------------------------
        # MULTIPLE REQUESTS THROUGH SAME CONNECTION
        # ----------------------------------------------------

        phrases = [
            (
                "Hello Swastik. "
                "This is the first phrase "
                "on one persistent connection."
            ),

            (
                "This is the second phrase, "
                "and I did not reconnect "
                "to the speech server."
            ),

            (
                "Persistent speech streaming "
                "is now ready for Qwen integration."
            ),
        ]


        print()

        print("=" * 72)
        print(
            "PERSISTENT COSYVOICE TEST"
        )
        print("=" * 72)


        for index, phrase in enumerate(
            phrases,
            start=1,
        ):

            print()

            print(
                f"Phrase {index}: "
                f"{phrase}"
            )

            result = (
                await client.speak(
                    phrase
                )
            )

            server = (
                result["server"]
                or {}
            )


            print(
                f"Client TTFA : "
                f"{result['client_ttfa_ms']:.1f} ms"
            )

            print(
                f"Server TTFA : "
                f"{server.get('model_ttfa_ms')} ms"
            )

            print(
                f"Wire TTFA   : "
                f"{server.get('wire_ttfa_ms')} ms"
            )

            print(
                f"Generation  : "
                f"{server.get('generation_time')} s"
            )

            print(
                f"RTF         : "
                f"{server.get('rtf')}"
            )

            print(
                f"Packets     : "
                f"{result['packets']}"
            )


        # Finish playing all queued speech before exiting.

        print()

        print(
            "Waiting for queued audio "
            "playback to finish..."
        )

        client.wait_for_playback()


        print()

        print("=" * 72)
        print(
            "PERSISTENT CONNECTION TEST PASSED"
        )
        print("=" * 72)


    finally:

        await client.close()


if __name__ == "__main__":

    asyncio.run(
        main()
    )