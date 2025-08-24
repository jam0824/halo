# Halo - 音声アシスタントシステム

HaloはPythonで実装された音声アシスタントシステムです。音声認識、LLM応答生成、音声合成を組み合わせて、自然な音声会話を実現します。

## 機能

- **音声認識 (STT)**: Google Cloud Speech-to-Text v2を使用したリアルタイム音声認識
- **自然言語生成 (LLM)**: OpenAI GPT-4o-miniによる応答生成
- **音声合成 (TTS)**: VOICEVOXエンジンによる音声合成と再生
- **設定可能なキャラクター**: 設定ファイルによるキャラクター名や話し方のカスタマイズ

## システム要件

- Python 3.8以上
- VOICEVOXエンジン（ローカル起動）
- Google Cloud Speech-to-Text API アクセス権限
- OpenAI API キー

## セットアップ

### 1. 依存関係のインストール

```bash
pip install openai google-cloud-speech pyaudio requests simpleaudio
```

### 2. API設定

#### Google Cloud Speech-to-Text
1. Google Cloud Projectを作成
2. Speech-to-Text APIを有効化
3. サービスアカウントキーまたはApplication Default Credentialsを設定
4. 環境変数を設定:
   ```bash
   export GOOGLE_CLOUD_PROJECT="your-project-id"
   ```

#### OpenAI API
1. OpenAI APIキーを取得
2. 環境変数を設定:
   ```bash
   export OPENAI_API_KEY="your-api-key"
   ```

### 3. VOICEVOXエンジンの起動

1. [VOICEVOX](https://voicevox.hiroshiba.jp/)をダウンロード・インストール
2. VOICEVOXエンジンを起動（デフォルト: http://127.0.0.1:50021）

## 使用方法

### 基本的な実行

```bash
python halo.py
```

### 設定ファイル（config.js）

プロジェクトルートに`config.js`を配置して、キャラクター設定をカスタマイズできます：

```json
{
  "system_content": "あなたの名前は{your_name}です。これはユーザーである{owner_name}とあなた（{your_name}）との会話です。",
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
```

### 音声コマンド

- **終了**: "終了"、"バイバイ"、"さようなら"と言うと会話を終了

## ファイル構成

```
halo/
├── halo.py              # メインアプリケーション
├── config.js            # 設定ファイル
├── llm.py              # OpenAI GPT-4o-mini連携
├── stt.py              # Google Cloud Speech-to-Text連携
├── voicevox.py         # VOICEVOX TTS連携
├── test_halo_oneshot.py # 単発テスト
├── test_openai.py      # OpenAI APIテスト
├── stt_example.py      # STT使用例
└── README.md           # このファイル
```

## 各モジュールの詳細

### `halo.py`
メインアプリケーション。音声認識→LLM応答生成→音声合成のループを実行します。

### `stt.py`
Google Cloud Speech-to-Text v2を使用した音声認識モジュール。WebRTC VAD（Voice Activity Detection）による発話終了検出機能付き。

### `llm.py`
OpenAI GPT-4o-miniを使用した自然言語生成モジュール。会話履歴を保持して文脈を理解した応答を生成します。

### `voicevox.py`
VOICEVOXエンジンを使用した音声合成モジュール。文単位での合成と即時再生に対応。

## テスト

### OpenAI API接続テスト
```bash
python test_openai.py
```

### STT単体テスト
```bash
python stt_example.py
```

### 単発会話テスト
```bash
python test_halo_oneshot.py
```

## トラブルシューティング

### よくある問題

1. **音声認識エラー**
   - Google Cloud認証が正しく設定されているか確認
   - マイクデバイスが正常に動作しているか確認

2. **音声合成エラー**
   - VOICEVOXエンジンが起動しているか確認（http://127.0.0.1:50021）
   - speaker IDが有効な値か確認

3. **LLM応答エラー**
   - OpenAI APIキーが正しく設定されているか確認
   - API使用制限に達していないか確認

### デバッグ情報

アプリケーション実行時に以下の情報が表示されます：
- STTレイテンシ（音声認識の応答時間）
- LLMレイテンシ（応答生成時間）
- 使用中のマイクデバイス情報

## カスタマイズ

### 音声認識設定
`stt.py`の`SpeechToText`クラス初期化パラメータで調整：
- `language`: 認識言語（デフォルト: "ja-JP"）
- `model`: 認識モデル（デフォルト: "latest_short"）
- `location`: Google Cloudリージョン（デフォルト: "asia-northeast1"）

### 音声合成設定
`config.js`の`voiceVoxTTS`セクションで調整：
- `speaker`: 話者ID
- `speedScale`: 話速（1.0が標準）
- `pitchScale`: ピッチ（0.0が標準）
- `intonationScale`: 抑揚（1.0が標準）

## ライセンス

このプロジェクトは個人利用・研究目的での使用を想定しています。

## 注意事項

- 各種APIの使用料金にご注意ください
- マイクとスピーカーの配置によってはハウリングが発生する可能性があります
- VOICEVOXエンジンのライセンス条項を確認してください
