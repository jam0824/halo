import os
import shutil
import subprocess
from pathlib import Path

class SpotifyRefresh:
    def refresh(self):
        # 実行ディレクトリをファイル位置から絶対パスで解決
        base_dir = Path(__file__).resolve().parents[2]  # .../codes
        target_dir = base_dir / "spotify-mcp-server"
        print(target_dir)
        if not target_dir.exists():
            raise FileNotFoundError(f"作業ディレクトリが見つかりません: {target_dir}")

        # Windows 環境でも確実に npm を見つける
        listExecutableCandidates = ["npm"]
        if os.name == "nt":
            listExecutableCandidates = ["npm.cmd", "npm.exe", "npm"]

        npm_path = None
        for name in listExecutableCandidates:
            found = shutil.which(name)
            if found:
                npm_path = found
                break

        if npm_path is None:
            raise FileNotFoundError("npm が見つかりません。Node.js/npm をインストールし、PATH を設定してください。")

        # 実行したいコマンド（非ブロッキング）
        listCmd = [npm_path, "run", "refresh"]

        # 非ブロッキングで起動し、ログへリダイレクト
        log_path = target_dir / "refresh.log"
        creationflags = 0
        if os.name == "nt":
            # コンソールウィンドウを出さない（Windows のみ）
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        log_file = open(log_path, "a", encoding="utf-8")
        try:
            process = subprocess.Popen(
                listCmd,
                cwd=str(target_dir),
                stdout=log_file,
                stderr=log_file,
                shell=False,
                start_new_session=True,
                creationflags=creationflags,
            )
        finally:
            # Popen にファイルハンドルが引き渡された後はクローズしてよい
            try:
                log_file.close()
            except Exception:
                pass

        print(f"Spotify refresh started (PID={process.pid}). Logs: {log_path}")
        return process.pid
if __name__ == "__main__":
    spotify_refresh = SpotifyRefresh()
    spotify_refresh.refresh()