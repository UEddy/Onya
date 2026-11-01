import os
import socket

import urllib3.util.connection
from dotenv import load_dotenv
from openai import OpenAI

urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET

load_dotenv(os.path.expanduser("~/.config/onya/.env"))
client = OpenAI(api_key=os.environ["BASETEN_API_KEY"], base_url=os.environ["BASETEN_BASE_URL"])
r = client.chat.completions.create(
    model="meta-models/muse-spark-open-1026",
    messages=[{"role": "user", "content": "Reply with one word: ready"}],
    max_tokens=1000,
)
print("reply:", r.choices[0].message.content)
print("finish_reason:", r.choices[0].finish_reason)
print("usage:", r.usage)
