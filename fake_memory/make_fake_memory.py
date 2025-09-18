import sys
import os
from pathlib import Path
# プロジェクトルート(../)を sys.path に追加してモジュール解決
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from llm import LLM
from helper.halo_helper import HaloHelper
import random
from datetime import datetime
from threading import Thread


class FakeMemory:
    path = "fake_memory/"
    def __init__(self):
        self.llm = LLM()
        self.halo_helper = HaloHelper()

    def select_destination(self):
        
        fake_memory = self.halo_helper.read_file_lines("fake_memory/travel.md")
        return random.choice(fake_memory)

    def make_travel_plan(self, selected_memory):
        prompt = f"あなたはアシスタントです。{selected_memory}について1日で巡れる詳しい旅行計画を立ててください。おすすめのグルメやおみやげも織り交ぜてください。"
        response = self.llm.generate_text("gpt-5-mini", prompt, "あなたはプロのツアーリストです。", "")
        return response

    def make_travel_experience(self, response):
        prompt = f"以下の旅行計画を実際に実行したとして、楽しかった体験を詳細に記述してください。実際の体験として書いてください。{response}"
        response_memory = self.llm.generate_text("gpt-4o-mini", prompt, "プロの脚本家の様に、あたかも実際に体験したかのように記述するのが得意です。必ず「これは今日の楽しい一日の思い出です。」からはじめてください。", "")
        print(response_memory)
        return response_memory

    def make_fake_memory(self) -> Thread:
        def worker():
            selected_memory = self.select_destination()
            response = self.make_travel_plan(selected_memory)
            file_name = self.make_file_name("_travel_plan")
            self.halo_helper.save_text_to_file(file_name, response)
            response_memory = self.make_travel_experience(response)
            file_name = self.make_file_name("_diary")
            self.halo_helper.save_text_to_file(file_name, response_memory)

        if os.path.exists(self.get_fake_memory_path()):
            return None
        background_thread = Thread(target=worker, daemon=True)
        background_thread.start()
        return background_thread

    def make_file_name(self, option_string: str):
        return f"{self.path}{datetime.now().strftime('%Y%m%d')}{option_string}.txt"
    
    def get_fake_memory_path(self):
        return self.make_file_name("_diary")

    def get_fake_memory_text(self):
        return self.halo_helper.read_file_text(self.get_fake_memory_path())

    def check_todays_memory(self):
        if os.path.exists(self.get_fake_memory_path()):
            return True
        return False


if __name__ == "__main__":
    fake_memory = FakeMemory()
    thread = fake_memory.make_fake_memory()
    if thread is None:
        print("既に生成されています")
        exit()
    print(f"生成をバックグラウンドで開始しました: {thread.name}")
    thread.join()
    print("生成が完了しました。")


