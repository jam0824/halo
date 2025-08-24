# stt.py
# Google Cloud Speech-to-Text v2 + WebRTC VAD
# 変更点:
# - ターン間で close() しない方針に変更（ホットリユース）
# - _ensure_input_started() / _pause_input() を追加して pause/resume
# - 録音スレッドは daemon=True で短時間 join
# - 設定オブジェクトを __init__ で作成して再利用

import os, sys, queue, threading, time
from typing import Optional
import pyaudio
import google.auth
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech as cs
from google.protobuf import duration_pb2


class SpeechToText:
    def __init__(self, language="ja-JP", model="latest_short", location="asia-northeast1"):
        # STT 設定
        self.LANGUAGE = language
        self.MODEL = model
        self.LOCATION = location
        self.RATE = 16000
        self.CHANNELS = 1
        self.CHUNK_MS = 50
        self.FRAMES_PER_BUFFER = self.RATE * self.CHUNK_MS // 1000

        # 内部管理
        self._stop_event = threading.Event()
        self._pa: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._producer: Optional[threading.Thread] = None
        self._q: Optional["queue.Queue[bytes|None]"] = None
        self._input_device_index: Optional[int] = None
        self._closed = False

        # GCP
        self.project_id = self._get_project_id()
        self.client = self._make_client()

        # 設定オブジェクトは一度作って使い回す（微小ながら毎回の生成コストを削減）
        self._recognizer_path = f"projects/{self.project_id}/locations/{self.LOCATION}/recognizers/_"
        self._decoding = cs.ExplicitDecodingConfig(
            encoding=cs.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=self.RATE,
            audio_channel_count=self.CHANNELS,
        )
        self._recognition_config = cs.RecognitionConfig(
            explicit_decoding_config=self._decoding,
            language_codes=[self.LANGUAGE],
            model=self.MODEL,
            features=cs.RecognitionFeatures(enable_automatic_punctuation=True),
        )
        self._streaming_features = cs.StreamingRecognitionFeatures(
            enable_voice_activity_events=True,
            voice_activity_timeout=cs.StreamingRecognitionFeatures.VoiceActivityTimeout(
                # 必要なら調整: 開始待ち/終了判定の猶予
                speech_start_timeout=duration_pb2.Duration(seconds=5, nanos=0),
                speech_end_timeout=duration_pb2.Duration(seconds=0, nanos=500_000_000),
            ),
        )
        self._streaming_config = cs.StreamingRecognitionConfig(
            config=self._recognition_config,
            streaming_features=self._streaming_features,
        )

    # ---- lifecycle ----
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        """
        完全停止: プロセス終了時のみ呼ぶ。デバイス・スレッド・クライアントを解放。
        """
        if self._closed:
            return
        self._pause_input(pause_stream=True)  # キャプチャ停止（軽量）

        # デバイス解放
        try:
            if self._stream is not None:
                try:
                    if self._stream.is_active():
                        self._stream.stop_stream()
                except Exception:
                    pass
                try:
                    self._stream.close()
                except Exception:
                    pass
            if self._pa is not None:
                try:
                    self._pa.terminate()
                except Exception:
                    pass
        finally:
            self._stream = None
            self._pa = None
            self._q = None
            # gRPCクライアントを明示的に閉じる
            if hasattr(self.client, "close"):
                try:
                    self.client.close()
                except Exception:
                    pass
            self._closed = True

    # ---- GCP ----
    def _get_project_id(self) -> str:
        pid = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT")
        if pid:
            return pid
        _, project_id = google.auth.default()
        if not project_id:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT を設定するか、ADC を見直してください。")
        return project_id

    def _make_client(self) -> SpeechClient:
        endpoint = f"{self.LOCATION}-speech.googleapis.com" if self.LOCATION != "global" else "speech.googleapis.com"
        return SpeechClient(client_options=ClientOptions(api_endpoint=endpoint))

    # ---- audio (hot reuse) ----
    def _ensure_input_started(self):
        """
        マイク入力をホットスタート。既に開いていれば start_stream のみ。
        キューと録音スレッドはターンごとに張り替える（軽量）。
        """
        self._stop_event.clear()

        if self._pa is None:
            self._pa = pyaudio.PyAudio()
            try:
                info = self._pa.get_default_input_device_info()
            except Exception as e:
                self._pa.terminate(); self._pa = None
                raise RuntimeError("既定の入力デバイスが見つかりません。") from e
            self._input_device_index = int(info["index"])
            name = info.get("name", "unknown")
            print(f"Using default mic (hot): index={self._input_device_index}, name='{name}', capture_rate={self.RATE}")

        if self._stream is None:
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                input_device_index=self._input_device_index,
                frames_per_buffer=self.FRAMES_PER_BUFFER,
            )
        else:
            # 前ターンで止めていれば再開
            if not self._stream.is_active():
                try:
                    self._stream.start_stream()
                except Exception:
                    # まれに OS 側で壊れている場合は作り直す
                    try:
                        self._stream.close()
                    except Exception:
                        pass
                    self._stream = self._pa.open(
                        format=pyaudio.paInt16,
                        channels=self.CHANNELS,
                        rate=self.RATE,
                        input=True,
                        input_device_index=self._input_device_index,
                        frames_per_buffer=self.FRAMES_PER_BUFFER,
                    )

        self._q = queue.Queue()

        def fill_buffer():
            try:
                while not self._stop_event.is_set():
                    data = self._stream.read(self.FRAMES_PER_BUFFER, exception_on_overflow=False)
                    self._q.put(data)
            except Exception:
                pass
            finally:
                try:
                    self._q.put_nowait(None)
                except Exception:
                    pass

        # すぐ終了できるよう daemon スレッドに
        self._producer = threading.Thread(target=fill_buffer, daemon=True)
        self._producer.start()

    def _pause_input(self, pause_stream: bool = True):
        """
        録音スレッドを停止し、必要ならストリームを一時停止する。
        リソースは解放しない（ホットスタンバイ）。
        """
        self._stop_event.set()

        # 先に stop_stream すると read() が速やかに抜ける
        if pause_stream and self._stream is not None:
            try:
                if self._stream.is_active():
                    self._stream.stop_stream()
            except Exception:
                pass

        # 録音スレッド終了待ち（長時間待たない）
        if self._producer and self._producer.is_alive():
            self._producer.join(timeout=0.3)
        self._producer = None

        # キューは破棄
        self._q = None

    def _mic_stream(self):
        """generator: マイク入力を逐次返す。"""
        self._ensure_input_started()
        try:
            while not self._stop_event.is_set():
                chunk = self._q.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            # 実際の解放は close()、ここでは停止のみ
            pass

    # ---- gRPC ----
    def _request_generator(self):
        """StreamingRecognizeRequest の generator"""
        # 最初に config
        yield cs.StreamingRecognizeRequest(
            recognizer=self._recognizer_path,
            streaming_config=self._streaming_config,
        )
        # 続いて音声チャンク
        for chunk in self._mic_stream():
            if self._stop_event.is_set():
                break
            yield cs.StreamingRecognizeRequest(audio=chunk)

    # ---- public ----
    def listen_once(self, timeout_sec: float = 15.0) -> str:
        """
        1回の発話を認識してテキストを返す（ターン間はホットスタンバイ）。
        """
        print(f"[Listening] language={self.LANGUAGE}, model={self.MODEL}, location={self.LOCATION}  (発話してください)")
        start = time.time()
        first_text_time = None
        latest_text = ""
        saw_vad_begin = False
        saw_any_text = False

        try:
            responses = self.client.streaming_recognize(
                requests=self._request_generator(),
                timeout=timeout_sec
            )
            for response in responses:
                # ---- 1) VADイベント処理 ----
                ev = getattr(response, "speech_event_type", 0)
                if ev:
                    BEGIN = cs.StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_BEGIN
                    END1  = cs.StreamingRecognizeResponse.SpeechEventType.END_OF_SINGLE_UTTERANCE
                    END2  = cs.StreamingRecognizeResponse.SpeechEventType.SPEECH_ACTIVITY_END

                    if ev == BEGIN:
                        saw_vad_begin = True

                    elif ev in (END1, END2):
                        # BEGINもテキストも無しでEND → 無視
                        if not saw_vad_begin and not saw_any_text:
                            continue
                        if not latest_text.strip():
                            continue

                        print("\n[VAD] speech end detected -> finishing")
                        self._stop_event.set()
                        try:
                            if self._q is not None:
                                self._q.put_nowait(None)
                        except Exception:
                            pass
                        if first_text_time is not None:
                            diff_ms = (time.perf_counter() - first_text_time) * 1000.0
                            print(f"[STT latency] first_char → VAD_end: {diff_ms:.1f} ms")
                        return latest_text.strip()
                    continue

                # ---- 2) 認識結果（interim / final） ----
                for result in response.results:
                    if not result.alternatives:
                        continue
                    alt = result.alternatives[0]
                    text = alt.transcript or ""

                    if text.strip():
                        latest_text = text
                        saw_any_text = True
                        if first_text_time is None:
                            first_text_time = time.perf_counter()

                    # 暫定結果をコンソールに上書き表示
                    sys.stdout.write("\r" + latest_text[:120]); sys.stdout.flush()

                    # フォールバック: is_final でも終了可能に
                    if getattr(result, "is_final", False) and latest_text.strip():
                        print()
                        print(latest_text)
                        if first_text_time is not None:
                            diff_ms = (time.perf_counter() - first_text_time) * 1000.0
                            print(f"[STT latency] first_char → is_final: {diff_ms:.1f} ms")
                        self._stop_event.set()
                        try:
                            if self._q is not None:
                                self._q.put_nowait(None)
                        except Exception:
                            pass
                        return latest_text.strip()

                # ---- 3) セッション安全装置 ----
                if time.time() - start > timeout_sec:
                    return ""
        except KeyboardInterrupt:
            print("\n音声認識を中断しました。")
            return ""
        finally:
            # ★ ここで close() は呼ばない：ホットスタンバイ
            self._pause_input(pause_stream=True)

    def warm_up(self, duration_sec: float = 0.05):
        """
        初回のオーバーヘッドを隠すプリウォーム。
        起動直後に一度呼ぶと 1ターン目も速くなる。
        """
        self._ensure_input_started()
        time.sleep(duration_sec)
        self._pause_input(pause_stream=True)


if __name__ == "__main__":
    # 簡易テスト: 2回連続で聞いてみる（2回目が速いはず）
    with SpeechToText(language="ja-JP", model="latest_short", location="asia-northeast1") as stt:
        stt.warm_up()
        for i in range(2):
            print(f"\n--- TURN {i+1} ---")
            text = stt.listen_once(timeout_sec=15.0)
            print("\n=== RESULT ===")
            print(text)
