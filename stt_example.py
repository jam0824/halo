#!/usr/bin/env python3
"""
SpeechToTextクラスの使用例

このファイルは、SpeechToTextクラスの基本的な使い方を示しています。
"""

from stt import SpeechToText

def basic_usage():
    """基本的な使用方法の例"""
    print("=== 基本的な使用方法 ===")
    
    # デフォルト設定でインスタンスを作成
    stt = SpeechToText()
    
    print("何か話してください...")
    text = stt.listen_once()
    
    if text:
        print(f"認識されたテキスト: '{text}'")
    else:
        print("音声が認識されませんでした。")

def custom_settings():
    """カスタム設定での使用例"""
    print("\n=== カスタム設定での使用 ===")
    
    # カスタム設定でインスタンスを作成
    stt = SpeechToText(
        language="en-US",  # 英語に変更
        model="latest_long",  # 長い音声用モデル
        location="us-central1"  # 米国リージョン
    )
    
    print("Please say something in English...")
    text = stt.listen_once()
    
    if text:
        print(f"Recognized text: '{text}'")
    else:
        print("No speech was recognized.")

def continuous_listening():
    """連続的な音声認識の例"""
    print("\n=== 連続的な音声認識 ===")
    
    stt = SpeechToText()
    
    print("連続的な音声認識を開始します。'終了'と言うと終了します。")
    
    while True:
        print("\n話してください...")
        text = stt.listen_once()
        
        if not text:
            print("音声が認識されませんでした。もう一度話してください。")
            continue
        
        print(f"認識結果: '{text}'")
        
        # 終了条件をチェック
        if "終了" in text.lower() or "おわり" in text.lower():
            print("音声認識を終了します。")
            break

def error_handling_example():
    """エラーハンドリングの例"""
    print("\n=== エラーハンドリングの例 ===")
    
    try:
        # 不正な設定を使用してエラーを発生させる例
        stt = SpeechToText(location="invalid-location")
        text = stt.listen_once()
        print(f"認識結果: {text}")
        
    except Exception as e:
        print(f"エラーが発生しました: {e}")
        print("適切な設定を使用してください。")

def integration_example():
    """他のシステムとの統合例"""
    print("\n=== 統合例（音声→テキスト変換のみ） ===")
    
    stt = SpeechToText()
    
    # 音声認識の結果をリストに保存
    list_recognized_texts = []
    
    for i in range(3):
        print(f"\n{i+1}回目の音声入力...")
        text = stt.listen_once()
        
        if text:
            list_recognized_texts.append(text)
            print(f"保存されたテキスト: '{text}'")
        else:
            print("音声が認識されませんでした。")
    
    print(f"\n認識されたテキストの一覧:")
    for i, text in enumerate(list_recognized_texts, 1):
        print(f"{i}. {text}")

def resource_management_examples():
    """リソース管理の方法例"""
    print("\n=== リソース管理の方法例 ===")
    
    # 方法1: with文を使用（推奨）
    print("\n方法1: with文を使用（推奨）")
    with SpeechToText() as stt:
        print("with文で自動的にリソースが管理されます")
        text = stt.listen_once()
        if text:
            print(f"認識結果: {text}")
    # ここで自動的にクリーンアップされる
    
    # 方法2: 明示的なクリーンアップ
    print("\n方法2: 明示的なクリーンアップ")
    stt = SpeechToText()
    try:
        text = stt.listen_once()
        if text:
            print(f"認識結果: {text}")
    finally:
        stt.cleanup()  # 明示的にクリーンアップ
    
    # 方法3: 毎回インスタンス化（ユーザーの要望に対応）
    print("\n方法3: 毎回インスタンス化と自動破棄")
    list_results = []
    for i in range(2):
        print(f"\n{i+1}回目の音声認識:")
        with SpeechToText() as stt:
            text = stt.listen_once()
            if text:
                list_results.append(text)
                print(f"結果: {text}")
        # 各ループで自動的にインスタンスが破棄される
    
    print(f"\n収集された結果: {list_results}")

def manual_cleanup_example():
    """手動でのクリーンアップ例"""
    print("\n=== 手動クリーンアップ例 ===")
    
    stt = None
    try:
        stt = SpeechToText()
        text = stt.listen_once()
        print(f"認識結果: {text}")
    except Exception as e:
        print(f"エラー: {e}")
    finally:
        if stt:
            stt.cleanup()
            print("手動でクリーンアップを実行しました")

if __name__ == "__main__":
    print("SpeechToTextクラスの使用例")
    print("=" * 50)
    
    try:
        # 基本的な使用方法
        basic_usage()
        
        # リソース管理の方法例
        resource_management_examples()
        
        # カスタム設定での使用（コメントアウト、必要に応じて有効化）
        # custom_settings()
        
        # 連続的な音声認識（コメントアウト、必要に応じて有効化）
        # continuous_listening()
        
        # エラーハンドリングの例（コメントアウト、必要に応じて有効化）
        # error_handling_example()
        
        # 統合例
        # integration_example()
        
        # 手動クリーンアップ例
        # manual_cleanup_example()
        
    except KeyboardInterrupt:
        print("\n\nプログラムが中断されました。")
    except Exception as e:
        print(f"\n予期しないエラーが発生しました: {e}")
