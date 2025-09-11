import asyncio
import websockets
import pyaudio
import numpy as np
import webrtcvad
import base64
import json
import os
import re
import time
from typing import Optional, TYPE_CHECKING

from voicevox import VoiceVoxTTS
from corr_gate import CorrelationGate

if TYPE_CHECKING:
    from function_led import LEDBlinker
    from function_motor import Motor


# ===== OpenAI Realtime 接続設定 =====
API_KEY = os.environ.get("OPENAI_API_KEY")
# 必要に応じて直書きも可
# API_KEY = "sk-xxxxx"

WS_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "OpenAI-Beta": "realtime=v1",
}


# ===== 設定読み込み =====
def load_config(config_path: str = "config.json") -> dict:
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"設定ファイル {config_path} が見つかりません。デフォルト設定を使用します。")
        return get_default_config()
    except json.JSONDecodeError as e:
        print(f"設定ファイルの読み込みエラー: {e}。デフォルト設定を使用します。")
        return get_default_config()


def get_default_config() -> dict:
    return {
        "owner_name": "まつ",
        "your_name": "ハロ",
        "change_text": {"春": "ハロ"},
        "llm": "gpt-4o-mini",
        "voiceVoxTTS": {
            "base_url": "http://127.0.0.1:50021",
            "speaker": 89,
            "max_len": 80,
            "queue_size": 4,
            "speedScale": 1.0,
            "pitchScale": 0.0,
            "intonationScale": 1.0,
        },
        "led": {"use_led": True, "led_pin": 27},
        "motor": {"use_motor": True, "pan_pin": 4, "tilt_pin": 25},
        "vad": {
            "samplereate": 16000,
            "frame_duration_ms": 20,
            "min_consecutive_speech_frames": 12,
            "corr_threshold": 0.60,
            "max_lag_ms": 95,
        },
    }


def load_system_prompt(system_prompt_path: str = "system_prompt.md") -> str:
    with open(system_prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def replace_placeholders(text: str, owner_name: str, your_name: str) -> str:
    return text.replace("{owner_name}", owner_name).replace("{your_name}", your_name)


# ===== 設定/デバイス初期化 =====
config = load_config()
owner_name: str = config["owner_name"]
your_name: str = config["your_name"]
tts_config: dict = config["voiceVoxTTS"]
use_led: bool = config["led"]["use_led"]
led_pin: int = config["led"]["led_pin"]
use_motor: bool = config["motor"]["use_motor"]
pan_pin: int = config["motor"]["pan_pin"]
tilt_pin: int = config["motor"]["tilt_pin"]

system_content_template = load_system_prompt()
instructions = replace_placeholders(system_content_template, owner_name, your_name)
# 日本語強制の追記
instructions_ja = instructions + "\n\n重要: 必ず日本語で返答してください。英語や他言語は使用しないでください。"

tts = VoiceVoxTTS(
    base_url=tts_config["base_url"],
    speaker=tts_config.get("speaker", 89),
    max_len=tts_config.get("max_len", 80),
    queue_size=tts_config.get("queue_size", 4),
)
tts.set_params(
    speedScale=tts_config.get("speedScale", 1.0),
    pitchScale=tts_config.get("pitchScale", 0.0),
    intonationScale=tts_config.get("intonationScale", 1.0),
)

led: Optional["LEDBlinker"] = None
if use_led:
    try:
        from function_led import LEDBlinker

        led = LEDBlinker(led_pin)
    except Exception as e:
        print(f"LED機能を無効化します: {e}")
        use_led = False
        led = None

motor: Optional["Motor"] = None
if use_motor:
    try:
        from function_motor import Motor

        motor = Motor(pan_pin, tilt_pin)
    except Exception as e:
        print(f"モーター機能を無効化します: {e}")
        use_motor = False
        motor = None

# 相関ゲート（TTS由来の音を抑制する参照用）
vad_cfg = config.get("vad", {})
corr_gate = CorrelationGate(
    sample_rate=vad_cfg.get("samplereate", 16000),
    frame_ms=vad_cfg.get("frame_duration_ms", 20),
    buffer_sec=1.0,
    corr_threshold=vad_cfg.get("corr_threshold", 0.60),
    max_lag_ms=vad_cfg.get("max_lag_ms", 95),
)


# ===== 送受信ループ =====
async def send_audio(websocket, stream, CHUNK, RATE, awaiting_response: asyncio.Event):
    # webrtcvad の設定
    vad_cfg = config.get("vad", {})
    vad_aggr = int(vad_cfg.get("aggressiveness", 3))
    vad_frame_ms = int(vad_cfg.get("frame_duration_ms", 20))
    if vad_frame_ms not in (10, 20, 30):
        vad_frame_ms = 20
    vad = webrtcvad.Vad(vad_aggr)

    def read_audio_block():
        try:
            if not stream.is_active():
                return None
            return stream.read(CHUNK, exception_on_overflow=False)
        except Exception as e:
            if "Stream closed" not in str(e):
                print(f"音声読み取りエラー: {e}")
            return None

    def _resample_int16(pcm: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
        if src_rate == dst_rate:
            return pcm
        ratio = float(dst_rate) / float(src_rate)
        x_old = np.arange(len(pcm))
        x_new = np.arange(0, len(pcm), 1.0 / ratio)
        return np.interp(x_new, x_old, pcm.astype(np.float32)).astype(np.int16)

    def is_speech_webrtc(frame_16k: np.ndarray) -> bool:
        # webrtcvad は 10/20/30ms のフレーム長のみ対応
        samples_per_frame = int(16000 * vad_frame_ms / 1000)
        if samples_per_frame <= 0:
            return False
        total = len(frame_16k)
        # チャンク内のサブフレームのどれかが有声なら True
        for start in range(0, total - samples_per_frame + 1, samples_per_frame):
            sub = frame_16k[start:start + samples_per_frame]
            try:
                if vad.is_speech(sub.tobytes(), 16000):
                    return True
            except Exception:
                continue
        return False

    print("マイクから音声を取得して送信中...")

    voice_started = False
    silence_ms_after_voice = 0.0
    speech_ms = 0.0
    chunk_ms = 1000.0 * CHUNK / RATE
    # origin準拠寄り
    min_speech_ms = float(config.get("vad", {}).get("min_speech_ms", 250.0))
    end_silence_ms = float(config.get("vad", {}).get("end_silence_ms", 800.0))
    force_commit_ms = float(config.get("vad", {}).get("force_commit_ms", 8000.0))
    voiced_accum_ms = 0.0

    while True:
        audio_data = await asyncio.get_event_loop().run_in_executor(None, read_audio_block)
        if audio_data is None:
            await asyncio.sleep(0.01)
            continue

        # corr_gate によるTTSエコー判定（16k基準）
        try:
            frame_int16 = np.frombuffer(audio_data, dtype=np.int16)
            frame_16k = _resample_int16(frame_int16, RATE, 16000)
            tts_like = bool(corr_gate.is_tts_like(frame_16k))
        except Exception:
            tts_like = False

        # TTS類似は送らず、VAD上も無音扱い（webrtcvadで判定）
        voiced_now = (not tts_like) and is_speech_webrtc(frame_16k)
        if not voiced_now:
            await asyncio.sleep(0)
            if voice_started:
                silence_ms_after_voice += chunk_ms
                if (
                    silence_ms_after_voice >= end_silence_ms
                    and speech_ms >= min_speech_ms
                    and not awaiting_response.is_set()
                ):
                    awaiting_response.set()
                    await websocket.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    await websocket.send(json.dumps({
                        "type": "response.create",
                        "response": {"modalities": ["text"], "instructions": instructions_ja}
                    }))
                    print(f"[VAD] commit → response.create (speech_ms={speech_ms:.0f}, silence_ms={silence_ms_after_voice:.0f})")
                    voice_started = False
                    silence_ms_after_voice = 0.0
                    speech_ms = 0.0
                    voiced_accum_ms = 0.0
            continue

        # TTS類似でないフレームのみ送信
        if not tts_like:
            base64_audio = base64.b64encode(audio_data).decode("utf-8")
            await websocket.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64_audio}))

        if not voice_started:
            voice_started = True
            silence_ms_after_voice = 0.0
            speech_ms = 0.0
            print("[VAD] voice start")
        else:
            silence_ms_after_voice = 0.0
            speech_ms += chunk_ms
            voiced_accum_ms += chunk_ms

        # 長すぎる発話は強制的にコミット（無音が取れない環境対策）
        if (
            voice_started
            and not awaiting_response.is_set()
            and voiced_accum_ms >= force_commit_ms
        ):
            awaiting_response.set()
            await websocket.send(json.dumps({"type": "input_audio_buffer.commit"}))
            await websocket.send(json.dumps({
                "type": "response.create",
                "response": {"modalities": ["text"], "instructions": instructions_ja}
            }))
            print(f"[VAD] force commit → response.create (voiced_accum_ms={voiced_accum_ms:.0f})")
            voice_started = False
            silence_ms_after_voice = 0.0
            speech_ms = 0.0
            voiced_accum_ms = 0.0

        await asyncio.sleep(0)


async def receive_audio(websocket, awaiting_response: asyncio.Event):
    _SENT_END = re.compile(r"[。．！？!?]\s*$")
    buf = ""
    print("assistant: ", end="", flush=True)
    while True:
        response = await websocket.recv()
        data = json.loads(response)
        etype = data.get("type")

        # --- ユーザー側の文字起こし（3系統をサポート）---
        # 1) 旧/一部実装
        if etype == "input_audio_transcription.delta":
            txt = data.get("delta", "")
            if txt:
                print(f"\nuser中間: {txt}")
            continue
        elif etype == "input_audio_transcription.completed":
            # ← 旧系は 'transcription' フィールド
            full = data.get("transcription", "")
            if full:
                print(f"\nuser(確定): {full}")
            continue

        # 2) 公式ドキュメント系（会話アイテム）
        elif etype == "conversation.item.audio_transcription.delta":
            txt = data.get("delta", "")
            if txt:
                print(f"\nuser: {txt}")
            continue
        elif etype == "conversation.item.audio_transcription.completed":
            # ← こちらは 'text' だったり 'transcription' の実装もある
            full = data.get("text") or data.get("transcription") or ""
            if full:
                print(f"\nuser(final): {full}")
            continue

        # 3) ★今回あなたのログで来ている系（input_ が付く）
        elif etype == "conversation.item.input_audio_transcription.delta":
            txt = data.get("delta", "")
            if txt:
                print(f"\nuser: {txt}")
            continue
        elif etype == "conversation.item.input_audio_transcription.completed":
            # ★ この系は completed のフィールド名が 'transcript'
            full = data.get("transcript", "")
            if full:
                print(f"\nuser(final): {full}")
            continue

        # テキスト出力（新APIのイベント名: response.text.delta）
        if etype == "response.text.delta":
            delta = data.get("delta", "").strip()
            if not delta:
                continue
            print(delta, end="", flush=True)
            buf += delta
            if _SENT_END.search(buf) or len(buf) >= tts.max_len:
                s = buf.strip()
                if s:
                    speak_text = s
                    # 応答がJSONなら message を抽出
                    if s.startswith("{"):
                        try:
                            j = json.loads(s)
                            if isinstance(j, dict) and "message" in j:
                                speak_text = str(j.get("message", ""))
                        except Exception:
                            pass
                    if speak_text:
                        tts.speak(speak_text, led, use_led, motor, use_motor, corr_gate=corr_gate)
                    buf = ""

        # 文字ストリーム（サーバが音声を生成しつつ、その字幕としてテキストが来る場合）
        elif etype == "response.audio_transcript.delta":
            delta = data.get("delta", "").strip()
            if not delta:
                continue
            print(delta, end="", flush=True)
            buf += delta
            if _SENT_END.search(buf) or len(buf) >= tts.max_len:
                s = buf.strip()
                if s:
                    tts.speak(s, led, use_led, motor, use_motor, corr_gate=corr_gate)
                    buf = ""
        # オーディオ断片（必要なら処理を追加可能）
        elif etype == "response.audio.delta":
            pass

        elif etype == "response.completed":
            buf = ""
            await websocket.send(json.dumps({"type": "input_audio_buffer.clear"}))
            awaiting_response.clear()
            print("[recv] response.completed → mic resume")
            try:
                if use_led and led:
                    led.stop_blink()
            except Exception:
                pass

        # テキスト完了（新API）
        elif etype == "response.text.done":
            s = buf.strip()
            if s:
                speak_text = s
                try:
                    j = json.loads(s)
                    if isinstance(j, dict) and "message" in j:
                        speak_text = str(j.get("message", ""))
                except Exception:
                    pass
                if speak_text:
                    tts.speak(speak_text, led, use_led, motor, use_motor, corr_gate=corr_gate)
            buf = ""
            await websocket.send(json.dumps({"type": "input_audio_buffer.clear"}))
            awaiting_response.clear()
            print("[recv] response.text.done → mic resume")
            try:
                if use_led and led:
                    led.stop_blink()
            except Exception:
                pass

        # 応答全体の完了
        elif etype == "response.done":
            buf = ""
            await websocket.send(json.dumps({"type": "input_audio_buffer.clear"}))
            awaiting_response.clear()
            print("[recv] response.done → mic resume")
            try:
                if use_led and led:
                    led.stop_blink()
            except Exception:
                pass

        elif etype == "response.audio_transcript.done":
            await websocket.send(json.dumps({"type": "input_audio_buffer.clear"}))
            awaiting_response.clear()
            mic_enabled_event.set()
            try:
                if use_led and led:
                    led.stop_blink()
            except Exception:
                pass

        elif etype == "error":
            print("<< エラー:", data)
        else:
            # デバッグ用: 予期しないタイプも観測
            t = data.get("type")
            if t:
                print(f"[recv] {t}")


async def stream_audio_and_receive_response():
    if not API_KEY:
        raise RuntimeError("環境変数 OPENAI_API_KEY が設定されていません。")

    async with websockets.connect(WS_URL, additional_headers=HEADERS) as websocket:
        print("WebSocketに接続しました。")

        # セッション設定（textのみ出力、日本語固定、サーバVADは応答自動生成を無効化、入力側の文字起こし有効化）
        session_update = {
            "type": "session.update",
            "session": {
                "modalities": ["text"],
                "instructions": instructions_ja,
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "silence_duration_ms": 800,
                    "create_response": False,
                    "interrupt_response": True
                },
                "input_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "gpt-4o-mini-transcribe",
                    "language": "ja"
                }
            }
        }
        await websocket.send(json.dumps(session_update))
        print("セッション設定を送信しました。")

        # 応答を確認
        while True:
            msg = await websocket.recv()
            data = json.loads(msg)
            etype = data.get("type")
            if etype == "session.updated":
                print("<< session.updated を受信しました")
                print(json.dumps(data, indent=2, ensure_ascii=False))
                break
            elif etype == "error":
                print("<< エラー:", data)
                break

        # PyAudio 設定（OpenAI Realtime は 24kHz でも動作）
        CHUNK = 2048
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 16000

        p = pyaudio.PyAudio()
        stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)

        print("マイク入力を開始...")

        awaiting_response = asyncio.Event()

        try:
            send_task = asyncio.create_task(
                send_audio(websocket, stream, CHUNK, RATE, awaiting_response)
            )
            recv_task = asyncio.create_task(
                receive_audio(websocket, awaiting_response)
            )
            await asyncio.gather(send_task, recv_task)
        except KeyboardInterrupt:
            print("終了します...")
        finally:
            try:
                if stream.is_active():
                    stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
            p.terminate()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(stream_audio_and_receive_response())


