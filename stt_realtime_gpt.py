import asyncio
import websockets
import pyaudio
import numpy as np
import base64
import json
import os
import re
import time
from voicevox import VoiceVoxTTS
from typing import Optional, TYPE_CHECKING
if TYPE_CHECKING:
    from function_led import LEDBlinker
    from function_motor import Motor

tts = VoiceVoxTTS(
    base_url="http://192.168.1.151:50021",
    speaker=89,
    max_len=80,
    queue_size=4,
)
tts.set_params(speedScale=1.0, pitchScale=0.0, intonationScale=1.0)

API_KEY = os.environ.get('OPENAI_API_KEY')
#わからない人は、上の行をコメントアウトして、下記のように直接API KEYを書き下してもよい
#API_KEY = "sk-xxxxx"

# WebSocket URLとヘッダー情報
WS_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime"
HEADERS = {
    "Authorization": "Bearer "+ API_KEY, 
    "OpenAI-Beta": "realtime=v1"
}



def load_config(config_path: str = "config.json") -> dict:
    """設定ファイル（config.json）を読み込む"""
    try:
        with open(config_path, 'r', encoding='utf-8') as file:
            config = json.load(file)
        return config
    except FileNotFoundError:
        print(f"設定ファイル {config_path} が見つかりません。デフォルト設定を使用します。")
        return get_default_config()
    except json.JSONDecodeError as e:
        print(f"設定ファイルの読み込みエラー: {e}。デフォルト設定を使用します。")
        return get_default_config()

def get_default_config() -> dict:
    """デフォルト設定を返す"""
    return {
        "system_content": "これはユーザーである{owner_name}とあなた（{your_name}）との会話です。{your_name}は片言で返します。セリフは短すぎず、長すぎずです。話を盛り上げようとします。また{your_name}は自分の名前を呼びがちです。けれど同じセリフで2回は自分の名前を言いません。（例）{your_name}、わかった！",
        "owner_name": "まつ",
        "your_name": "ハロ",
        "change_text": {
            "春": "ハロ"
        },
        "llm": "gpt-4o-mini",
        "voiceVoxTTS": {
            "base_url": "http://127.0.0.1:50021",
            "speaker": 89,
            "max_len": 80,
            "queue_size": 4,
            "speedScale": 1.0,
            "pitchScale": 0.0,
            "intonationScale": 1.0
        },
        "led":{
            "use_led": True,
            "led_pin": 17
        },
        "motor": {
            "use_motor": True,
            "pan_pin": 4,
            "tilt_pin": 17
        }
    }

config = load_config()
system_content = config["system_content"]
owner_name = config["owner_name"]
your_name = config["your_name"]
stt_type = config["stt"]
llm_model = config["llm"]
tts_config = config["voiceVoxTTS"]
change_name = config["change_text"]
isfiller = config["use_filler"]
use_led = config["led"]["use_led"]
led_pin = config["led"]["led_pin"]
use_motor = config["motor"]["use_motor"]
pan_pin = config["motor"]["pan_pin"]
tilt_pin = config["motor"]["tilt_pin"]

led: Optional["LEDBlinker"] = None
if use_led:
    try:
        from function_led import LEDBlinker  # 遅延インポート
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
 

# 音声を送信する非同期関数（VADで区切ってcommit→response.createを送る）
async def send_audio(websocket, stream, CHUNK, RATE, mic_enabled_event: asyncio.Event, awaiting_response: asyncio.Event):
    def is_voice(pcm16_bytes: bytes, threshold: float = 2000.0) -> bool:
        if not pcm16_bytes:
            return False
        data = np.frombuffer(pcm16_bytes, dtype=np.int16)
        if data.size == 0:
            return False
        rms = np.sqrt(np.mean(np.square(data.astype(np.float32))))
        return rms >= threshold
    def read_audio_block():
        """同期的に音声データを読み取る関数"""
        try:
            # マイク停止中は読み取らない
            if not stream.is_active():
                return None
            return stream.read(CHUNK, exception_on_overflow=False)
        except Exception as e:
            # ストリーム停止中の例外は無視
            msg = str(e)
            if mic_enabled_event.is_set() and "Stream closed" not in msg:
                print(f"音声読み取りエラー: {e}")
            return None

    print("マイクから音声を取得して送信中...")
    # VAD 状態管理（音声ターン検出）
    voice_started = False
    silence_ms_after_voice = 0.0
    speech_ms = 0.0
    chunk_ms = 1000.0 * CHUNK / RATE
    min_speech_ms = 1000.0  # 最低発話長（誤起動抑制）

    while True:
        # アシスタント再生中は送信停止
        await mic_enabled_event.wait()
        # 再開時に物理ストリームが止まっていたら起動
        try:
            if not stream.is_active():
                stream.start_stream()
                # ドライバ反映待ちのごく短い猶予
                await asyncio.sleep(0.01)
        except Exception:
            # 起動失敗時は少し待って次ループ
            await asyncio.sleep(0.02)
            continue
        # マイクから音声を取得
        audio_data = await asyncio.get_event_loop().run_in_executor(None, read_audio_block)
        if audio_data is None:
            # 停止中や読み取り失敗時は待機
            await asyncio.sleep(0.01)
            continue  # 読み取りに失敗した場合はスキップ
        
        # 無音（非音声）は送らない（ただしVADのターン検出には使用）
        voiced_now = is_voice(audio_data)
        if not voiced_now:
            # 完全無音は送信を省略
            await asyncio.sleep(0)
            # VAD用にサイレンスを加算
            if voice_started:
                silence_ms_after_voice += chunk_ms
                # 区切り条件: 無音>=800ms & 最低発話長 & 未応答
                if (
                    silence_ms_after_voice >= 800.0
                    and speech_ms >= min_speech_ms
                    and not awaiting_response.is_set()
                ):
                    # 重複防止のため先に待機フラグ
                    awaiting_response.set()
                    # 1ターンの音声を確定
                    await websocket.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    # 応答生成をリクエスト
                    await websocket.send(json.dumps({"type": "response.create"}))
                    # アシスタントが話す間はマイク停止
                    mic_enabled_event.clear()
                    try:
                        if stream.is_active():
                            stream.stop_stream()
                    except Exception:
                        pass
                    # 次ターンに備えてリセット
                    voice_started = False
                    silence_ms_after_voice = 0.0
                    speech_ms = 0.0
            else:
                # まだ話し始めていない無音
                pass
            continue
        
        # PCM16データをBase64にエンコード
        base64_audio = base64.b64encode(audio_data).decode("utf-8")

        audio_event = {
            "type": "input_audio_buffer.append",
            "audio": base64_audio
        }

        # WebSocketで音声データを送信
        await websocket.send(json.dumps(audio_event))

        # ---- VAD の状態遷移 ----
        if not voice_started:
            # 話し始め検出
            voice_started = True
            silence_ms_after_voice = 0.0
            speech_ms = 0.0
        else:
            # 発話継続中
            silence_ms_after_voice = 0.0
            speech_ms += chunk_ms
        """
        # 送信直後にマイクを一時停止
        mic_enabled_event.clear()
        try:
            if stream.is_active():
                stream.stop_stream()
        except Exception:
            pass
        """
        
        

        await asyncio.sleep(0)

# サーバーからの応答を受信して処理する非同期関数（音声再生なし）
async def receive_audio(websocket, mic_enabled_event: asyncio.Event, awaiting_response: asyncio.Event):
    _SENT_END = re.compile(r"[。．！？!?]\s*$")  # 文末検出（日本語/記号）
    buf = ""
    print("assistant: ", end="", flush=True)
    while True:
        # サーバーからの応答を受信
        response = await websocket.recv()
        response_data = json.loads(response)

        # サーバーからの応答をリアルタイム（ストリーム）で表示
        if response_data.get("type") == "response.audio_transcript.delta":
            stream_data = response_data["delta"].strip()
            print(stream_data, end="", flush=True)
            buf += stream_data
            if _SENT_END.search(buf) or len(buf) >= tts.max_len:
                s = buf.strip()
                if s:
                    tts.stream_speak(s, led, use_led, motor, use_motor)
                    buf = ""

        elif response_data.get("type") == "response.completed":
            # 応答完了: ローカル/サーバ側バッファをクリアし、マイク再開（完了イベントに一本化）
            buf = ""
            await websocket.send(json.dumps({"type": "input_audio_buffer.clear"}))
            awaiting_response.clear()
            print("マイク再開: response.completed")
            mic_enabled_event.set()

        if "type" in response_data and response_data["type"] == "response.audio_transcript.done":
            await websocket.send(json.dumps({"type": "input_audio_buffer.clear"}))
            print("マイク再開: response.audio_transcript.done")
            awaiting_response.clear()
            mic_enabled_event.set()
            led.stop_blink()
                

        # 出力完了イベント（ここでは何もしない。completedでのみクリア/再開）
        if response_data.get("type") in ("response.audio.done", "response.output_text.done"):
            pass

# マイクからの音声を取得し、WebSocketで送信しながらサーバーからの音声応答を再生する非同期関数
async def stream_audio_and_receive_response():
    

    # WebSocketに接続
    async with websockets.connect(WS_URL, additional_headers=HEADERS) as websocket:
        print("WebSocketに接続しました。")

        # セッション設定（最初は応答を生成しない & サーバの自動ターン検出を無効化）
        session_update = {
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "instructions": "Please make sure to speak in only one sentence; more than one sentence is not allowed.",
                "voice": "cedar",
                "turn_detection": {"type": "none"}
            }
        }
        await websocket.send(json.dumps(session_update))
        print("セッション設定を送信しました。")
        
        # PyAudioの設定
        CHUNK = 2048          # マイクからの入力データのチャンクサイズ
        FORMAT = pyaudio.paInt16  # PCM16形式
        CHANNELS = 1          # モノラル
        RATE = 24000          # サンプリングレート（24kHz）

        # PyAudioインスタンス
        p = pyaudio.PyAudio()

        # マイクストリームの初期化
        stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)

        print("マイク入力を開始...")

        # マイクON/OFF制御（初期はON）と応答待機フラグ
        mic_enabled_event = asyncio.Event()
        mic_enabled_event.set()
        awaiting_response = asyncio.Event()

        try:
            # 音声送信タスクと応答受信タスクを非同期で並行実行（音声再生なし）
            send_task = asyncio.create_task(send_audio(websocket, stream, CHUNK, RATE, mic_enabled_event, awaiting_response))
            receive_task = asyncio.create_task(receive_audio(websocket, mic_enabled_event, awaiting_response))

            # タスクが終了するまで待機
            await asyncio.gather(send_task, receive_task)

        except KeyboardInterrupt:
            # キーボードの割り込みで終了
            print("終了します...")
        finally:
            # ストリームを閉じる
            if stream.is_active():
                stream.stop_stream()
            stream.close()
            p.terminate()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(stream_audio_and_receive_response())
