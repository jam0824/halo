from datetime import datetime
import os


class ServerHelper:
    def make_file_name(self, path: str, option_string: str):
        return f"{path}{datetime.now().strftime('%Y%m%d')}{option_string}.txt"

    def get_today_month_day(self) -> str:
        """今日の日付を『～月～日』形式で返す。例: '9月20日'"""
        now = datetime.now()
        return f"{now.month}月{now.day}日"

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
