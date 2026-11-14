"""Terminal version of the attuneMIND chatbot. Run with `make chat`."""
from claude_chat import chat_reply


def chatbot():
    print("Welcome to attuneMIND. Type 'exit' to end the conversation.")
    history = []
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() == 'exit':
            print("attuneMIND: Goodbye! Take care.")
            break
        if not user_input:
            continue
        history.append({'role': 'user', 'text': user_input})
        try:
            result = chat_reply(history)
        except Exception as e:
            history.pop()
            print(f"attuneMIND: Sorry, I couldn't reply just now. ({e})")
            continue
        history.append({'role': 'model', 'text': result['reply']})
        print(f"attuneMIND: {result['reply']}")


if __name__ == '__main__':
    chatbot()
