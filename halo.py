# halo.py
import json
import time
import sys
from llm import LLM
from stt import SpeechToText
from voicevox import VoiceVoxTTS  # ← 追加：クラスをインポート

def load_config(config_path: str = "config.js") -> dict:
    """設定ファイル（config.js）を読み込む"""
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
    # 設定ファイルを読み込み
    config = load_config()
    
    # 設定から値を取得
    system_content = config["system_content"]
    owner_name = config["owner_name"]
    your_name = config["your_name"]
    tts_config = config["voiceVoxTTS"]
    
    # LLM/STT/TTS のインスタンス作成（TTSは一度だけ）
    llm = LLM()
    stt = SpeechToText()
    tts = VoiceVoxTTS(
        base_url=tts_config["base_url"],
        speaker=tts_config["speaker"],
        max_len=tts_config["max_len"],
        queue_size=tts_config["queue_size"],
    )
    # 声質調整（設定ファイルから）
    tts.set_params(
        speedScale=tts_config["speedScale"], 
        pitchScale=tts_config["pitchScale"], 
        intonationScale=tts_config["intonationScale"]
    )

    system_content = replace_placeholders(system_content, owner_name, your_name)
    history = ""

    try:
        loop_count = 0
        while True:
            loop_count += 1
            print(f"\n=== ループ {loop_count} 開始 ===")

            try:
                user_text = exec_stt(stt)
            except KeyboardInterrupt:
                print("\n\n音声認識中に中断されました。")
                break
            
            if not user_text:
                print("音声が認識されませんでした。もう一度話してください")
                continue
            owner_text = f"{owner_name}: {user_text}"
            history += owner_text + "\n"
            print(owner_text)
            stt_end_time = time.perf_counter()

            # 終了コマンド
            if check_end_command(user_text):
                farewell = "バイバイ！"
                print(f"{your_name}: {farewell}")
                # 口頭でもお別れを読み上げ
                try:
                    tts.speak(farewell)
                except Exception as e:
                    print(f"TTSでエラーが発生しました: {e}")
                break
            
            # LLM応答生成
            print("LLMで応答を生成中...")
            try:
                response = llm.generate_text(user_text, system_content, history)
                response = response.replace(f"{your_name}:", "")
                your_text = f"{your_name}: {response}"
                history += your_text + "\n"
                print(your_text)
            except Exception as e:
                print(f"LLMでエラーが発生しました: {e}")
                continue  # エラーが発生してもループを続ける
            
           
            llm_end_time = time.perf_counter()
            print(f"[LLM latency] {llm_end_time - stt_end_time:.1f} ms")
             # 応答を読み上げ（同期、終わるまで待つ）
            exec_tts(tts, response)
            
            print(f"=== ループ {loop_count} 完了 ===")
            
    except KeyboardInterrupt:
        print("\n\n会話を終了します。")
        tts.stop()
    except Exception as e:
        print(f"\nエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        tts.stop()

def exec_stt(stt: SpeechToText) -> str:
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
    

if __name__ == "__main__":
    main()
