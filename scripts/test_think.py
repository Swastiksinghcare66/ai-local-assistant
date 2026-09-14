from ollama import Client

client = Client()

response = client.chat(
    model="qwen3:4b",
    messages=[
        {
            "role": "user",
            "content": "Say only Hello."
        }
    ],
    think=False,
)

print(response)