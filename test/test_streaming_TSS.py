from voicevox import VoiceVoxTTS
from llm_stream import openai_token_stream

tts = VoiceVoxTTS(
    base_url="http://192.168.1.151:50021",
    speaker=89,
    max_len=80,
    queue_size=4,
)
tts.set_params(speedScale=1.0, pitchScale=0.0, intonationScale=1.0)

messages = [
    {"role": "system", "content": "あなたは日本語で親しみやすく話すナレーターです。"},
    {"role": "user", "content": "リアルタイムに自己紹介して、最後に質問を一つ投げかけてください。"},
]

system_content = "あなたは日本語で親しみやすく話すナレーターです。"
assistant_content = ""
prompt = "リアルタイムに自己紹介して、最後に質問を一つ投げかけてください。"

try:
    token_iter = openai_token_stream(prompt, system_content, assistant_content)
    tts.stream_speak(token_iter)
except KeyboardInterrupt:
    tts.stop()