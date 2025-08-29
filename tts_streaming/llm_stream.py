from openai import OpenAI
client = OpenAI()  # APIキーは環境変数 OPENAI_API_KEY などで

def openai_token_stream(prompt, system_content, assistant_content):
    """
    4o-mini の出力をストリーミングで1トークン(または断片)ずつ yield する。
    """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_content},
            {"role": "assistant", "content": assistant_content},
            {"role": "user", "content": prompt},
        ],
        stream=True,
        stream_options={"include_usage": False},
    )
    for chunk in resp:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta