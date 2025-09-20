from pathlib import Path
import json
from server_helper import ServerHelper
from make_generic_memory import MakeGenericMemory
import random


class FakeMemory:
    path = "fake_memory/"
    def __init__(self):
        self.server_helper = ServerHelper()
        self.make_generic_memory = MakeGenericMemory()
        self.base_dir = Path(__file__).resolve().parent.parent / self.path
        print(self.base_dir)

    def make_fake_memory(self) -> None:
        diary_text = self.make_travel_memory()
        return diary_text

    def select_memory(self, data_file: str):
        file_path = self.base_dir / data_file
        fake_memory = self.server_helper.read_file_lines(str(file_path))
        return random.choice(fake_memory)

    def replace_word(self, text: str, selected_memory: str, today_month_day: str):
        text = text.replace("{selected_memory}", selected_memory)
        text = text.replace("{today_month_day}", today_month_day)
        return text

    def make_travel_memory(self):
        file_path = self.base_dir / "travel_memory.json"
        data = self.server_helper.read_file_text(str(file_path))
        # ファイル名が欲しいだけでjson化。後にリプレイスする。良いやり方があれば変えたい
        tmp_dict_data = json.loads(data)
        selected_memory = self.select_memory(tmp_dict_data["data_file"])
        today_month_day = self.server_helper.get_today_month_day()  

        data = self.replace_word(data, selected_memory, today_month_day)
        dict_data = json.loads(data)
        diary_text = self.make_generic_memory.make_generic_memory(dict_data, str(self.base_dir))
        return diary_text


if __name__ == "__main__":
    fake_memory = FakeMemory()
    text = fake_memory.make_fake_memory()
    print(text)


