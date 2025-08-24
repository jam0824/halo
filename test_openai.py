from openai import OpenAI, __version__ as ver
import os

print("openai.version =", ver)
print("API key set?   =", bool(os.getenv("OPENAI_API_KEY")))

client = OpenAI(timeout=30)  # タイムアウトを明示
resp = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role":"system","content":"短く答えて"}, {"role":"user","content":"テスト"}],
)
print("OK:", resp.choices[0].message.content)
