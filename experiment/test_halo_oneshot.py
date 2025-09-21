from stt import SpeechToText
from llm import LLM

def main():
    with SpeechToText(model="latest_short") as stt:
        user_text = stt.listen_once()
    print("音声認識完了:", user_text)

    llm = LLM()
    print("LLMで応答を生成中...")
    resp = llm.generate_text(user_text, "短く答えて")
    print("ハロ:", resp)
