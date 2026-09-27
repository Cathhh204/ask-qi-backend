# Prompt Log — Ask Qi (HW4: Backend + Frontend)

**Tool used:** Claude Code (Claude Opus 5), working directly in both repos
(`ask-qi-backend` for the backend, `Cathhh204.github.io` for the frontend).

This was mostly one detailed brief plus a few decisions I made when Claude asked, so this log gives
the prompts as sent (translated from Chinese where noted) and what each one produced, rather than a
long back-and-forth.

---

## 1. The brief

**Prompt:** the full HW4 assignment page pasted in, followed by (translated from Chinese):

> Complete this assignment.

**What Claude did before writing anything:**

1. Read my existing portfolio repo to find the conventions it should follow — `pokedex-arena/` and
   `crossy-road/` are both course-project subfolders with their own `README.md` and `prompt_log.md`,
   linked from a card in the main page's Projects section. It matched that layout instead of
   inventing a new one.
2. Read the whole portfolio page to pull out my actual background (work, research, projects,
   coursework, sports, awards) as the factual base for the chatbot's persona, rather than making
   things up about me.
3. Checked what was available on my machine (`gh` CLI: not installed; Python 3.9; Flask: not
   installed) before planning any steps that depended on them.
4. Stopped and asked me two questions instead of guessing.

## 2. The two decisions it asked me for

**Question 1 — what should the backend do?** Options offered: an AI chatbot version of me, a
keyless game leaderboard for my two existing games, or both.
**My answer:** the AI chatbot ("Ask Qi"). It's closest to the assignment's own Carnegie Chat
example and demonstrates the point of a backend best — you *cannot* do it safely from the frontend.

**Question 2 — which LLM API key?**
**My answer:** get a free Google Gemini key from AI Studio (no credit card, free tier is plenty for
this), so Claude wrote the backend against the Gemini REST API.

Claude also pushed back on scope: the assignment explicitly warns that last semester's students
found HW4 hard because of *service glue*, not code, so we deliberately kept it to one service, one
external API, and no database.

## 3. Prompts and decisions that shaped the implementation

These are the specific things I asked for or approved along the way:

- **"Keep the interface in English so the TA can grade it easily"** (a standing preference from my
  earlier homework) — all code, comments, UI text, and documentation are in English.
- **Put the persona on the server, not in the page.** Claude proposed this and explained why: if the
  system prompt lived in frontend JS, any visitor could read it in DevTools and send a modified copy
  with their own request. `persona.py` holds both the profile facts and the behavioral rules.
- **Validate before anything else.** The first version checked for the API key first, so *every*
  bad request came back as "not configured" during local testing. I had it reorder `/chat` to:
  validate the body → check configuration → rate limit → call Gemini. A malformed request is
  malformed regardless of server configuration, and the rate limit now only counts requests that
  actually reach Gemini, since protecting the free quota is the whole point of having one.
- **Ask it to explain the failure modes, then handle each one.** Rather than a generic
  `try/except`, `/chat` returns a distinct status and a plain-language message for: bad JSON, empty
  message, over-length message, malformed history, safety-filter block, rate limit, missing key,
  upstream rejection, upstream unreachable, and timeout. Flask's own 404/405/500 pages were
  converted to JSON too, so the frontend never gets HTML where it expects JSON.
- **"Test it locally before deploying."** Claude wrote `test_local.sh`, which curls every endpoint
  and every error case and prints the status returned next to the status expected. Running it caught
  the ordering bug above. Two failures it hit and explained rather than papering over:
  - macOS AirPlay Receiver occupies port 5000, so `python app.py` fails with *"Address already in
    use"*. Documented in the README with the `PORT=5050` workaround.
  - Gemini 2.5 models "think" before answering by default, and those hidden thinking tokens count
    against `maxOutputTokens` — which can consume the whole budget and return an *empty* reply. The
    request sets `thinkingConfig.thinkingBudget = 0` for 2.5 models, with a comment saying why.
- **Verify the error paths for real, not just in theory.** Claude ran the backend with a deliberately
  invalid key to confirm a bad key produces a clean `502` with a useful message and no key leakage,
  and curled a CORS preflight from `https://cathhh204.github.io` (allowed) and from a made-up domain
  (rejected) to prove the allow-list actually works.
- **Drive the real frontend in a browser.** It opened the page against the local backend and checked
  three states end to end: backend up but unconfigured (`503` shown as a red bubble in the chat),
  backend unreachable (connection failure explained in plain language, suggestion chips silently
  falling back to hardcoded ones), and a normal exchange. A whitespace bug showed up only in the
  browser — the greeting was written into the HTML, and `white-space: pre-wrap` on the bubbles was
  preserving the HTML source's indentation — so the greeting moved into JS to go through the same
  render path as every other message.
- **Don't let model output be parsed as HTML.** Every bubble is filled with `textContent`, never
  `innerHTML`.
- **Make the wait explainable instead of hiding it.** Render's free tier sleeps; the frontend calls
  `/health` on load to start the cold boot early and shows a status pill ("waking up" / "ready" /
  "unreachable") so a 50-second first response doesn't look like a broken page.

## 4. What I did myself

- Chose the project, the API provider, and the scope.
- Created the Google AI Studio API key and set `GEMINI_API_KEY` in Render's dashboard — the key was
  never typed into any file, any prompt, or either repository.
- Created the GitHub repo and the Render web service, and verified the deployed URL end to end.
- Checked the persona facts in `persona.py` against my actual résumé before publishing.
