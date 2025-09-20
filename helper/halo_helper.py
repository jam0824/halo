import json
import os

class HaloHelper:
    # 設定ファイルの読み込み
    def load_config(self, config_path: str = "config.json") -> dict:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return self._get_default_config()
        except json.JSONDecodeError:
            return self._get_default_config()

    def _get_default_config(self) -> dict:
        return {
            "voiceVoxTTS": {
                "base_url": "http://127.0.0.1:50021",
                "speaker": 89,
                "max_len": 80,
                "queue_size": 4,
                "speedScale": 1.0,
                "pitchScale": 0.0,
                "intonationScale": 1.0,
            },
            "owner_name": "まつ",
            "your_name": "ハロ",
            "llm": "gpt-4o-mini",
            "change_text": {"春": "ハロ"},
            "led": {"use_led": True, "led_pin": 27},
            "motor": {"use_motor": True, "pan_pin": 4, "tilt_pin": 25},
            "vad": {
                "samplereate": 16000,
                "frame_duration_ms": 20,
                "corr_threshold": 0.60,
                "max_lag_ms": 95,
            },
        }

    # システムプロンプトの読み込みと名前の変更
    def load_system_prompt_and_replace(self, owner_name: str, your_name: str) -> str:
        try:
            with open("system_prompt.md", "r", encoding="utf-8") as f:
                s = f.read()
        except Exception:
            s = "あなたはアシスタントです。"
        s = s.replace("{owner_name}", owner_name)
        s = s.replace("{your_name}", your_name)
        return s

    # ユーザー発話認識のテキスト変更(春→ハロなど)
    def apply_text_changes(self, text: str, change_text_map: dict) -> str:
        if not change_text_map:
            return text
        result = text
        try:
            for key, value in change_text_map.items():
                if key in result:
                    result = result.replace(key, value)
        except Exception:
            pass
        return result

    # ハロ発話から不要な単語を削除
    def replace_dont_need_word(self, text: str, your_name: str) -> str:
        try:
            text = text.replace(f"{your_name}:", "")
            text = text.replace(f"{your_name}：", "")
        except Exception:
            pass
        return text

    # 履歴にユーザー発話を追加
    def append_history(self, history: str, name: str, message: str) -> str:
        line = f"{name}: {message}\n"
        print(line)
        history = history + line
        return history

    # jsonからハロ発話を抽出
    def get_halo_response(self, text: str) -> tuple[str, str]:
        print(f"Response: {text}")
        responses = text.split("\n")
        if len(responses) == 1:
            return responses[0], ""
        # 1行目がメッセージ、2行目がコマンド
        return responses[0], responses[1]

    # テキストファイルを読み込み、1行ごとのリストにして返す
    def read_file_lines(self, file_path: str) -> list[str]:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                listLines = f.read().splitlines()
            return listLines
        except Exception:
            return []
    def read_file_text(self, file_path: str) -> str:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    # 与えられたテキストを指定パスに保存する
    def save_text_to_file(self, file_path: str, text: str) -> bool:
        try:
            parent = os.path.dirname(file_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(text)
            return True
        except Exception:
            return False

    