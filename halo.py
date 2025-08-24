from llm import LLM

system_content = "これはユーザーであるみねおとあなた（ハロ）との会話です。ハロは片言で返します。（例）ハロ、わかった！"
llm = LLM()

user_text = "こんにちは"
response = llm.generate_text(user_text, system_content)
print(response)