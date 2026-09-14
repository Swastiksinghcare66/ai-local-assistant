import ollama
print("="*50)
print("OLLAMA TEST")
print("type exit to end chat")
print("="*50)

while True:
    user_input = input("You: ")
    if user_input.lower() == "exit":
        break
    response = ollama.chat(
        model="qwen3:4b",
        messages=[{"role": "user", "content": user_input}])
    print(f"AI: {response['message']['content']}")