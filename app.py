"""
app.py — "Ask Qi" backend service (CMU 15-113, HW4).

A small Flask service that sits between my portfolio page and the Google Gemini API.

Why a backend is needed at all (instead of calling Gemini straight from the browser):
  * The Gemini API key must stay secret. Anything in frontend JavaScript is readable by every
    visitor, so a key shipped to the browser is a leaked key. Here it lives only in the server
    environment variable GEMINI_API_KEY and is never sent to the client.
  * Server-side validation: the browser can be edited, so length limits and history caps are
    enforced here, where the visitor can't bypass them.
  * Rate limiting: one visitor with a loop shouldn't be able to burn my free quota.
  * The persona/system prompt stays private and unmodifiable (see persona.py).

Endpoints:
  GET  /             -> service info (what this is, which endpoints exist)
  GET  /health       -> liveness check; the frontend calls it on page load to wake the free Render
                        instance and to find out whether a key is configured
  GET  /suggestions  -> starter questions for the frontend's suggestion chips
  POST /chat         -> {"message": str, "history": [{"role","content"}, ...]} -> {"reply": str, ...}

AI usage: written with Claude Code (Claude Opus 5). See prompt_log.md for the key prompts.
"""

import logging
import os
import time
from collections import defaultdict, deque

import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

from persona import STARTER_QUESTIONS, SYSTEM_PROMPT

# For local development only: if a .env file exists next to this one, load it so you don't have to
# export variables by hand. On Render there is no .env file (it's gitignored) — the real environment
# variables come from the dashboard, and load_dotenv() simply finds nothing and does nothing.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv isn't installed; environment variables still work
    pass

# ---------------------------------------------------------------------------
# Configuration — everything secret or deployment-specific comes from the
# environment, never from this file (see .env.example / README).
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest").strip()
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)

# Which websites the browser is allowed to call this service from (CORS).
DEFAULT_ORIGINS = ",".join(
    [
        "https://cathhh204.github.io",  # the deployed frontend on GitHub Pages
        "http://localhost:8000",        # local testing: python3 -m http.server 8000
        "http://127.0.0.1:8000",
        "http://localhost:5500",        # local testing: VS Code Live Server
        "http://127.0.0.1:5500",
    ]
)
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", DEFAULT_ORIGINS).split(",") if o.strip()
]

MAX_MESSAGE_CHARS = 500   # a single question
MAX_HISTORY_MSGS = 8      # previous turns kept for context (older ones are dropped)
MAX_HISTORY_CHARS = 1000  # per history entry
RATE_LIMIT_MAX = 20       # messages per IP ...
RATE_LIMIT_WINDOW = 3600  # ... per this many seconds
UPSTREAM_TIMEOUT = 45     # seconds to wait on Gemini
MAX_OUTPUT_TOKENS = 600

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": ALLOWED_ORIGINS}}, methods=["GET", "POST", "OPTIONS"])

logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Rate limiting: per-IP timestamps in memory.
# Good enough for a free single-instance deployment; it resets whenever Render
# restarts or spins the instance down. A real app would use Redis.
# ---------------------------------------------------------------------------
_hits = defaultdict(deque)


def client_ip():
    """Render runs behind a proxy, so the real client IP is the first X-Forwarded-For entry."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def check_rate_limit(ip):
    """Return (allowed, remaining, retry_after_seconds)."""
    now = time.time()
    hits = _hits[ip]
    while hits and now - hits[0] > RATE_LIMIT_WINDOW:
        hits.popleft()
    if len(hits) >= RATE_LIMIT_MAX:
        return False, 0, int(RATE_LIMIT_WINDOW - (now - hits[0])) + 1
    hits.append(now)
    return True, RATE_LIMIT_MAX - len(hits), 0


def error(message, status, **extra):
    """Every failure leaves here as JSON, so the frontend can always show a real message."""
    payload = {"error": message}
    payload.update(extra)
    return jsonify(payload), status


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
def index():
    """A human-readable service card — handy when you open the Render URL in a browser."""
    return jsonify(
        {
            "service": "Ask Qi backend",
            "description": "Chat backend for https://cathhh204.github.io — CMU 15-113 HW4.",
            "model": GEMINI_MODEL,
            "endpoints": {
                "GET /": "this message",
                "GET /health": "liveness check",
                "GET /suggestions": "starter questions for the chat UI",
                "POST /chat": {
                    "body": {
                        "message": f"required, non-empty string, max {MAX_MESSAGE_CHARS} chars",
                        "history": "optional list of {role: 'user'|'assistant', content: str}",
                    },
                    "returns": {"reply": "string", "requests_remaining": "int"},
                },
            },
            "limits": {
                "max_message_chars": MAX_MESSAGE_CHARS,
                "rate_limit": f"{RATE_LIMIT_MAX} messages per hour per IP",
            },
            "source": "https://github.com/Cathhh204/ask-qi-backend",
        }
    )


@app.get("/health")
def health():
    """
    The frontend calls this on page load. Two reasons:
      1. Render's free tier sleeps after ~15 minutes idle, and the first request takes ~50s to wake
         it. Calling /health early means the wait happens while the visitor is still reading, and
         lets the UI say "waking up" instead of looking broken.
      2. It reports whether a key is configured (a boolean — never the key itself).
    """
    return jsonify(
        {
            "status": "ok",
            "model": GEMINI_MODEL,
            "api_key_configured": bool(GEMINI_API_KEY),
        }
    )


@app.get("/suggestions")
def suggestions():
    return jsonify({"suggestions": STARTER_QUESTIONS})


@app.post("/chat")
def chat():
    # --- 1. validate the request body ------------------------------------
    # Validation comes first: a malformed request is malformed no matter how the server is
    # configured, and this is the check a visitor can actually trigger by using the UI wrong.
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return error('Send JSON like {"message": "your question"}.', 400)

    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return error("Please type a question first.", 400)
    message = message.strip()
    if len(message) > MAX_MESSAGE_CHARS:
        return error(
            f"That message is {len(message)} characters; the limit is {MAX_MESSAGE_CHARS}.", 400
        )

    raw_history = body.get("history", [])
    if not isinstance(raw_history, list):
        return error('"history" must be a list of {"role", "content"} objects.', 400)

    # Keep only well-formed entries, then only the most recent few. Trimming here (rather than
    # trusting the browser) keeps one visitor from stuffing a huge conversation into the prompt.
    contents = []
    for entry in raw_history[-MAX_HISTORY_MSGS:]:
        if not isinstance(entry, dict):
            continue
        role, content = entry.get("role"), entry.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            continue
        contents.append(
            {
                # Gemini calls the assistant turn "model"
                "role": "user" if role == "user" else "model",
                "parts": [{"text": content.strip()[:MAX_HISTORY_CHARS]}],
            }
        )
    contents.append({"role": "user", "parts": [{"text": message}]})

    # --- 2. is the server actually configured? ----------------------------
    if not GEMINI_API_KEY:
        app.logger.error("GEMINI_API_KEY is not set; refusing /chat")
        return error(
            "The chat service isn't configured yet — the server is missing its GEMINI_API_KEY.",
            503,
        )

    # --- 3. rate limit ----------------------------------------------------
    # Counted only for requests that are about to reach Gemini, since the point of the limit is
    # protecting my free API quota, not punishing typos.
    allowed, remaining, retry_after = check_rate_limit(client_ip())
    if not allowed:
        response, status = error(
            f"You've hit the limit of {RATE_LIMIT_MAX} messages per hour. "
            "Try again later, or email cchen7@andrew.cmu.edu.",
            429,
            retry_after_seconds=retry_after,
        )
        response.headers["Retry-After"] = str(retry_after)
        return response, status

    # --- 4. call Gemini ---------------------------------------------------
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
        },
    }
    # Current Gemini models "think" before answering by default, and those hidden thinking
    # tokens count against maxOutputTokens — a two-word answer can spend 50+ tokens on invisible
    # reasoning, which can eat the whole budget and return an empty reply. Earlier this only
    # checked for a "gemini-2.5" prefix, which silently stopped applying the moment the model
    # name moved on (confirmed live: gemini-2.5-flash is now retired in favor of gemini-3.8-flash).
    # This chatbot only needs short factual answers, so thinking is always turned off, regardless
    # of which model name/alias is configured.
    payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}

    try:
        upstream = requests.post(
            GEMINI_URL,
            # The key goes in a header, not the query string, so it can't end up in a URL log.
            headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
            json=payload,
            timeout=UPSTREAM_TIMEOUT,
        )
    except requests.Timeout:
        app.logger.warning("Gemini timed out after %ss", UPSTREAM_TIMEOUT)
        return error("The model took too long to answer. Please try again.", 504)
    except requests.RequestException as exc:
        app.logger.error("Gemini request failed: %s", exc)
        return error("Couldn't reach the language model. Please try again in a moment.", 502)

    if upstream.status_code != 200:
        # Log the whole upstream body server-side; send the visitor a short, safe summary.
        app.logger.error("Gemini returned %s: %s", upstream.status_code, upstream.text[:1000])
        detail = ""
        try:
            detail = (upstream.json().get("error", {}).get("message") or "")[:200]
        except ValueError:
            pass
        return error(
            f"The language model rejected the request (HTTP {upstream.status_code}). {detail}".strip(),
            502,
        )

    # --- 5. pull the text out of the response ----------------------------
    try:
        data = upstream.json()
    except ValueError:
        app.logger.error("Gemini sent non-JSON: %s", upstream.text[:500])
        return error("Got an unreadable response from the language model.", 502)

    block_reason = (data.get("promptFeedback") or {}).get("blockReason")
    if block_reason:
        return error(
            "That message was blocked by the model's safety filter "
            f"({block_reason}). Try rephrasing it.",
            400,
        )

    candidates = data.get("candidates") or []
    parts = (candidates[0].get("content") or {}).get("parts", []) if candidates else []
    reply = "".join(part.get("text", "") for part in parts).strip()

    if not reply:
        finish = candidates[0].get("finishReason") if candidates else "no candidates"
        app.logger.error("Gemini returned no text (finishReason=%s)", finish)
        return error("The model didn't return an answer. Please try asking again.", 502)

    return jsonify({"reply": reply, "model": GEMINI_MODEL, "requests_remaining": remaining})


# ---------------------------------------------------------------------------
# Make Flask's own errors JSON too, so the frontend never has to parse an HTML
# error page it wasn't expecting.
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_e):
    return error("No such endpoint. See GET / for the list.", 404)


@app.errorhandler(405)
def bad_method(_e):
    return error("Wrong HTTP method for this endpoint. /chat expects POST.", 405)


@app.errorhandler(500)
def server_error(_e):
    return error("Something broke on the server. Please try again.", 500)


if __name__ == "__main__":
    # Local development only. In production Render runs gunicorn (see render.yaml / README).
    # PORT is overridable because macOS AirPlay Receiver squats on port 5000.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
