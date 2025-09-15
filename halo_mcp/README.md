# mcpセットアップ

## install
```
sudo apt install nodejs npm
npm i @openai/agents
pip install "mcp[cli]"
curl -LsSf https://astral.sh/uv/install.sh | sh
pip install uv
```

## 各種keyの設定
```
$env:OPENAI_API_KEY = "sk-..."
$env:BRAVE_API_KEY  = "..."
$env:SPOTIPY_CLIENT_ID = ""
$env:SPOTIPY_CLIENT_SECRET = ""
$env:SPOTIPY_REDIRECT_URI = "http://127.0.0.1:8080/callback"
```
switchbotのkeyは.envの中にある。

powershellの永続化例
```
[Environment]::SetEnvironmentVariable("BRAVE_API_KEY", "あなたのAPIキー", "User")
```

## Spotifyの設定
```
git clone https://github.com/varunneal/spotify-mcp.git
cd spotify-mcp
# 依存を同期して実行テスト
uv sync
uv run spotify-mcp --help
```


## Playwright実行側(サーバー側)設定
### ブラウザのインストール
```
npx playwright install chromium
```
### ngrokの設定
```
ngrok config add-authtoken <YOUR_NGROK_TOKEN>   # 初回のみ
```
### サーバーの立ち上げ
以下は`run_voicevox.bat`で実行している
```
npx -y @playwright/mcp@latest --host 0.0.0.0 --port 8931
```
```
ngrok http --domain=prevalid-unacrimoniously-leigh.ngrok-free.app 8931
```


