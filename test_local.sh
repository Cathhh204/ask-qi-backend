#!/usr/bin/env bash
# Smoke-tests every endpoint against a running server.
#   Terminal 1:  python3 app.py
#   Terminal 2:  ./test_local.sh                      (defaults to http://127.0.0.1:5000)
#                ./test_local.sh https://ask-qi-backend.onrender.com   (test the deployed one)
set -u
BASE="${1:-http://127.0.0.1:5000}"
echo "Testing $BASE"

run() {  # run <label> <expected-status> <curl args...>
  local label="$1" expected="$2"; shift 2
  local body status
  body=$(curl -s -w '\n%{http_code}' "$@")
  status=$(printf '%s' "$body" | tail -n1)
  printf '\n--- %s\n' "$label"
  printf '%s\n' "$body" | sed '$d'
  if [ "$status" = "$expected" ]; then
    printf 'status %s (expected %s)  OK\n' "$status" "$expected"
  else
    printf 'status %s (expected %s)  MISMATCH\n' "$status" "$expected"
  fi
}

run "GET / (service info)"        200 "$BASE/"
run "GET /health"                 200 "$BASE/health"
run "GET /suggestions"            200 "$BASE/suggestions"
run "GET /nope (404 as JSON)"     404 "$BASE/nope"
run "GET /chat (wrong method)"    405 "$BASE/chat"
run "POST /chat empty message"    400 -X POST "$BASE/chat" -H 'Content-Type: application/json' -d '{"message":"   "}'
run "POST /chat no JSON body"     400 -X POST "$BASE/chat" -H 'Content-Type: application/json' -d 'not json'
run "POST /chat bad history type" 400 -X POST "$BASE/chat" -H 'Content-Type: application/json' -d '{"message":"hi","history":"oops"}'
run "POST /chat too long"         400 -X POST "$BASE/chat" -H 'Content-Type: application/json' \
    -d "{\"message\":\"$(printf 'a%.0s' $(seq 1 600))\"}"
run "POST /chat real question"    200 -X POST "$BASE/chat" -H 'Content-Type: application/json' \
    -d '{"message":"What are you studying at CMU?"}'
echo
echo "Note: the last test needs GEMINI_API_KEY set on the server, otherwise it returns 503."
