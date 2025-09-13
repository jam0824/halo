import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Pattern, Tuple
from playwright.controller_browser import BrowserController


class CommandSelector:
    """
    - 初期化時に command.json を読み込む
    - 文字列を正規表現で評価し、最初にヒットした key を返す
    - key に応じて処理を分岐するセレクター（現状は print のみ）
    """

    def __init__(self, config_path: str = "command.json") -> None:
        self.config_path: str = config_path
        self.listRules: List[Tuple[str, Pattern[str]]] = []
        self._load_config()

    def _load_config(self) -> None:
        path = Path(self.config_path)
        if not path.exists():
            raise FileNotFoundError(f"設定ファイルが見つかりません: {path}")
        with path.open("r", encoding="utf-8") as f:
            data: Dict[str, Dict[str, str]] = json.load(f)

        dictCommands: Dict[str, str] = data.get("command", {})  # type: ignore[assignment]
        # JSON の順序を尊重して評価する
        for key, regexp in dictCommands.items():
            try:
                compiled = re.compile(regexp)
            except re.error as e:
                raise ValueError(f"正規表現が不正です: key={key}, pattern={regexp}, err={e}") from e
            self.listRules.append((key, compiled))

    def match_key(self, text: str) -> Optional[str]:
        for key, pattern in self.listRules:
            if pattern.search(text):
                return key
        return None

    def select(self, text: str) -> Optional[str]:
        key = self.match_key(text)
        if key is None:
            print("[selector] マッチするコマンドがありませんでした")
            return None
        
        self.exec_command(key, text)
        return key
    
    def exec_command(self, key: str, text: str) -> str:
        result = None
        if key == "browser":
            self._bc = getattr(self, "_bc", BrowserController())  # 使い回し
            return self._bc.send_async(text)  # Futureを返す
        else:
            print(f"[selector] {key} コマンドを検出: text='{text}'")
            return None


if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "ライトをつけて"
    selector = CommandSelector()
    selector.select(text)