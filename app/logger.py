"""
ConAI Logging System
"""

from pathlib import Path
from datetime import datetime


class Logger:

    def __init__(self):

        # Create logs directory if it doesn't exist
        self.log_dir = Path("logs")
        self.log_dir.mkdir(exist_ok=True)

        # Log files
        self.session_log = self.log_dir / "session.log"
        self.error_log = self.log_dir / "error.log"

    def log(
        self,
        user_message: str,
        assistant_message: str,
        model: str,
        inference_time: float,
        context_size: int,
    ):

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        log_entry = f"""
============================================================
Time            : {timestamp}

Model           : {model}

Inference Time  : {inference_time:.2f} sec

Context Size    : {context_size} messages

------------------------------------------------------------

User

{user_message}

------------------------------------------------------------

Assistant

{assistant_message}

============================================================


"""

        with open(self.session_log, "a", encoding="utf-8") as file:
            file.write(log_entry)

    def log_error(self, error: str, traceback_text: str):

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        error_entry = f"""
============================================================
Time            : {timestamp}

Error

{error}

------------------------------------------------------------

Traceback

{traceback_text}

============================================================


"""

        with open(self.error_log, "a", encoding="utf-8") as file:
            file.write(error_entry)