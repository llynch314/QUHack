"""Terminal version of the AttuneMIND chatbot. Run with `make chat`."""
from gemini_backend import chat_reply


def chatbot():
    print("Welcome to AttuneMIND. Type 'exit' to end the conversation.")
    history = []
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() == 'exit':
            print("AttuneMIND: Goodbye! Take care.")
            break
        if not user_input:
            continue
        history.append({'role': 'user', 'text': user_input})
        try:
            result = chat_reply(history)
        except Exception as e:
            history.pop()
            print(f"AttuneMIND: Sorry, I couldn't reply just now. ({e})")
            continue
        history.append({'role': 'model', 'text': result['reply']})
        print(f"AttuneMIND: {result['reply']}")


if __name__ == '__main__':
    chatbot()
