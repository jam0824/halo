#!/usr/bin/env python3
"""
VOICEVOXエンジン (http://192.168.1.151:50021) への接続テスト
"""

import requests
from voicevox import VoiceVoxTTS
import time

def test_voicevox_connection():
    """http://192.168.1.151:50021 への接続テスト"""
    base_url = "http://192.168.1.151:50021"
    print(f"VOICEVOXエンジン接続テスト: {base_url}")
    
    try:
        # 1. エンジン情報の取得
        print("1. エンジン情報を取得中...")
        response = requests.get(f"{base_url}/version", timeout=5)
        response.raise_for_status()
        version_info = response.json()
        print(f"   ✅ エンジンバージョン: {version_info}")
        
        # 2. 音声クエリのテスト
        print("2. 音声クエリテスト中...")
        test_text = "こんにちは、接続テストです"
        speaker_id = 89
        
        query_response = requests.post(
            f"{base_url}/audio_query",
            params={"text": test_text, "speaker": speaker_id},
            timeout=10
        )
        query_response.raise_for_status()
        print(f"   ✅ 音声クエリ成功")
        
        # 3. 音声合成のテスト
        print("3. 音声合成テスト中...")
        query_data = query_response.json()
        
        synth_response = requests.post(
            f"{base_url}/synthesis",
            params={"speaker": speaker_id},
            json=query_data,
            timeout=30
        )
        synth_response.raise_for_status()
        
        audio_size = len(synth_response.content)
        print(f"   ✅ 音声合成成功 (音声データサイズ: {audio_size} bytes)")
        
        print("\n✅ 基本接続テスト完了: エンジンは正常に動作しています")
        return True
        
    except requests.exceptions.ConnectionError:
        print(f"\n❌ 接続エラー: {base_url} に接続できません")
        print("   VOICEVOXエンジンが起動しているか確認してください")
        return False
        
    except requests.exceptions.Timeout:
        print(f"\n❌ タイムアウト: {base_url} への接続がタイムアウトしました")
        return False
        
    except Exception as e:
        print(f"\n❌ エラー: {e}")
        return False

def test_voicevox_class():
    """VoiceVoxTTSクラスでの実際の音声再生テスト"""
    base_url = "http://192.168.1.151:50021"
    print(f"\nVoiceVoxTTSクラステスト: {base_url}")
    
    try:
        tts = VoiceVoxTTS(
            base_url=base_url,
            speaker=89,
            max_len=50,
            queue_size=2,
        )
        
        print("TTSインスタンス作成成功")
        
        test_text = "テスト、テスト。聞こえますか？"
        print(f"音声合成・再生開始: '{test_text}'")
        
        start_time = time.time()
        tts.speak(test_text)
        end_time = time.time()
        
        print(f"✅ 音声合成・再生完了 (所要時間: {end_time - start_time:.2f}秒)")
        return True
        
    except Exception as e:
        print(f"❌ VoiceVoxTTSクラステストエラー: {e}")
        return False

def main():
    """メイン実行関数"""
    print("VOICEVOXエンジン (192.168.1.151:50021) 接続テスト開始\n")
    
    # 基本接続テスト
    if test_voicevox_connection():
        # 実際の音声再生テスト
        test_voicevox_class()
    else:
        print("\n接続に失敗しました。以下を確認してください：")
        print("1. 192.168.1.151 のVOICEVOXエンジンが起動している")
        print("2. ネットワーク接続が正常")
        print("3. ファイアウォールでポート50021がブロックされていない")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nテストが中断されました")
    except Exception as e:
        print(f"\n予期しないエラーが発生しました: {e}")
