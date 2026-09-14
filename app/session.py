"""
Session Manager
---------------

Represents one running assistant session.

A session owns:
- conversation history
- runtime memory state
"""

import uuid
from datetime import datetime

from app.conversation import Conversation
from app.memory_manager import MemoryManager


class Session:

    def __init__(self):

        # Unique ID for this assistant session.
        self.session_id = str(uuid.uuid4())

        # Session start time.
        self.start_time = datetime.now()

        # Conversation storage.
        self.conversation = Conversation()

        # Runtime memory controller.
        #
        # This allows:
        #
        # session.memory.enable()
        # session.memory.disable()
        # session.memory.status()
        # session.memory.clear(...)
        #
        self.memory = MemoryManager()