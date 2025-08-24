# stt.py
# Google Cloud Speech-to-Text v2 を利用し、
# WebRTC VAD (Voice Activity Detection) の「発話終了」イベントで
# 音声認識を終了してテキストを返す実装。
# 録音スレッド・PyAudio・gRPC クライアントを安全に扱えるよう工夫。

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
        self.RATE = 16000   # サンプルレート (Google推奨: 16kHz)
        self.CHANNELS = 1   # モノラル
        self.CHUNK_MS = 50  # マイクから読み取る単位(ms)
        self.FRAMES_PER_BUFFER = self.RATE * self.CHUNK_MS // 1000

        # 内部管理フラグ/リソース
        self._stop_event = threading.Event()
        self._pa: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._producer: Optional[threading.Thread] = None
        self._q: Optional["queue.Queue[bytes|None]"] = None

        # GCP プロジェクトとクライアント
        self.project_id = self._get_project_id()
        self.client = self._make_client()
        self._closed = False

    # ---- lifecycle ----
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        """
        停止処理: 安全にマイク・スレッド・クライアントを解放する。
        手順: 停止フラグ → read解除 → キュー解除 → スレッドjoin → デバイス解放
        """
        if self._closed:
            return
        self._stop_event.set()  # 停止フラグ

        # マイクの read() を解除
        try:
            if self._stream is not None and self._stream.is_active():
                try:
                    self._stream.stop_stream()
                except Exception:
                    pass
        except Exception:
            pass

        # キュー解除 (generator側の get() を抜けさせる)
        try:
            if self._q is not None:
                self._q.put_nowait(None)
        except Exception:
            pass

        # 録音スレッド終了待ち
        if self._producer and self._producer.is_alive():
            self._producer.join(timeout=2.0)

        # デバイス解放
        try:
            if self._stream is not None:
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
            self._producer = None
            self._q = None
            # gRPCクライアントは毎回作り直せるので閉じてOK
            if hasattr(self.client, "close"):
                try:
                    self.client.close()
                except Exception:
                    pass
            self._closed = True

    # ---- GCP ----
    def _get_project_id(self) -> str:
        """ADC からプロジェクトIDを取得（環境変数優先）"""
        pid = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT")
        if pid:
            return pid
        _, project_id = google.auth.default()
        if not project_id:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT を設定するか、ADC を見直してください。")
        return project_id

    def _make_client(self) -> SpeechClient:
        """ロケーションに応じたエンドポイントで SpeechClient を生成"""
        endpoint = f"{self.LOCATION}-speech.googleapis.com" if self.LOCATION != "global" else "speech.googleapis.com"
        return SpeechClient(client_options=ClientOptions(api_endpoint=endpoint))

    # ---- audio ----
    def _start_input(self):
        """PyAudioでマイクを開き、録音スレッドを開始"""
        self._stop_event.clear()
        self._pa = pyaudio.PyAudio()
        try:
            info = self._pa.get_default_input_device_info()
        except Exception as e:
            self._pa.terminate(); self._pa = None
            raise RuntimeError("既定の入力デバイスが見つかりません。") from e

        idx = info["index"]
        name = info.get("name", "unknown")
        print(f"Using default mic: index={idx}, name='{name}', capture_rate={self.RATE}")

        # マイク入力を開始
        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self.CHANNELS,
            rate=self.RATE,
            input=True,
            input_device_index=idx,
            frames_per_buffer=self.FRAMES_PER_BUFFER,
        )

        self._q = queue.Queue()

        def fill_buffer():
            """マイクから読み取った音声をキューに積むスレッド"""
            try:
                while not self._stop_event.is_set():
                    data = self._stream.read(self.FRAMES_PER_BUFFER, exception_on_overflow=False)
                    self._q.put(data)
            except Exception:
                # 終了処理時の read エラーは無視
                pass
            finally:
                try:
                    self._q.put_nowait(None)  # キュー終端
                except Exception:
                    pass

        # joinで確実に止めたいので daemon=False
        self._producer = threading.Thread(target=fill_buffer, daemon=False)
        self._producer.start()

    def _mic_stream(self):
        """generator: マイク入力を逐次返す。終了時は None が流れる。"""
        self._start_input()
        try:
            while not self._stop_event.is_set():
                chunk = self._q.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            pass  # 実リソース解放は close() に委任

    # ---- gRPC ----
    def _request_generator(self):
        """Google Speech-to-Text API へ送る StreamingRecognizeRequest の generator"""
        recognizer_path = f"projects/{self.project_id}/locations/{self.LOCATION}/recognizers/_"

        # 音声デコード設定
        decoding = cs.ExplicitDecodingConfig(
            encoding=cs.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=self.RATE,
            audio_channel_count=self.CHANNELS,
        )
        recognition_config = cs.RecognitionConfig(
            explicit_decoding_config=decoding,
            language_codes=[self.LANGUAGE],
            model=self.MODEL,
            features=cs.RecognitionFeatures(enable_automatic_punctuation=True),
        )

        # ★ WebRTC VAD を有効化
        # speech_start_timeout: 発話開始を待つ最大時間
        # speech_end_timeout  : 無音が続いた時にサーバが終了と判断する猶予
        streaming_features = cs.StreamingRecognitionFeatures(
            enable_voice_activity_events=True,
            voice_activity_timeout=cs.StreamingRecognitionFeatures.VoiceActivityTimeout(
                speech_start_timeout=duration_pb2.Duration(seconds=5, nanos=0),
                speech_end_timeout=duration_pb2.Duration(seconds=0, nanos=800_000_000),
            ),
        )

        streaming_config = cs.StreamingRecognitionConfig(
            config=recognition_config,
            streaming_features=streaming_features,
        )

        # 最初に config を送る
        yield cs.StreamingRecognizeRequest(
            recognizer=recognizer_path,
            streaming_config=streaming_config,
        )
        # 続いて音声チャンクを送り続ける
        for chunk in self._mic_stream():
            if self._stop_event.is_set():
                break
            yield cs.StreamingRecognizeRequest(audio=chunk)

    # ---- public ----
    def listen_once(self, timeout_sec: float = 15.0) -> str:
        """
        1回の発話を認識してテキストを返す。
        - is_final を待たず、WebRTC VAD の「発話終了」で返す
        - ただし「BEGINもテキストも無しでEND」は無視
        - タイムアウト時は空文字を返す
        """
        print(f"[Listening] language={self.LANGUAGE}, model={self.MODEL}, location={self.LOCATION}  (発話してください)")
        start = time.time()
        first_text_time = None
        latest_text = ""
        saw_vad_begin = False   # VAD開始を検出したか
        saw_any_text = False    # 一度でも文字を受け取ったか

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
                        # BEGINもテキストも無い END → 無視
                        if not saw_vad_begin and not saw_any_text:
                            continue
                        if not latest_text.strip():
                            continue

                        # 発話終了を検出したので返す
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

                    continue  # 他イベントは無視

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

                    # ★ フォールバック: is_final が来た場合も終了できるようにする
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
            self.close()


if __name__ == "__main__":
    # 単体テスト用: 1回だけ聞いて出力
    with SpeechToText(language="ja-JP", model="latest_short", location="asia-northeast1") as stt:
        text = stt.listen_once(timeout_sec=15.0)
        print("\n=== RESULT ===")
        print(text)
