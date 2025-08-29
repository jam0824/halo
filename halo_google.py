# halo.py
import json
import time
import sys
from llm import LLM
from stt_google import GoogleSpeechToText
from voicevox import VoiceVoxTTS  # ← 追加：クラスをインポート
from wav_player import WavPlayer
from stt_azure import AzureSpeechToText

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
        "voiceVoxTTS": {
            "base_url": "http://127.0.0.1:50021",
            "speaker": 89,
            "max_len": 80,
            "queue_size": 4,
            "speedScale": 1.0,
            "pitchScale": 0.0,
            "intonationScale": 1.0
        }
    }

def main():
    config = load_config()
    system_content = config["system_content"]
    owner_name = config["owner_name"]
    your_name = config["your_name"]
    tts_config = config["voiceVoxTTS"]
    change_name = config["change_text"]
    isfiller = config["use_filler"]

    llm = LLM()
    stt = GoogleSpeechToText()
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

            if isfiller:
                player.random_play(block=False)
                print("filler再生中")
            
            user_text = apply_text_changes(user_text, change_name)
            owner_text = f"{owner_name}: {user_text}"
            history += owner_text + "\n"
            print(owner_text)
            stt_end_time = time.perf_counter()

            if check_end_command(user_text):
                farewell = "バイバイ！"
                print(f"{your_name}: {farewell}")
                try:
                    tts.speak(farewell)
                except Exception as e:
                    print(f"TTSでエラーが発生しました: {e}")
                break

            print("LLMで応答を生成中...")
            try:
                response = llm.generate_text(user_text, system_content, history)
                response = response.replace(f"{your_name}:", "")
                your_text = f"{your_name}: {response}"
                history += your_text + "\n"
                print(your_text)
            except Exception as e:
                print(f"LLMでエラーが発生しました: {e}")
                continue

            llm_end_time = time.perf_counter()
            print(f"[LLM latency] {llm_end_time - stt_end_time:.1f} ms")

            # 応答を読み上げ（この間は STT は一時停止状態）
            exec_tts(tts, response)

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

def exec_stt(stt: GoogleSpeechToText) -> str:
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

def exec_tts(tts: VoiceVoxTTS, text: str):
    try:
        tts.speak(text)
    except KeyboardInterrupt:
        tts.stop()
        print("\n読み上げを中断しました。")
    except Exception as e:
        print(f"TTSでエラーが発生しました: {e}")

def replace_placeholders(text: str, owner_name: str, your_name: str) -> str:
    text = text.replace("{owner_name}", owner_name)
    text = text.replace("{your_name}", your_name)
    return text

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
