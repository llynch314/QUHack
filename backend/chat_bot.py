"""Chat with AttuneMind in the terminal (same bot and system prompt as the website)."""
from gemini_backend import MODEL_NAME, generate_response


def chatbot():
    print(f"Welcome to AttuneMind! (model: {MODEL_NAME}) Type 'exit' to end the conversation.")
    history = []

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() == "exit":
            print("AttuneMind: Goodbye! Take care.")
            break

        reply = generate_response(user_input, history)
        print(f"AttuneMind: {reply}")
        history += [{"sender": "user", "text": user_input},
                    {"sender": "model", "text": reply}]


if __name__ == "__main__":
    chatbot()
