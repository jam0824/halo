from llm_server import LLM
from server_helper import ServerHelper

class MakeGenericMemory:
    def __init__(self):
        self.llm = LLM()
        self.server_helper = ServerHelper()
        self.data_save_path = "fake_memory/diary/"

    def make_detailed_text(self, dict_data: dict):
        detailed_text = self.llm.generate_text(
            dict_data["detailed"]["model"], 
            dict_data["detailed"]["prompt"], 
            dict_data["detailed"]["system_content"], 
            dict_data["detailed"]["assistant_content"])
        file_name = self.server_helper.make_file_name(self.data_save_path, "_detailed")
        print(file_name)
        self.server_helper.save_text_to_file(file_name, detailed_text)
        return detailed_text

    def make_diary_text(self, dict_data: dict, detailed_text: str):
        prompt = dict_data["diary"]["prompt"] + detailed_text
        diary_text = self.llm.generate_text(
            dict_data["diary"]["model"], 
            prompt, 
            dict_data["diary"]["system_content"], 
            dict_data["diary"]["assistant_content"])
        file_name = self.server_helper.make_file_name(self.data_save_path, "_diary")
        print(file_name)
        self.server_helper.save_text_to_file(file_name, diary_text)
        return diary_text

    def make_summary_text(self, dict_data: dict, diary_text: str):
        prompt = dict_data["summary"]["prompt"] + diary_text
        summary_text = self.llm.generate_text(
            dict_data["summary"]["model"], 
            prompt, 
            dict_data["summary"]["system_content"], 
            dict_data["summary"]["assistant_content"])
        file_name = self.server_helper.make_file_name(self.data_save_path, "_summary")
        print(file_name)
        self.server_helper.save_text_to_file(file_name, summary_text)
        return summary_text


    def make_generic_memory(self, dict_data: dict, path: str):
        self.data_save_path = path + "/diary/"
        # 詳細を作る
        detailed_text = self.make_detailed_text(dict_data)
        # 詳細から日記を作る
        diary_text = self.make_diary_text(dict_data, detailed_text)
        # 日記から要約を作る
        summary_text = self.make_summary_text(dict_data, diary_text)
        return summary_text
