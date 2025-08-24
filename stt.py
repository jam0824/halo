# stt_simple.py
# Google Cloud Speech-to-Text v2 / 超シンプル版（Python, 双方向ストリーミング）
# 事前:
#   pip install google-cloud-speech pyaudio
#   gcloud auth application-default login
#   環境変数 GOOGLE_CLOUD_PROJECT=<あなたのプロジェクトID> を設定（または ADC から取得されます）

import os
import sys
import queue
import threading

import pyaudio
import google.auth
from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech as cs

# ===== 設定（必要ならここだけ書き換え） =====
LANGUAGE = "ja-JP"          # 認識言語
MODEL    = "latest_short"    # "latest_short" も可
LOCATION = "asia-northeast1"  # 例: "global", "us-central1", "asia-northeast1"
RATE     = 16000            # 16kHz 推奨
CHANNELS = 1
CHUNK_MS = 50              # 100msごとに送信（十分小さい）
FRAMES_PER_BUFFER = RATE * CHUNK_MS // 1000

# ---------------------------------------------

def get_project_id() -> str:
    pid = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT")
    if pid:
        return pid
    creds, project_id = google.auth.default()
    if not project_id:
        raise RuntimeError(
            "GCP プロジェクトIDが特定できません。"
            "環境変数 GOOGLE_CLOUD_PROJECT を設定するか、ADCの設定を見直してください。"
        )
    return project_id

def make_client() -> SpeechClient:
    endpoint = f"{LOCATION}-speech.googleapis.com" if LOCATION != "global" else "speech.googleapis.com"
    return SpeechClient(client_options=ClientOptions(api_endpoint=endpoint))

def default_mic_stream():
    """既定の入力デバイスから音声を取り出して yield"""
    pa = pyaudio.PyAudio()

    # 既定の入力デバイス情報
    info = pa.get_default_input_device_info()
    idx = info["index"]
    name = info.get("name", "unknown")
    default_rate = int(info.get("defaultSampleRate", 0))
    inputs = int(info.get("maxInputChannels", 0))
    print(f"Using default mic: index={idx}, name='{name}', inputs={inputs}, default_rate={default_rate}, capture_rate={RATE}")

    stream = pa.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        input_device_index=idx,
        frames_per_buffer=FRAMES_PER_BUFFER,
    )

    q: "queue.Queue[bytes|None]" = queue.Queue()

    def fill_buffer():
        try:
            while True:
                data = stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False)
                q.put(data)
        except Exception:
            q.put(None)

    threading.Thread(target=fill_buffer, daemon=True).start()

    try:
        while True:
            chunk = q.get()
            if chunk is None:
                break
            yield chunk
    finally:
        try:
            stream.stop_stream(); stream.close()
        except Exception:
            pass
        pa.terminate()

def request_generator(project_id: str):
    """最初に設定、以降は音声チャンクだけ送る"""
    recognizer_path = f"projects/{project_id}/locations/{LOCATION}/recognizers/_"

    # 明示デコード（LINEAR16/16kHz/mono）
    decoding = cs.ExplicitDecodingConfig(
        encoding=cs.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=RATE,
        audio_channel_count=CHANNELS,
    )

    recognition_config = cs.RecognitionConfig(
        explicit_decoding_config=decoding,
        language_codes=[LANGUAGE],
        model=MODEL,
        features=cs.RecognitionFeatures(
            enable_automatic_punctuation=True,
        ),
    )
    streaming_config = cs.StreamingRecognitionConfig(config=recognition_config)

    # 1発目: 設定
    yield cs.StreamingRecognizeRequest(
        recognizer=recognizer_path,
        streaming_config=streaming_config,
    )

    # 以降: 音声
    for chunk in default_mic_stream():
        yield cs.StreamingRecognizeRequest(audio=chunk)

def main():
    project_id = get_project_id()
    client = make_client()

    print(f"[Listening] language={LANGUAGE}, model={MODEL}, location={LOCATION}  (Ctrl+C to stop)\n")

    try:
        responses = client.streaming_recognize(requests=request_generator(project_id))
        for response in responses:
            for result in response.results:
                if not result.alternatives:
                    continue
                alt = result.alternatives[0]
                text = alt.transcript
                if getattr(result, "is_final", False):
                    # 確定時は改行して確定
                    print(text)
                else:
                    # 暫定は同じ行で上書き
                    sys.stdout.write("\r" + text[:120])
                    sys.stdout.flush()
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as e:
        print("\n[Error]", repr(e))
        raise

if __name__ == "__main__":
    main()
