from openai import OpenAI
from config import settings

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=settings.GROQ_API_KEY,
)


def stream_response(messages: list[dict]):
    stream = client.chat.completions.create(
        model=settings.MODEL,
        messages=messages,
        stream=True,
        temperature=settings.TEMPERATURE,
        top_p=settings.TOP_P,
    )
    for chunk in stream:
        token = chunk.choices[0].delta.content
        if token:
            yield token
