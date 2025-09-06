# halo.py
import json
import threading
import time
from llm import LLM
from voicevox import VoiceVoxTTS  # ← 追加：クラスをインポート
from wav_player import WavPlayer
from stt_azure import AzureSpeechToText
from stt_google import GoogleSpeechToText
from vad import VAD
from command_selector import CommandSelector
from corr_gate import CorrelationGate
from typing import Optional, TYPE_CHECKING, Union
if TYPE_CHECKING:
    from function_led import LEDBlinker
    from function_motor import Motor

def load_system_prompt(system_prompt_path: str = "system_prompt.md") -> str:
    with open(system_prompt_path, 'r', encoding='utf-8') as file:
        system_prompt = file.read()
    return system_prompt


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

def load_stt(stt_type: str) -> Union[AzureSpeechToText, GoogleSpeechToText]:
    if stt_type == "azure":
        return AzureSpeechToText()
    elif stt_type == "google":
        return GoogleSpeechToText()
    else:
        raise ValueError(f"Invalid STT type: {stt_type}")

def main():
    config = load_config()
    system_content = load_system_prompt()
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
        
    command_selector = CommandSelector()
    llm = LLM()
    stt = load_stt(stt_type)
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

    tts = VoiceVoxTTS(
        base_url=tts_config["base_url"],
        speaker=tts_config["speaker"],
        max_len=tts_config["max_len"],
        queue_size=tts_config["queue_size"],
    )
    tts.set_params(
        speedScale=tts_config["speedScale"], 
        pitchScale=tts_config["pitchScale"], 
        intonationScale=tts_config["intonationScale"]
    )
    if isfiller:
        player = WavPlayer()
        player.preload_dir("./filler")
    else:
        player = None

    # ★ 初回ターンも速くしたい場合はプリウォーム（任意）
    try:
        stt.warm_up()
    except Exception as e:
        print(f"STT warm_up でエラー: {e}")

    system_content = replace_placeholders(system_content, owner_name, your_name)
    print(system_content)
    history = ""

    try:
        loop_count = 0
        while True:
            loop_count += 1
            print(f"\n=== ループ {loop_count} 開始 ===")

            #is_voice()  #VADで音声があるかどうかをチェック

            try:
                stt_start_time = time.perf_counter()
                user_text = exec_stt(stt)   # ← listen_once() は内部で「一時停止」までやる
                stt_end_time = time.perf_counter()
                print(f"[STT latency] {stt_end_time - stt_start_time:.1f} ms")
            except KeyboardInterrupt:
                print("\n\n音声認識中に中断されました。")
                break
            if not user_text:
                print("音声が認識されませんでした。もう一度話してください")
                continue

            user_text = apply_text_changes(user_text, change_name)
            history = make_history(history, owner_name, user_text)

            # バイバイの場合
            if is_ferewell(user_text, tts, led, use_led, use_motor, motor, your_name):
                break
            
            # fillerを再生する場合
            say_filler(isfiller, player, use_led, led, use_motor, motor)

            command_selector.select(user_text)

            print("LLMで応答を生成中...")
            llm_start_time = time.perf_counter()
            try:
                response = llm.generate_text(llm_model, user_text, system_content, history)
                response = get_halo_response(response, your_name, command_selector)
                #response = "今日も一日元気に張り切っていこう。本日は晴天なり。"
                history = make_history(history, your_name, response)
            except Exception as e:
                print(f"LLMでエラーが発生しました: {e}")
                continue
            llm_end_time = time.perf_counter()
            print(f"[LLM latency] {llm_end_time - llm_start_time:.1f} ms")

            
            # 応答を読み上げ（この間は STT は一時停止状態）
            move_pan_kyoro_kyoro(use_motor, motor, 2, 1)
            move_tilt_kyoro_kyoro(use_motor, motor,2)
            #exec_tts(tts, response, led, use_led, use_motor, motor)
            
            exec_tts_with_vad(tts, response, led, use_led, use_motor, motor)

            print(f"=== ループ {loop_count} 完了 ===")

    except KeyboardInterrupt:
        print("\n\n会話を終了します。")
        try: tts.stop()
        except: pass
    except Exception as e:
        print(f"\nエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        try: tts.stop()
        except: pass
    finally:
        # ★ プロセス終了時にだけ完全に解放
        try: stt.close()
        except: pass
        try:
            if use_motor and 'motor' in locals() and motor:
                motor.clean_up()
        except: pass
def is_voice() -> bool:
    is_voice = VAD.listen_until_voice_webrtc(
        aggressiveness=3,
        samplerate=16000,
        frame_duration_ms=20,
        device=None,
        timeout_seconds=None,
        min_consecutive_speech_frames=8,
    )
    print(f"is_voice: {is_voice}")
    return is_voice

def is_ferewell(user_text: str, tts: VoiceVoxTTS, led: Optional["LEDBlinker"], use_led: bool, use_motor: bool, motor: Optional["Motor"], your_name: str) -> bool:
    if not check_end_command(user_text):
        return False
    farewell = "バイバイ！"
    print(f"{your_name}: {farewell}")
    try:
        tts.speak(farewell, led, use_led, motor, use_motor, corr_gate=None)
    except Exception as e:
        print(f"TTSでエラーが発生しました: {e}")
    return True

def make_history(history: str, name: str, message: str) -> str:
    line_text = f"{name}: {message}"
    history += line_text + "\n"
    print(line_text)
    return history

def move_pan_kyoro_kyoro(use_motor: bool, motor: Optional["Motor"], speed: float=1, count: int=1):
    if use_motor and motor:
        motor.pan_kyoro_kyoro(80, 100, speed, count)
def move_tilt_kyoro_kyoro(use_motor: bool, motor: Optional["Motor"], count: int=1):
    if use_motor and motor:
        motor.motor_kuchipaku()
        
def say_filler(isfiller: bool, player: WavPlayer, use_led: bool, led: Optional["LEDBlinker"], use_motor: bool, motor: Optional["Motor"]):
    if isfiller:
        if use_led and led:
            led.start_blink()
        move_tilt_kyoro_kyoro(use_motor, motor, 2)
        move_pan_kyoro_kyoro(use_motor, motor, 1, 2)
        player.random_play(block=False)
        print("filler再生中")


def exec_stt(stt: Union[
        AzureSpeechToText, 
        GoogleSpeechToText
    ]) -> str:

    # 音声認識
    print("--- 音声入力待ち ---")
    try:
        user_text = stt.listen_once()
        return user_text
    except KeyboardInterrupt:
        print("\n音声認識を中断しました。")
        raise  # メインループに中断を伝える

def check_end_command(user_text: str) -> bool:
    if "終了" in user_text or "バイバイ" in user_text or "さようなら" in user_text:
        return True
    return False

def exec_tts(tts: VoiceVoxTTS, text: str, led: Optional["LEDBlinker"], isLed: bool, use_motor: bool, motor: Optional["Motor"]):
    try:
        tts.speak(text, led, isLed, motor, use_motor, corr_gate=None)
    except KeyboardInterrupt:
        tts.stop()
        print("\n読み上げを中断しました。")
    except Exception as e:
        print(f"TTSでエラーが発生しました: {e}")

def exec_tts_with_vad(tts: VoiceVoxTTS, text: str, led: Optional["LEDBlinker"], isLed: bool, use_motor: bool, motor: Optional["Motor"]):
    print(f"exec_tts_with_vad: {text}")
    corr_gate = CorrelationGate(
        sample_rate=16000,
        frame_ms=20,
        buffer_sec=3.0,
        corr_threshold=0.60,
        max_lag_ms=95,
    )
    def _vad_watcher():
        ok = VAD.listen_until_voice_webrtc(
            aggressiveness=3, samplerate=16000, frame_duration_ms=20,
            device=None, timeout_seconds=None, min_consecutive_speech_frames=12,
            corr_gate=corr_gate,
        )
        if ok:
            print("割り込み : VADで音声が検出されました。")
            tts.stop()

    watcher = threading.Thread(target=_vad_watcher, daemon=True)
    watcher.start()
    try:
        tts.speak(text, led, isLed, motor, use_motor, corr_gate=corr_gate)
    except KeyboardInterrupt:
        tts.stop()
        print("\n読み上げを中断しました。")
    except Exception as e:
        print(f"TTSでエラーが発生しました: {e}")
    finally:
        # 監視スレッドはVAD戻りで自然終了。長時間ブロックを避けて短めにjoin。
        watcher.join(timeout=0.1)

def replace_placeholders(text: str, owner_name: str, your_name: str) -> str:
    text = text.replace("{owner_name}", owner_name)
    text = text.replace("{your_name}", your_name)
    return text

def replace_dont_need_word(text: str, your_name: str) -> str:
    text = text.replace(f"{your_name}:", "")
    text = text.replace(f"{your_name}：", "")
    return text

def get_halo_response(text: str, your_name: str, command_selector: CommandSelector) -> str:
    print(f"text: {text}")
    response_json = json.loads(text)
    response = replace_dont_need_word(response_json['message'], your_name)
    
    command = response_json['command']
    if command:
        for key, value in command.items():
            command_selector.exec_command(key, value)
    return response

def apply_text_changes(text: str, change_text_config: dict) -> str:
    """テキスト内に変更対象の文字列があったら、それを変更対象の文字列に置き換えて返すメソッド"""
    if not change_text_config:
        return text
    
    result = text
    for key, value in change_text_config.items():
        if key in result:
            result = result.replace(key, value)
    
    return result
    

if __name__ == "__main__":
    main()
