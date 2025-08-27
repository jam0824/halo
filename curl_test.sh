# テキストを音声合成クエリへ変換
curl -s -X POST "http://192.168.1.151:50021/audio_query?speaker=1" --get --data-urlencode "text=こんにちは、世界" > query.json

# クエリを用いて音声（WAV）を生成
curl -s -H "Content-Type: application/json" -X POST -d @query.json "http://192.168.1.151:50021/synthesis?speaker=1" > audio.wav

# 再生
aplay audio.wav
