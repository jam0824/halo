## Halo - 音声アシスタントシステム

Halo は、音声認識(STT)・大規模言語モデル(LLM)・音声合成(TTS)・デバイス制御(LED/サーボ)を組み合わせた対話型アシスタントです。Raspberry Pi 5 に最適化し、TTSループバック抑制やVADを備えています。

### 主な機能
- **STT**: Azure Cognitive Services または Google Cloud Speech-to-Text（単発認識）
- **LLM**: OpenAI Chat Completions API
- **TTS**: VOICEVOX エンジンにより文単位で合成・即時再生
- **ループバック抑制**: 相関ゲート(`helper/corr_gate.py`)でTTS由来音をSTTから除外
- **VAD**: WebRTC VAD による発話検出(`helper/vad.py`)
- **LED/Motor**: Pi 5 対応。LEDは gpiozero、サーボはハードウェアPWM(`rpi-hardware-pwm`)で低ジッター制御

## 動作要件
- Python 3.9+（推奨: 3.11）
- Raspberry Pi OS (Bookworm) on Raspberry Pi 5 で動作確認
- ネットワーク接続（LLM/STT利用時）

### ハードウェア要件（任意機能）
- LED: GPIO 出力（デフォルト `GPIO27`）
- サーボ: ハードウェアPWM対応ピン（`GPIO18/19` から選択、デフォルト `GPIO18/19`）
  - 外部電源推奨（サーボVccとPiのGND共通）

## セットアップ

### 1) OSパッケージ
```bash
sudo apt update
# Pi 5 GPIO制御（gpiozeroはrpi-lgpioバックエンドで動作）
sudo apt install -y python3-gpiozero python3-rpi-lgpio
# PyAudio実行時に必要になることがあるランタイム
sudo apt install -y libportaudio2
```

### 2) Python 環境
```bash
python3 -m venv halo
source halo/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

環境によっては仮想環境内で `lgpio` が見えない場合があります。その際は下記いずれかを実施してください。
- venv内に直接インストール: `pip install lgpio`
- もしくは venv を `--system-site-packages` で作成

必要に応じてピンファクトリを固定:
```bash
export GPIOZERO_PIN_FACTORY=lgpio
```

### 3) API/サービスの設定
- OpenAI: 環境変数 `OPENAI_API_KEY`
- Azure STT を使う場合: `SPEECH_KEY`, `SPEECH_REGION`
- Google STT を使う場合: ADC（`GOOGLE_APPLICATION_CREDENTIALS` など）

```bash
export OPENAI_API_KEY="sk-..."
# Azure を使う場合
export SPEECH_KEY="your-azure-speech-key"
export SPEECH_REGION="japaneast"  # 例
# Google を使う場合（サービスアカウント）
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/sa.json"
```

### 4) VOICEVOX エンジン
- VOICEVOXエンジンを起動（例: `http://127.0.0.1:50021`）

## 設定ファイル
`config.json` で挙動を調整します（例）。
```json
{
  "owner_name": "まつ",
  "your_name": "ハロ",
  "stt": "azure",                
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
  "change_text": {"春": "ハロ"},
  "filler": {"use_filler": false, "filler_dir": "./filler"},
  "led": {"use_led": true, "led_pin": 27},
  "motor": {"use_motor": true, "pan_pin": 18, "tilt_pin": 19},
  "wakeup_word": ".*(ハロ|しゃべり|喋|話).*",
  "farewell_word": ".*(終了|バイバイ|さようなら).*",
  "interrupt_word": ".*(待って|止めて|終了).*",
  "similarity_threshold": 0.70,
  "coherence_threshold": 0.10,
  "vad": {
    "samplereate": 16000,
    "frame_duration_ms": 20,
    "min_consecutive_speech_frames": 12,
    "aggressiveness": 3,
    "corr_threshold": 0.50,
    "max_lag_ms": 95
  }
}
```

## 実行方法
```bash
source halo/bin/activate
python halo.py
```
- 単発会話モードで、VADが話し始めを検出→STT→LLM→TTSの順に動作します。

## 主要ファイル
- `halo.py`: メインアプリ本体
- `helper/halo_helper.py`: 設定/履歴/テキスト処理ユーティリティ
- `helper/vad.py`: WebRTC VAD による発話検出
- `helper/corr_gate.py`: TTS PCM とマイクの相関でループバック抑制
- `helper/similarity.py`: 類似度計算（ハウリング検知に近い用途）
- `helper/asr_coherence.py`: 認識文の整合性スコア（しきい値でフィルタ）
- `voicevox.py`: VOICEVOX TTS 制御
- `function_led.py`: gpiozero によるLED制御
- `function_motor.py`: ハードウェアPWMによるサーボ制御（低ジッター）
- `stt_azure.py`, `stt_google.py`: 単発認識（listen_once）
- `llm.py`: OpenAI Chat Completions クライアント

## サーボ制御メモ（Raspberry Pi 5）
- PWM対応ピン: `GPIO18/19`
- 既定: PAN=`GPIO18`, TILT=`GPIO19`
- `function_motor.py` の主パラメータ:
  - `frame_width_s` (既定 0.02s=50Hz): 0.02〜0.025の範囲で調整可
  - `angle_step_deg` (既定 1.0): 量子化ステップ。大きくすると微小変化を抑制
  - `min_delta_deg` (既定 0.7): 最小変化しきい値。小刻み更新を無視
  - `hold_servo` (既定 True): 動作終了後に保持。False でデタッチしジッター低減
- 物理的対策: サーボ外部電源、GND共通、信号直列抵抗など

## トラブルシューティング
- `PinFactoryFallback: Falling back from lgpio`: venvに `lgpio` が無い→`pip install lgpio` もしくは `--system-site-packages` で venv 作成
- `Cannot determine SOC peripheral base address`: RPi.GPIO バックエンドにフォールバックしている→ `python3-rpi-lgpio` を導入し `GPIOZERO_PIN_FACTORY=lgpio`
- pigpio は不要（Pi 5 では未対応版が多く、デーモン起動は使いません）
- 麦音（ループバック）を拾う: `helper/corr_gate.py` によりTTS PCMをpublishしておくこと。`halo.py`ではTTSに `self.corr_gate` を渡しています

## ライセンス
個人利用・研究目的での使用を想定しています。各サービスの利用規約/ライセンスに従ってください。
