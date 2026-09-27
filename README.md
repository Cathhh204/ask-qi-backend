# Ask Qi — Backend

The backend half of **Ask Qi**, a chatbot version of me embedded in my portfolio site.
Built for **CMU 15-113 (Effective Coding with AI), HW4: Backend + Frontend**.

- **Live backend:** https://ask-qi-backend.onrender.com
- **Live frontend:** https://cathhh204.github.io/ask-qi/
- **Frontend code:** https://github.com/Cathhh204/Cathhh204.github.io/tree/main/ask-qi
- **Prompt log:** [prompt_log.md](prompt_log.md)

---

## Why this needs a backend at all

The chat answers come from Google's Gemini API, which requires an API key. A key shipped to the
browser is a leaked key — anyone can open DevTools, copy it, and spend my quota. So the browser
never sees it: the page sends a plain question to this service, and this service (running on Render,
where the key lives in an environment variable) is the only thing that ever talks to Gemini.

Three more jobs are done here for the same reason — anything enforced in browser JavaScript can be
edited away by whoever is using the browser:

| Job | Why it belongs on the server |
|---|---|
| **Secret storage** | `GEMINI_API_KEY` exists only in the server environment, never in any file in either repo. |
| **The persona / system prompt** | `persona.py` holds the instructions that make the bot answer as me and refuse off-topic requests. In frontend JS, a visitor could read it and send their own replacement. |
| **Input validation** | Message length, history shape, and history length are re-checked here, not trusted from the client. |
| **Rate limiting** | 20 messages per hour per IP, so one person in a loop can't burn my free Gemini quota. |

---

## Endpoints

Base URL: `https://ask-qi-backend.onrender.com`

### `GET /`
Service card — what this is, which endpoints exist, and the current limits. Useful for checking the
deployment by hand in a browser.

### `GET /health`
Liveness check. Returns:

```json
{ "status": "ok", "model": "gemini-2.5-flash", "api_key_configured": true }
```

`api_key_configured` is a **boolean, never the key itself** — it just tells the frontend whether the
server is able to answer at all. Render's health check is pointed at this route.

### `GET /suggestions`
The starter questions shown as clickable chips in the UI:

```json
{ "suggestions": ["What are you studying at CMU?", "..."] }
```

They're served from the backend so the wording can change without redeploying the frontend.

### `POST /chat`
The main endpoint.

**Request body** (JSON):

| Field | Type | Required | Rules |
|---|---|---|---|
| `message` | string | yes | non-empty after trimming, max **500** characters |
| `history` | array | no | `[{ "role": "user" \| "assistant", "content": string }]`. Malformed entries are dropped; only the last **8** are used, each truncated to 1000 characters. |

**Success — `200`:**

```json
{
  "reply": "I'm a second-year at CMU studying ECE and Computer Science...",
  "model": "gemini-2.5-flash",
  "requests_remaining": 19
}
```

**Errors** — every one of them is JSON with an `error` string, so the frontend never has to parse an
HTML error page:

| Status | When |
|---|---|
| `400` | no JSON body, empty `message`, `message` over 500 chars, `history` not a list, or the prompt was blocked by Gemini's safety filter |
| `429` | rate limit hit — also includes `retry_after_seconds` and a `Retry-After` header |
| `502` | Gemini rejected the request, was unreachable, or returned nothing usable |
| `503` | the server has no `GEMINI_API_KEY` configured |
| `504` | Gemini didn't respond within 45 seconds |

Try it:

```bash
curl -X POST https://ask-qi-backend.onrender.com/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"What did you build for 15-113?"}'
```

---

## How the frontend talks to this backend

The frontend is a static page on GitHub Pages ([`ask-qi/`](https://github.com/Cathhh204/Cathhh204.github.io/tree/main/ask-qi)),
so the two halves live at different origins and talk over `fetch()`:

1. **On page load** it calls `GET /health`. Render's free tier stops the instance after ~15 minutes
   of inactivity, and a cold start takes roughly 50 seconds. Calling `/health` while the visitor is
   still reading the intro absorbs that wait, and the status pill says *"Waking up the backend…"*
   instead of the page looking broken. The response's `api_key_configured` flag also lets the UI
   say "up but not configured" rather than failing mysteriously on the first question.
2. **Also on load** it calls `GET /suggestions` and renders the questions as chips. If that request
   fails, it silently falls back to three hardcoded questions — chips are a convenience, not a
   feature worth an error message.
3. **On every question** it `POST`s to `/chat` with the message and the last 8 turns of history, and
   renders `reply` into a chat bubble with `textContent` (never `innerHTML` — model output must not
   be parsed as HTML by the page). `requests_remaining` is shown as "N messages left this hour".
4. **On any failure** it reads the `error` field out of the JSON and shows it as a red bubble in the
   conversation. Timeouts, offline browsers, and CORS/connection failures are caught separately and
   explained in plain language.

**CORS:** the browser blocks cross-origin requests unless the server opts in, so `flask-cors`
allow-lists exactly the origins in `ALLOWED_ORIGINS` — `https://cathhh204.github.io` in production,
plus `localhost:8000` / `localhost:5500` for development. Requests from any other site are rejected
by the browser.

---

## Running it locally

```bash
git clone https://github.com/Cathhh204/ask-qi-backend.git
cd ask-qi-backend

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then open .env and paste your real key
python app.py
```

It prints something like `Running on http://127.0.0.1:5000`.

> **On macOS, port 5000 is taken by AirPlay Receiver** and you'll get *"Address already in use"*.
> Either disable it in System Settings → General → AirDrop & Handoff, or use another port:
> `PORT=5050 python app.py`.

### Environment variables

| Name | Required | Default | What it's for |
|---|---|---|---|
| `GEMINI_API_KEY` | **yes** | — | Google AI Studio key. Free at https://aistudio.google.com/apikey |
| `GEMINI_MODEL` | no | `gemini-2.5-flash` | Which Gemini model to call |
| `ALLOWED_ORIGINS` | no | GitHub Pages + localhost | Comma-separated list of sites allowed to call this service |
| `PORT` | no | `5000` | Local port (Render sets this itself in production) |

Locally these come from `.env`, which `python-dotenv` loads at startup and which **`.gitignore`
excludes from the repo**. In production there is no `.env` file at all — Render injects the real
values as environment variables.

### Testing the backend by itself

Before involving the frontend, check the server answers on its own:

```bash
curl -X POST http://127.0.0.1:5000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"Hello"}'
```

`./test_local.sh http://127.0.0.1:5000` runs that plus every error case (empty message, non-JSON
body, bad history, over-length message, wrong method, unknown route) and prints the status each one
returned next to the status it should have returned.

### Testing the frontend against a local backend

Serve the portfolio repo over HTTP and point the page at your local server with the `?api=` query
parameter — no need to edit any file:

```bash
# in the Cathhh204.github.io repo
python3 -m http.server 8000
# then open:
# http://localhost:8000/ask-qi/?api=http://127.0.0.1:5050
```

Open it through `http://localhost:8000`, **not** by double-clicking the `.html` file: a `file://`
page sends `Origin: null`, which isn't in the CORS allow-list, and every request will be blocked.

---

## Deploying to Render

1. Push this repo to GitHub (public).
2. On [render.com](https://render.com): **New + → Web Service → connect this repo**.
3. Settings:
   - **Runtime:** Python 3
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app --bind 0.0.0.0:$PORT`
   - **Instance type:** Free
   - **Health check path:** `/health`
4. **Environment → Add Environment Variable:** `GEMINI_API_KEY` = your key.
   This is the only place the key exists. It is set in Render's dashboard, never committed.
5. Deploy, then open the service URL — `GET /` should return the service card JSON.

`render.yaml` in this repo describes the same setup as a Blueprint (with `sync: false` on the key,
so Render prompts for it instead of storing it in the file) if you'd rather deploy that way.

---

## How secrets are handled — summary

- The Gemini API key lives in **one** place: the `GEMINI_API_KEY` environment variable on Render.
- It is read with `os.environ.get()` at startup and sent to Google in an `x-goog-api-key` **header**
  (not a query string, so it can't end up in a URL log).
- It is never returned by any endpoint, never logged, and never included in an error message —
  upstream failures are logged server-side and summarized to the client.
- `.env` and `*.env` are in `.gitignore`; only `.env.example`, which contains the placeholder
  `your-key-here`, is committed.
- The frontend repo contains no key and no secret of any kind — it only knows this service's URL.

## Known limitations

- Rate limiting is in-process memory, so it resets when Render restarts or spins the instance down,
  and wouldn't work across multiple instances. A real deployment would use Redis.
- Conversation history lives in the browser tab. Refreshing the page starts a new conversation;
  nothing is stored server-side (which also means no visitor data is retained).
- The free Render instance sleeps after ~15 minutes idle, so the first request after a quiet period
  takes ~50 seconds.
- Answers are generated by an LLM from the profile in `persona.py`. It's instructed to stick to
  those facts and to decline what it doesn't know, but it can still phrase something misleadingly —
  the page says so, and points visitors to my email for anything that matters.

## AI tools used

Built with **Claude Code (Claude Opus 5)** as an AI pair-programmer. See [prompt_log.md](prompt_log.md).
