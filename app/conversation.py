class Conversation:

    def __init__(self):
        self.messages = []

    def add_user(self, text):
        self.messages.append(
            {
                "role": "user",
                "content": text,
            }
        )

    def add_assistant(self, text):
        self.messages.append(
            {
                "role": "assistant",
                "content": text,
            }
        )

    def get_messages(self):
        return self.messages

    def clear(self):
        self.messages.clear()

    def message_count(self):
        return len(self.messages)


    def user_message_count(self):
        return sum(
            1
            for message in self.messages
            if message["role"] == "user"
        )


    def assistant_message_count(self):
        return sum(
            1
            for message in self.messages
            if message["role"] == "assistant"
        )
    # -------------------------
    # Statistics
    # -------------------------

    def message_count(self):
        return len(self.messages)

    def user_message_count(self):
        return sum(
            1 for message in self.messages
            if message["role"] == "user"
        )

    def assistant_message_count(self):
        return sum(
            1 for message in self.messages
            if message["role"] == "assistant"
        )