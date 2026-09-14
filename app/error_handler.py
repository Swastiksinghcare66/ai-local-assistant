"""
ConAI Error Handler
"""

import traceback

from app.logger import Logger


class ErrorHandler:

    def __init__(self):

        self.logger = Logger()

    def handle(self, exception: Exception):

        # Show friendly message to the user
        print(f"\n[ERROR] {self.user_message(exception)}")

        # Save complete error details
        self.logger.log_error(
            error=str(exception),
            traceback_text=traceback.format_exc(),
        )

    def user_message(self, exception: Exception) -> str:

        text = str(exception).lower()

        if "connection" in text:
            return "Unable to connect to Ollama. Please make sure Ollama is running."

        if "timed out" in text:
            return "The model took too long to respond."

        if "not found" in text:
            return "The requested model was not found."

        if "permission" in text:
            return "Permission denied."

        if "file" in text:
            return "Unable to access the required file."

        return "An unexpected error occurred. Check logs/error.log for details."