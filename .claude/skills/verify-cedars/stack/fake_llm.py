"""OpenAI-compatible stand-in for the project LLM in the parity stack.

The deployed stack calls Bedrock through LiteLLM. Here a project is configured
with provider "vllm" and api_base http://fake-llm:8080, so app/llm/client.py takes
its real openai-compatible path (openai/ prefix, /v1 suffix, native JSON mode) and
lands here. No paid calls, deterministic answers.

The answer depends on the system prompt:
  - classifier (pipeline/classifier.py): positive when an excerpt mentions one of
    FAKE_LLM_POSITIVE_TERMS and no negation cue comes just before it
  - query suggestion (evaluation/query_suggest.py): a fixed JSON array
  - pattern generation (pipeline/pattern_generator.py): fixed keywords and regexes

The failure mode is read from /control/mode on every request, so
`control-cedars llm mode <mode>` changes it without a restart:
  normal | fail (HTTP 500) | empty ("{}", the Bedrock regression fixed in cef61132)
  | garbage (prose, no JSON) | slow (sleep FAKE_LLM_SLOW_SECONDS, then normal)

Every call is appended to /evidence/fake-llm-calls.jsonl.
Standard library only, so it runs on a stock python image.
"""

import json
import os
import re
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODE_FILE = os.environ.get("FAKE_LLM_MODE_FILE", "/control/mode")
CALL_LOG = os.environ.get("FAKE_LLM_CALL_LOG", "/evidence/fake-llm-calls.jsonl")
SLOW_SECONDS = float(os.environ.get("FAKE_LLM_SLOW_SECONDS", "20"))
POSITIVE_TERMS = [
    t.strip().lower()
    for t in os.environ.get("FAKE_LLM_POSITIVE_TERMS", "dvt,thromb,embol").split(",")
    if t.strip()
]
NEGATION_CUES = ("no ", "denies", "negative for", "ruled out", "rule out", "r/o", "without", "no evidence of")
EXCERPT_RE = re.compile(
    r"--- Excerpt from note (?P<note_id>\S+) \(date: (?P<date>[^)]*)\) ---\n(?P<text>.*?)"
    r"(?=\n\n--- Excerpt from note |\n\nBased on ALL excerpts|\Z)",
    re.S,
)


def current_mode() -> str:
    try:
        with open(MODE_FILE) as f:
            return f.read().strip() or "normal"
    except OSError:
        return "normal"


def find_positive(text: str) -> str | None:
    """Return the matched snippet if the text asserts a positive term."""
    lowered = text.lower()
    for term in POSITIVE_TERMS:
        for m in re.finditer(re.escape(term), lowered):
            window = lowered[max(0, m.start() - 40) : m.start()]
            if not any(cue in window for cue in NEGATION_CUES):
                return text[max(0, m.start() - 60) : m.end() + 60].strip()
    return None


def classify(user_prompt: str) -> dict:
    excerpts = [m.groupdict() for m in EXCERPT_RE.finditer(user_prompt)]
    for e in excerpts:
        snippet = find_positive(e["text"])
        if snippet:
            # The app sends datetimes ("2023-01-05T00:00:00" or "2023-01-05 00:00:00"); a real model returns the date part.
            m = re.match(r"\d{4}-\d{2}-\d{2}", e["date"] or "")
            date = m.group(0) if m else None
            return {
                "event_detected": True,
                "confidence": 0.9,
                "event_date": date,
                "reasoning": f"fake-llm: positive term in note {e['note_id']}",
                "evidence": [{"note_id": e["note_id"], "text": snippet, "note_date": date}],
            }
    return {
        "event_detected": False,
        "confidence": 0.85,
        "event_date": None,
        "reasoning": f"fake-llm: no positive term in {len(excerpts)} excerpts",
        "evidence": [],
    }


def answer(messages: list[dict]) -> tuple[str, str]:
    """Return (kind, content) for a chat request."""
    system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
    user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
    if '"event_detected"' in system:
        return "classify", json.dumps(classify(user))
    if "JSON array" in system and '"type": "include"' in system:
        return "suggest", json.dumps(
            [{"query": "DVT", "type": "include"}, {"query": "thromb*", "type": "include"}]
        )
    if '"keywords"' in system:
        return "patterns", json.dumps(
            {"keywords": ["DVT", "thrombosis"], "regex_patterns": [r"\bDVT\b"], "exclusion_patterns": []}
        )
    return "other", json.dumps({"result": "ok"})


def log_call(record: dict) -> None:
    try:
        with open(CALL_LOG, "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        if self.path in ("/healthz", "/health"):
            self._send(200, {"status": "ok", "mode": current_mode()})
        elif self.path.rstrip("/").endswith("/models"):
            self._send(200, {"object": "list", "data": [{"id": "fake-clinical", "object": "model"}]})
        else:
            self._send(404, {"error": {"message": f"no route {self.path}"}})

    def do_POST(self):  # noqa: N802
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send(404, {"error": {"message": f"no route {self.path}"}})
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        mode = current_mode()
        kind, content = answer(body.get("messages", []))
        log_call(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "mode": mode,
                "kind": kind,
                "model": body.get("model"),
                "response_format": body.get("response_format"),
            }
        )
        if mode == "fail":
            self._send(500, {"error": {"message": "fake-llm forced failure", "type": "server_error"}})
            return
        if mode == "slow":
            time.sleep(SLOW_SECONDS)
        if mode == "empty":
            content = "{}"
        elif mode == "garbage":
            content = "I am unable to classify these notes."
        prompt_tokens = sum(len(str(m.get("content", ""))) for m in body.get("messages", [])) // 4
        completion_tokens = len(content) // 4
        self._send(
            200,
            {
                "id": f"fake-{int(time.time() * 1000)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": body.get("model", "fake-clinical"),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            },
        )

    def log_message(self, fmt, *args):  # quieter container logs
        print(f"fake-llm {self.address_string()} {fmt % args}", flush=True)


if __name__ == "__main__":
    port = int(os.environ.get("FAKE_LLM_PORT", "8080"))
    print(f"fake-llm listening on :{port}, terms={POSITIVE_TERMS}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
