# tts_pipelined.py
import wave
import re
import queue
import threading
import time
from io import BytesIO
from typing import Dict, Optional

import requests
import simpleaudio as sa

try:
    from motor_controller import MotorController
except Exception:
    class MotorController:
        def led_start_blink(self): pass
        def led_stop_blink(self): pass
        def motor_tilt_kyoro_kyoro(self, n:int=1): pass


class VoiceVoxTTSPipelined:
    """
    VOICEVOX: 文の合成(並列) と 再生(順序保証) をパイプライン化した常駐ストリームTTS。
      - start_stream(..., synth_workers=N): 常駐開始（N並列で合成）
      - push_text(text): 断片を何度でも投入。文末/長さで文にスプリット
      - close_stream(): これ以上入力が無いことを通知（残りを読み上げて終了）
      - wait_until_idle(): 再生完了まで待機（任意）
      - stop(): 即時停止（緊急）
      - shutdown(): 安全終了（プロセス終了時に）
    """

    _SENT_END = re.compile(r"[。．！？!?]\s*$")

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:50021",
        speaker: int = 89,
        max_len: int = 80,
        queue_size_sent: int = 32,    # 文キュー
        request_timeout_query: int = 15,
        request_timeout_synth: int = 60,
        default_params: Optional[Dict] = None,
    ):
        self.base_url = base_url
        self.speaker = speaker
        self.max_len = max_len
        self.queue_size_sent = queue_size_sent
        self.request_timeout_query = request_timeout_query
        self.request_timeout_synth = request_timeout_synth

        self.params = {
            "speedScale": 1.0,
            "pitchScale": 0.0,
            "intonationScale": 1.0,
            "volumeScale": 1.0,
            "prePhonemeLength": 0.1,
            "postPhonemeLength": 0.1,
            "enableInterrogativeUpspeak": True,
        }
        if default_params:
            self.params.update(default_params)

        # 再生・状態
        self._motor: Optional[MotorController] = None
        self._filler = None
        self._corr_gate = None
        self._play_obj: Optional[sa.PlayObject] = None

        # 制御フラグ
        self._stop_event = threading.Event()     # 即停止
        self._closed_event = threading.Event()   # 入力終端
        self._started = False
        self._is_speaking = False
        self._state_lock = threading.Lock()

        # キュー/共有
        self._in_q: "queue.Queue[str]" = queue.Queue(maxsize=1024)                 # 断片
        self._sent_q: "queue.Queue[tuple[int, str]]" = queue.Queue(self.queue_size_sent)  # (seq, 文)

        # 合成結果（順序保持用）
        self._results: Dict[int, bytes] = {}
        self._results_cv = threading.Condition()  # _results と _next_seq 用
        self._next_seq = 0
        self._seq_counter = 0

        # スレッド
        self._th_ingest: Optional[threading.Thread] = None
        self._th_player: Optional[threading.Thread] = None
        self._th_synths: list[threading.Thread] = []

    # ---------- Public API ----------
    def set_params(self, **kwargs):
        self.params.update(kwargs)

    def set_speaker(self, speaker: int):
        self.speaker = speaker

    def start_stream(self, motor_controller: MotorController, corr_gate=None, filler=None, synth_workers: int = 2):
        with self._state_lock:
            if self._started:
                return
            self._started = True
            self._stop_event.clear()
            self._closed_event.clear()
            self._is_speaking = True

            self._motor = motor_controller
            self._corr_gate = corr_gate
            self._filler = filler

            # ingest
            self._th_ingest = threading.Thread(target=self._run_ingest, name="tts_ingest", daemon=True)
            self._th_ingest.start()

            # synth workers
            self._th_synths = []
            for i in range(max(1, synth_workers)):
                th = threading.Thread(target=self._run_synth_worker, name=f"tts_synth_{i}", daemon=True)
                th.start()
                self._th_synths.append(th)

            # player
            self._th_player = threading.Thread(target=self._run_player, name="tts_player", daemon=True)
            self._th_player.start()

    def push_text(self, text: str):
        if not text:
            return
        if not self._started:
            raise RuntimeError("start_stream() を先に呼んでください。")
        try:
            self._in_q.put_nowait(text)
        except queue.Full:
            self._in_q.put(text)  # backpressure

    def close_stream(self):
        self._closed_event.set()

    def wait_until_idle(self, poll: float = 0.05):
        while self.is_playing():
            time.sleep(poll)

    def stop(self):
        """即時停止（キュー排水・再生停止）"""
        self._stop_event.set()
        with self._suppress_ex():
            if self._play_obj:
                self._play_obj.stop()
        self._drain_queue(self._in_q)
        self._drain_queue(self._sent_q)
        with self._results_cv:
            self._results.clear()
            self._results_cv.notify_all()

    def is_playing(self) -> bool:
        if self._stop_event.is_set():
            return False
        if self._is_speaking:
            return True
        if self._play_obj is not None:
            try:
                return self._play_obj.is_playing()
            except Exception:
                return False
        return False

    def shutdown(self, timeout: float = 2.0):
        self.close_stream()
        self.wait_until_idle()
        self._stop_event.set()
        for th in ([self._th_ingest] + self._th_synths + [self._th_player]):
            if th and th.is_alive():
                th.join(timeout=timeout)
        with self._state_lock:
            self._started = False
            self._is_speaking = False

    # ---------- Threads ----------
    def _run_ingest(self):
        buf = ""
        while not self._stop_event.is_set():
            try:
                timeout = 0.1 if self._closed_event.is_set() else 1.0
                try:
                    piece = self._in_q.get(timeout=timeout)
                except queue.Empty:
                    piece = None

                if piece is None:
                    if self._closed_event.is_set():
                        tail = buf.strip()
                        if tail:
                            seq = self._seq_counter; self._seq_counter += 1
                            self._sent_q.put((seq, tail))
                        break
                    continue

                buf += piece
                if len(buf) >= self.max_len or self._SENT_END.search(buf):
                    s = buf.strip()
                    if s:
                        seq = self._seq_counter; self._seq_counter += 1
                        self._sent_q.put((seq, s))
                    buf = ""

            except Exception:
                if self._stop_event.is_set():
                    break

        # 最終フラッシュ（保険）
        tail = buf.strip()
        if tail:
            with self._suppress_ex():
                seq = self._seq_counter; self._seq_counter += 1
                self._sent_q.put((seq, tail))

    def _run_synth_worker(self):
        while not self._stop_event.is_set():
            try:
                timeout = 0.1 if self._closed_event.is_set() else 1.0
                try:
                    seq, sent = self._sent_q.get(timeout=timeout)
                except queue.Empty:
                    if self._closed_event.is_set() and self._sent_q.empty():
                        break
                    continue

                # 合成
                query = self._audio_query(sent, self.speaker)
                query.update(self.params)
                wav_bytes = self._synth(query, self.speaker)

                # AECにfar-end供給（任意）
                if self._corr_gate is not None:
                    with self._suppress_ex():
                        pcm = self._wav_to_int16_mono16k(wav_bytes)
                        self._corr_gate.publish_farend(pcm)

                # 結果を登録（順序保証はplayer側）
                with self._results_cv:
                    self._results[seq] = wav_bytes
                    self._results_cv.notify_all()

            except Exception:
                if self._stop_event.is_set():
                    break

    def _run_player(self):
        start_time = time.perf_counter()
        try:
            while not self._stop_event.is_set():
                with self._results_cv:
                    # 次に再生すべき seq が来るまで待つ
                    while (self._next_seq not in self._results) and not self._stop_event.is_set():
                        # すべて閉じて空なら終了
                        if (self._closed_event.is_set() and
                            self._sent_q.empty() and
                            not self._results and
                            (self._next_seq >= self._seq_counter)):
                            return
                        self._results_cv.wait(timeout=0.2)

                    if self._stop_event.is_set():
                        break

                    wav_bytes = self._results.pop(self._next_seq, None)

                if wav_bytes is None:
                    continue  # もう一度待つ

                # 再生
                self._play(wav_bytes)

                # ログ：初回からのレイテンシ
                end_time = time.perf_counter()
                print(f"[VoiceVox latency] {end_time - start_time:.1f} s")

                # 文ごとに待つと自然
                if self._play_obj:
                    self._play_obj.wait_done()

                self._next_seq += 1
        finally:
            with self._suppress_ex():
                if self._play_obj:
                    self._play_obj.stop()
                if self._motor:
                    self._motor.led_stop_blink()
            self._is_speaking = False

    # ---------- HTTP / audio ----------
    def _audio_query(self, text: str, speaker: int) -> Dict:
        r = requests.post(
            f"{self.base_url}/audio_query",
            params={"text": text, "speaker": speaker},
            timeout=self.request_timeout_query,
        )
        r.raise_for_status()
        return r.json()

    def _synth(self, query: Dict, speaker: int) -> bytes:
        r = requests.post(
            f"{self.base_url}/synthesis",
            params={"speaker": speaker},
            json=query,
            timeout=self.request_timeout_synth,
        )
        r.raise_for_status()
        return r.content

    def _play(self, wav_bytes: bytes):
        with wave.open(BytesIO(wav_bytes), "rb") as wf:
            wav = sa.WaveObject.from_wave_read(wf)
        if self._filler is not None:
            with self._suppress_ex():
                self._filler.stop_filler()
        if self._motor:
            with self._suppress_ex():
                self._motor.led_start_blink()
                self._motor.motor_tilt_kyoro_kyoro(2)
        self._play_obj = wav.play()

    # ---------- utils ----------
    def _wav_to_int16_mono16k(self, wav_bytes: bytes):
        import numpy as np, io, wave
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            ch = wf.getnchannels()
            sr = wf.getframerate()
            n = wf.getnframes()
            pcm = np.frombuffer(wf.readframes(n), dtype=np.int16)
            if ch > 1:
                pcm = pcm.reshape(-1, ch).mean(axis=1).astype(np.int16)
        if sr != 16000:
            import numpy as np
            ratio = 16000 / sr
            x_old = np.arange(len(pcm))
            x_new = np.arange(0, len(pcm), 1/ratio)
            pcm = np.interp(x_new, x_old, pcm.astype(np.float32)).astype(np.int16)
        return pcm

    @staticmethod
    def _drain_queue(q: "queue.Queue"):
        with VoiceVoxTTSPipelined._suppress_ex():
            while not q.empty():
                q.get_nowait()

    @staticmethod
    def _suppress_ex():
        class _Ctx:
            def __enter__(self): return self
            def __exit__(self, exc_type, exc, tb): return True
        return _Ctx()
