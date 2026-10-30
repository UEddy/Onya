import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.environ["META_API_KEY"], base_url=os.environ["META_BASE_URL"])
r = client.chat.completions.create(
    model="muse-spark-1.3",
    messages=[{"role": "user", "content": "Reply with one word: ready"}],
    max_tokens=1000,
)
print("reply:", r.choices[0].message.content)
print("finish_reason:", r.choices[0].finish_reason)
print("usage:", r.usage)
