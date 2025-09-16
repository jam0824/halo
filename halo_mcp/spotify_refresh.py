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

        # 実行したいコマンド
        listCmd = [npm_path, "run", "refresh"]

        # 作業ディレクトリを指定して実行
        result = subprocess.run(listCmd, cwd=str(target_dir), capture_output=True, text=True, shell=False)

        # 標準出力と標準エラーを表示
        print("stdout:", result.stdout)
        print("stderr:", result.stderr)
        return result.stdout
if __name__ == "__main__":
    spotify_refresh = SpotifyRefresh()
    spotify_refresh.refresh()