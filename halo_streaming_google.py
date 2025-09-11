import json
import threading
import time
from typing import Optional, TYPE_CHECKING

from stt_google import GoogleSpeechToText
from voicevox import VoiceVoxTTS
from corr_gate import CorrelationGate
from llm import LLM
from command_selector import CommandSelector

if TYPE_CHECKING:
    from function_led import LEDBlinker
    from function_motor import Motor


def load_config(config_path: str = "config.json") -> dict:
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return get_default_config()
    except json.JSONDecodeError:
        return get_default_config()


def get_default_config() -> dict:
    return {
        "voiceVoxTTS": {
            "base_url": "http://127.0.0.1:50021",
            "speaker": 89,
            "max_len": 80,
            "queue_size": 4,
            "speedScale": 1.0,
            "pitchScale": 0.0,
            "intonationScale": 1.0,
        },
        "owner_name": "まつ",
        "your_name": "ハロ",
        "llm": "gpt-4o-mini",
        "change_text": {"春": "ハロ"},
        "led": {"use_led": True, "led_pin": 27},
        "motor": {"use_motor": True, "pan_pin": 4, "tilt_pin": 25},
        "vad": {
            "samplereate": 16000,
            "frame_duration_ms": 20,
            "corr_threshold": 0.60,
            "max_lag_ms": 95,
        },
    }


def main() -> None:
    cfg = load_config()
    tts_cfg = cfg["voiceVoxTTS"]
    owner_name: str = cfg.get("owner_name", "ユーザー")
    your_name: str = cfg.get("your_name", "ハロ")
    llm_model: str = cfg.get("llm", "gpt-4o-mini")
    change_text_map: dict = cfg.get("change_text", {})

    # --- Devices / TTS ---
    tts = VoiceVoxTTS(
        base_url=tts_cfg["base_url"],
        speaker=tts_cfg.get("speaker", 89),
        max_len=tts_cfg.get("max_len", 80),
        queue_size=tts_cfg.get("queue_size", 4),
    )
    tts.set_params(
        speedScale=tts_cfg.get("speedScale", 1.0),
        pitchScale=tts_cfg.get("pitchScale", 0.0),
        intonationScale=tts_cfg.get("intonationScale", 1.0),
    )

    use_led: bool = cfg["led"]["use_led"]
    led: Optional["LEDBlinker"] = None
    if use_led:
        try:
            from function_led import LEDBlinker

            led = LEDBlinker(int(cfg["led"]["led_pin"]))
        except Exception as e:
            print(f"LED機能を無効化します: {e}")
            use_led = False
            led = None

    use_motor: bool = cfg["motor"]["use_motor"]
    motor: Optional["Motor"] = None
    if use_motor:
        try:
            from function_motor import Motor

            motor = Motor(int(cfg["motor"]["pan_pin"]), int(cfg["motor"]["tilt_pin"]))
        except Exception as e:
            print(f"モーター機能を無効化します: {e}")
            use_motor = False
            motor = None

    # 相関ゲート（TTSエコー抑制用参照）
    vad_cfg = cfg.get("vad", {})
    corr_gate = CorrelationGate(
        sample_rate=vad_cfg.get("samplereate", 16000),
        frame_ms=vad_cfg.get("frame_duration_ms", 20),
        buffer_sec=1.0,
        corr_threshold=vad_cfg.get("corr_threshold", 0.60),
        max_lag_ms=vad_cfg.get("max_lag_ms", 95),
    )

    # --- Google STT / LLM / 会話状態 ---
    stt = GoogleSpeechToText(debug=False)
    llm = LLM()
    history: str = ""
    system_content = _load_system_prompt_and_replace(owner_name, your_name)
    command_selector = CommandSelector()

    # TTSをバックグラウンドで回すためのスレッド管理
    tts_thread: Optional[threading.Thread] = None
    tts_lock = threading.Lock()

    def stop_tts() -> None:
        try:
            tts.stop()
        except Exception:
            pass

    def speak_async(text: str) -> None:
        nonlocal tts_thread
        # 進行中があれば停止
        with tts_lock:
            stop_tts()
            if tts_thread and tts_thread.is_alive():
                # 少しだけ待つ（即時復帰）
                try:
                    tts_thread.join(timeout=0.1)
                except Exception:
                    pass

            def _run():
                try:
                    tts.speak(text, led, use_led, motor, use_motor, corr_gate=corr_gate)
                except Exception as e:
                    print(f"TTSエラー: {e}")

            tts_thread = threading.Thread(target=_run, daemon=True)
            tts_thread.start()

    print("=== Google Streaming STT × VOICEVOX (corr_gate) ===")
    print("話しかけてください。Ctrl+Cで終了します。")

    try:
        for transcript, is_final in stt.listen_streaming_iter(single_utterance=False):
            if not transcript:
                continue
            if is_final:
                print(f"\n確定: {transcript}")
                # 置換（名前など）
                user_text = _apply_text_changes(transcript, change_text_map)
                # 履歴にユーザー発話を追加
                history = _append_history(history, owner_name, user_text)
                # LLMで応答
                try:
                    print("LLMで応答を生成中...")
                    response_text = llm.generate_text(llm_model, user_text, system_content, history)
                except Exception as e:
                    print(f"LLMエラー: {e}")
                    continue
                # ハロ応答を抽出（JSON then command）
                response = _get_halo_response(response_text, your_name, command_selector)
                # 履歴にアシスタント発話を追加
                history = _append_history(history, your_name, response)
                # 新規確定が来たら現TTSを停止し、最新のみ再生
                speak_async(response)
            else:
                # 中間は表示のみ
                print(f"\r中間: {transcript}", end="", flush=True)
    except KeyboardInterrupt:
        print("\n終了します...")
    finally:
        try:
            stop_tts()
            if tts_thread and tts_thread.is_alive():
                tts_thread.join(timeout=0.5)
        except Exception:
            pass
        try:
            stt.close()
        except Exception:
            pass
        try:
            if use_led and led:
                led.stop_blink(wait=True)
                led.off()
        except Exception:
            pass


# ---------- helpers ----------
def _load_system_prompt_and_replace(owner_name: str, your_name: str) -> str:
    try:
        with open("system_prompt.md", "r", encoding="utf-8") as f:
            s = f.read()
    except Exception:
        s = "あなたはアシスタントです。"
    s = s.replace("{owner_name}", owner_name)
    s = s.replace("{your_name}", your_name)
    return s


def _apply_text_changes(text: str, change_text_config: dict) -> str:
    if not change_text_config:
        return text
    result = text
    try:
        for key, value in change_text_config.items():
            if key in result:
                result = result.replace(key, value)
    except Exception:
        pass
    return result


def _append_history(history: str, name: str, message: str) -> str:
    line = f"{name}: {message}"
    print(line)
    return history + line + "\n"


def _replace_dont_need_word(text: str, your_name: str) -> str:
    try:
        text = text.replace(f"{your_name}:", "")
        text = text.replace(f"{your_name}：", "")
    except Exception:
        pass
    return text


def _get_halo_response(text: str, your_name: str, command_selector: CommandSelector) -> str:
    print(f"text: {text}")
    response = text
    try:
        response_json = json.loads(text)
        response = _replace_dont_need_word(response_json.get("message", ""), your_name)
        cmd = response_json.get("command")
        if cmd:
            for key, value in cmd.items():
                try:
                    command_selector.exec_command(key, value)
                except AttributeError:
                    command_selector.select(str(value))
    except Exception:
        pass
    return response



if __name__ == "__main__":
    main()
