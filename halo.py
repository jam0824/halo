from llm import LLM
from stt import SpeechToText

def main():
    # システムプロンプト
    system_content = "これはユーザーであるみねおとあなた（ハロ）との会話です。ハロは片言で返します。（例）ハロ、わかった！"
    
    # LLMとSTTのインスタンスを作成
    llm = LLM()
    
    try:
        loop_count = 0
        while True:
            loop_count += 1
            print(f"\n=== ループ {loop_count} 開始 ===")
            
            # 音声認識でユーザーの発話を取得（方法1: with文を使用した自動リソース管理）
            print("--- 音声入力待ち ---")
            with SpeechToText() as stt:
                user_text = stt.listen_once()
            
            if not user_text:
                print("音声が認識されませんでした。もう一度話してください。")
                continue
            
            print(f"みねお: {user_text}")
            
            # 終了コマンドをチェック
            if "終了" in user_text or "バイバイ" in user_text or "さようなら" in user_text:
                print("ハロ: バイバイ！")
                break
            
            # LLMで応答を生成
            print("LLMで応答を生成中...")
            try:
                response = llm.generate_text(user_text, system_content)
                print(f"ハロ: {response}")
            except Exception as e:
                print(f"LLMでエラーが発生しました: {e}")
                continue  # エラーが発生してもループを続ける
            
            print(f"=== ループ {loop_count} 完了 ===")
            
    except KeyboardInterrupt:
        print("\n\n会話を終了します。")
    except Exception as e:
        print(f"\nエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
    

if __name__ == "__main__":
    main()