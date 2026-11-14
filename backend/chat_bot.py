"""Terminal version of the Mind Connect chatbot. Run with `make chat`."""
from gemini_backend import chat_reply


def chatbot():
    print("Welcome to Mind Connect. Type 'exit' to end the conversation.")
    history = []
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() == 'exit':
            print("Mind Connect: Goodbye! Take care.")
            break
        if not user_input:
            continue
        history.append({'role': 'user', 'text': user_input})
        try:
            result = chat_reply(history)
        except Exception as e:
            history.pop()
            print(f"Mind Connect: Sorry, I couldn't reply just now. ({e})")
            continue
        history.append({'role': 'model', 'text': result['reply']})
        print(f"Mind Connect: {result['reply']}")


if __name__ == '__main__':
    chatbot()
