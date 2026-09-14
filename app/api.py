from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from uuid import uuid4
from pathlib import Path
import json
from datetime import datetime

from app.llm_client import chat
from app.session import Session
from app.context_manager import ContextManager
from app.prompt_builder import PromptBuilder


app = FastAPI(
    title="ConAI API",
    version="0.1.0"
)


# --------------------------------------------------
# Shared components
# --------------------------------------------------

context_manager = ContextManager()
prompt_builder = PromptBuilder()


# --------------------------------------------------
# Active sessions
# --------------------------------------------------

active_sessions = {}


# --------------------------------------------------
# History directory
# --------------------------------------------------

HISTORY_DIR = Path("history")
HISTORY_DIR.mkdir(exist_ok=True)


# --------------------------------------------------
# Request models
# --------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str
    message: str


class EndSessionRequest(BaseModel):
    session_id: str


# --------------------------------------------------
# Root
# --------------------------------------------------

@app.get("/")
def root():
    return {
        "system": "ConAI",
        "status": "engaged"
    }


# --------------------------------------------------
# Start session
# --------------------------------------------------

@app.post("/session/start")
def start_session():

    session_id = str(uuid4())

    active_sessions[session_id] = Session()

    return {
        "session_id": session_id,
        "status": "session_started"
    }


# --------------------------------------------------
# Chat
# --------------------------------------------------

@app.post("/chat")
def chat_endpoint(request: ChatRequest):

    session_id = request.session_id

    if session_id not in active_sessions:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )

    session = active_sessions[session_id]

    user = request.message

    # Add user message
    session.conversation.add_user(user)

    # Get context
    context = context_manager.get_context(
        session.conversation.get_messages()
    )

    # Build prompt
    prompt = prompt_builder.build(context)

    # LLM inference
    answer, inference_time = chat(prompt)

    # Save assistant response
    session.conversation.add_assistant(answer)

    return {
        "session_id": session_id,
        "response": answer,
        "inference_time": inference_time,
        "context_size": len(context)
    }


# --------------------------------------------------
# End session
# --------------------------------------------------

@app.post("/session/end")
def end_session(request: EndSessionRequest):

    session_id = request.session_id

    if session_id not in active_sessions:
        raise HTTPException(
            status_code=404,
            detail="Session not found"
        )

    session = active_sessions[session_id]

    messages = session.conversation.get_messages()

    timestamp = datetime.now().strftime(
        "%Y-%m-%d_%H-%M-%S"
    )

    history_file = (
        HISTORY_DIR
        / f"{timestamp}_{session_id}.json"
    )

    with open(
        history_file,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            {
                "session_id": session_id,
                "ended_at": datetime.now().isoformat(),
                "messages": messages
            },
            file,
            indent=4,
            ensure_ascii=False
        )

    # Remove session from active memory
    del active_sessions[session_id]

    return {
        "session_id": session_id,
        "status": "session_archived",
        "history_file": str(history_file)
    }