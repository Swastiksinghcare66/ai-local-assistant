import { useEffect, useRef, useState } from "react";

function App() {
  const [sessionId, setSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [latency, setLatency] = useState(null);

  const bottomRef = useRef(null);

  useEffect(() => {
    startSession();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({
      behavior: "smooth",
    });
  }, [messages]);

  async function startSession() {
    try {
      const response = await fetch("/api/session/start", {
        method: "POST",
      });

      const data = await response.json();

      setSessionId(data.session_id);

      setMessages([
        {
          role: "assistant",
          content: "ConAI is engaged.",
        },
      ]);

      setLatency(null);
    } catch (error) {
      console.error(error);
    }
  }

  async function endSession() {
    if (!sessionId) return;

    try {
      await fetch("/api/session/end", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          session_id: sessionId,
        }),
      });

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: "Session archived.",
        },
      ]);

      setSessionId(null);
      setLatency(null);
    } catch (error) {
      console.error(error);
    }
  }

  async function newChat() {
    if (sessionId) {
      await endSession();
    }

    await startSession();
  }

  async function sendMessage() {
    const text = input.trim();

    if (!text || loading) return;

    let activeSession = sessionId;

    if (!activeSession) {
      const response = await fetch("/api/session/start", {
        method: "POST",
      });

      const data = await response.json();

      activeSession = data.session_id;
      setSessionId(activeSession);
    }

    setMessages((previous) => [
      ...previous,
      {
        role: "user",
        content: text,
      },
    ]);

    setInput("");
    setLoading(true);

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          session_id: activeSession,
          message: text,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Request failed");
      }

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: data.response,
        },
      ]);

      setLatency(data.inference_time);
    } catch (error) {
      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content: "Unable to reach ConAI.",
        },
      ]);

      console.error(error);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  }

  return (
    <div className="flex h-screen bg-neutral-950 text-white">
      <aside className="flex w-72 flex-col border-r border-neutral-800 bg-neutral-900 p-5">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold">ConAI</h1>
          <p className="mt-1 text-xs text-emerald-400">
            ● ENGAGED
          </p>
        </div>

        <button
          onClick={newChat}
          className="mb-3 rounded-lg border border-neutral-700 bg-neutral-800 px-4 py-3 text-left hover:bg-neutral-700"
        >
          + New Chat
        </button>

        <button
          onClick={endSession}
          className="rounded-lg border border-neutral-800 px-4 py-3 text-left text-neutral-400 hover:bg-neutral-800"
        >
          End Chat
        </button>

        <div className="mt-auto text-xs text-neutral-500">
          <p className="mb-1">Session</p>
          <p className="break-all">
            {sessionId || "No active session"}
          </p>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-20 items-center justify-between border-b border-neutral-800 px-8">
          <div>
            <h2 className="font-medium">ConAI</h2>
            <p className="text-xs text-neutral-500">
              Local AI Research Assistant
            </p>
          </div>

          <div className="text-xs text-neutral-400">
            {loading
              ? "Thinking..."
              : latency
                ? `Inference ${latency.toFixed(2)}s`
                : "Ready"}
          </div>
        </header>

        <section className="flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-4xl flex-col gap-6 px-8 py-10">
            {messages.map((message, index) => (
              <div
                key={index}
                className={
                  message.role === "user"
                    ? "flex justify-end"
                    : "flex justify-start"
                }
              >
                <div
                  className={
                    message.role === "user"
                      ? "max-w-[75%] rounded-2xl bg-neutral-100 px-5 py-3 text-neutral-950"
                      : "max-w-[75%] rounded-2xl border border-neutral-800 bg-neutral-900 px-5 py-3 text-neutral-100"
                  }
                >
                  <p className="whitespace-pre-wrap leading-7">
                    {message.content}
                  </p>
                </div>
              </div>
            ))}

            {loading && (
              <div className="flex justify-start">
                <div className="rounded-2xl border border-neutral-800 bg-neutral-900 px-5 py-3 text-neutral-400">
                  Thinking...
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>
        </section>

        <footer className="border-t border-neutral-800 p-5">
          <div className="mx-auto flex max-w-4xl gap-3">
            <textarea
              value={input}
              onChange={(event) =>
                setInput(event.target.value)
              }
              onKeyDown={handleKeyDown}
              placeholder="Message ConAI..."
              rows={1}
              className="min-h-14 flex-1 resize-none rounded-xl border border-neutral-700 bg-neutral-900 px-5 py-4 outline-none focus:border-neutral-500"
            />

            <button
              onClick={sendMessage}
              disabled={loading}
              className="rounded-xl bg-white px-7 font-medium text-black disabled:opacity-40"
            >
              Send
            </button>
          </div>

          <p className="mx-auto mt-2 max-w-4xl text-center text-xs text-neutral-600">
            Enter to send · Shift + Enter for newline
          </p>
        </footer>
      </main>
    </div>
  );
}

export default App;