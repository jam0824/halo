# halo.py
from llm import LLM
from stt import SpeechToText
from voicevox import VoiceVoxTTS  # ← 追加：クラスをインポート

def main():
    # システムプロンプト
    system_content = "これはユーザーであるみねおとあなた（ハロ）との会話です。ハロは片言で返します。（例）ハロ、わかった！"
    
    # LLM/STT/TTS のインスタンス作成（TTSは一度だけ）
    llm = LLM()
    tts = VoiceVoxTTS(
        base_url="http://127.0.0.1:50021",
        speaker=89,     # 好きな話者IDに変更OK
        max_len=80,
        queue_size=4,
    )
    # 好みの声質調整（任意）
    tts.set_params(speedScale=1.0, pitchScale=0.0, intonationScale=1.0)

    try:
        loop_count = 0
        while True:
            loop_count += 1
            print(f"\n=== ループ {loop_count} 開始 ===")

            user_text = exec_stt()
            if not user_text:
                print("音声が認識されませんでした。もう一度話してください。")
                continue
            print(f"みねお: {user_text}")
            
            # 終了コマンド
            if check_end_command(user_text):
                farewell = "バイバイ！"
                print(f"ハロ: {farewell}")
                # 口頭でもお別れを読み上げ
                try:
                    tts.speak(farewell)
                except Exception as e:
                    print(f"TTSでエラーが発生しました: {e}")
                break
            
            # LLM応答生成
            print("LLMで応答を生成中...")
            try:
                response = llm.generate_text(user_text, system_content)
                print(f"ハロ: {response}")
            except Exception as e:
                print(f"LLMでエラーが発生しました: {e}")
                continue  # エラーが発生してもループを続ける
            
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

def exec_stt() -> str:
    # 音声認識
    print("--- 音声入力待ち ---")
    with SpeechToText() as stt:
        user_text = stt.listen_once()
    return user_text

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
    

if __name__ == "__main__":
    main()
