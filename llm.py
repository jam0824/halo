# pip install --upgrade openai
from openai import OpenAI
import time

class LLM:
    def __init__(self):
        self.client = OpenAI()

    def generate_text(self, default_model, prompt, system_content, assistant_content):
        start_time = time.perf_counter()
        resp = self.client.chat.completions.create(
            model=default_model,
            # model="gpt-4o-mini",
            # model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": system_content},
                {"role": "assistant", "content": assistant_content},
                {"role": "user", "content": prompt},
            ]
        )
        end_time = time.perf_counter()
        print(f"[LLM latency] {end_time - start_time:.1f} s")
        return resp.choices[0].message.content

