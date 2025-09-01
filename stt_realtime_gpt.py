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

 

# 音声を送信する非同期関数（VADで区切ってcommit→response.createを送る）
async def send_audio(websocket, stream, CHUNK, RATE, mic_enabled_event: asyncio.Event, awaiting_response: asyncio.Event):
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
        
        # PCM16データをBase64にエンコード
        base64_audio = base64.b64encode(audio_data).decode("utf-8")

        audio_event = {
            "type": "input_audio_buffer.append",
            "audio": base64_audio
        }

        # WebSocketで音声データを送信
        await websocket.send(json.dumps(audio_event))
        

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
                    tts.stream_speak(s, None, False, None, False)
                    buf = ""

        elif response_data.get("type") == "response.completed":
            # 応答完了: サーバ側バッファをクリアし、マイク再開
            
            await websocket.send(json.dumps({"type": "input_audio_buffer.clear"}))
            awaiting_response.clear()
            print("マイク再開: response.completed")
            mic_enabled_event.set()

        # 出力音声は再生しないため、audio.deltaは無視

        # 出力完了イベント
        if response_data.get("type") in ("response.audio.done", "response.output_text.done"):
            await websocket.send(json.dumps({"type": "input_audio_buffer.clear"}))
            awaiting_response.clear()
            print("マイク再開: response.audio.done, response.output_text.done")
            mic_enabled_event.set()

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
