# stt.py  (安全版 / 2周目以降も確実に再開)
import os, sys, queue, threading, time
from typing import Optional
import pyaudio
import google.auth
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech as cs

class SpeechToText:
    def __init__(self, language="ja-JP", model="latest_short", location="asia-northeast1"):
        self.LANGUAGE = language
        self.MODEL = model
        self.LOCATION = location
        self.RATE = 16000
        self.CHANNELS = 1
        self.CHUNK_MS = 50
        self.FRAMES_PER_BUFFER = self.RATE * self.CHUNK_MS // 1000

        self._stop_event = threading.Event()
        self._pa: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._producer: Optional[threading.Thread] = None
        self._q: Optional["queue.Queue[bytes|None]"] = None

        self.project_id = self._get_project_id()
        self.client = self._make_client()
        self._closed = False

    # ---- lifecycle ----
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        """停止→read解除→join→デバイス解放 の順で確実に終了"""
        if self._closed:
            return
        # 1) 停止フラグ
        self._stop_event.set()

        # 2) read() を解除（ここが肝）
        try:
            if self._stream is not None and self._stream.is_active():
                try: self._stream.stop_stream()
                except Exception: pass
        except Exception:
            pass

        # 3) キュー待ちを起こす（ジェネレータ側が q.get() で待っていても抜けられる）
        try:
            if self._q is not None:
                self._q.put_nowait(None)
        except Exception:
            pass

        # 4) 録音スレッド終了を待つ
        if self._producer and self._producer.is_alive():
            self._producer.join(timeout=2.0)

        # 5) デバイスを閉じる
        try:
            if self._stream is not None:
                try: self._stream.close()
                except Exception: pass
            if self._pa is not None:
                try: self._pa.terminate()
                except Exception: pass
        finally:
            self._stream = None
            self._pa = None
            self._producer = None
            self._q = None
            # gRPC クライアントは都度作り直すので閉じてOK
            if hasattr(self.client, "close"):
                try: self.client.close()
                except Exception: pass
            self._closed = True

    # ---- GCP ----
    def _get_project_id(self) -> str:
        pid = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT")
        if pid: return pid
        _, project_id = google.auth.default()
        if not project_id:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT を設定するか、ADC を見直してください。")
        return project_id

    def _make_client(self) -> SpeechClient:
        endpoint = f"{self.LOCATION}-speech.googleapis.com" if self.LOCATION != "global" else "speech.googleapis.com"
        return SpeechClient(client_options=ClientOptions(api_endpoint=endpoint))

    # ---- audio ----
    def _start_input(self):
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
            try:
                while not self._stop_event.is_set():
                    data = self._stream.read(self.FRAMES_PER_BUFFER, exception_on_overflow=False)
                    self._q.put(data)
            except Exception:
                # 終了時・デバイス解放時の read 例外は無視
                pass
            finally:
                # 終端通知
                try: self._q.put_nowait(None)
                except Exception: pass

        # デーモンにしない（joinで確実に止める）
        self._producer = threading.Thread(target=fill_buffer, daemon=False)
        self._producer.start()

    def _mic_stream(self):
        self._start_input()
        try:
            while not self._stop_event.is_set():
                chunk = self._q.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            # 実際の解放は close() が担当
            pass

    # ---- gRPC ----
    def _request_generator(self):
        recognizer_path = f"projects/{self.project_id}/locations/{self.LOCATION}/recognizers/_"

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
        streaming_config = cs.StreamingRecognitionConfig(config=recognition_config)

        yield cs.StreamingRecognizeRequest(recognizer=recognizer_path, streaming_config=streaming_config)
        for chunk in self._mic_stream():
            if self._stop_event.is_set():
                break
            yield cs.StreamingRecognizeRequest(audio=chunk)

    # ---- public ----
    def listen_once(self, timeout_sec: float = 15.0) -> str:
        """
        最初の確定結果を返して終了（latest_short向け）。
        timeout を超えたら空文字で返す。
        """
        print(f"[Listening] language={self.LANGUAGE}, model={self.MODEL}, location={self.LOCATION}  (発話してください)")
        start = time.time()
        try:
            responses = self.client.streaming_recognize(
                requests=self._request_generator(),
                timeout=timeout_sec  # 応答がまったく来ない時の保険
            )
            for response in responses:
                for result in response.results:
                    if not result.alternatives:
                        continue
                    alt = result.alternatives[0]
                    text = alt.transcript
                    if getattr(result, "is_final", False):
                        print(text)
                        # 先に停止して、read解除→join→close の順へ
                        self._stop_event.set()
                        # 起きていない待ちを起こす
                        try:
                            if self._q is not None:
                                self._q.put_nowait(None)
                        except Exception:
                            pass
                        return text
                    else:
                        sys.stdout.write("\r" + text[:120]); sys.stdout.flush()

                    # 任意の安全装置（長すぎるセッションは終了）
                    if time.time() - start > timeout_sec:
                        return ""
        finally:
            self.close()
