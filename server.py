"""Local HTTP server for the standalone Fieldnotes research assistant."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from research_agent import ResearchAgent


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
SEARCH_PROVIDER = os.getenv("FIELDNOTES_SEARCH_PROVIDER", "auto").strip().casefold()
BRAVE_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY", "")
TOOL_TIMEOUT = os.getenv("FIELDNOTES_TOOL_TIMEOUT_SECONDS", "8")
logger = logging.getLogger("fieldnotes.server")

if SEARCH_PROVIDER not in {"auto", "duckduckgo", "brave"}:
    raise RuntimeError("FIELDNOTES_SEARCH_PROVIDER must be auto, duckduckgo, or brave.")
try:
    TOOL_TIMEOUT = float(TOOL_TIMEOUT)
except ValueError as error:
    raise RuntimeError("FIELDNOTES_TOOL_TIMEOUT_SECONDS must be numeric.") from error


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status, value):
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(200, {
                "status": "ok",
                "agent": "fieldnotes",
                "configured_search_provider": SEARCH_PROVIDER,
                "effective_search_provider": (
                    "brave" if SEARCH_PROVIDER == "auto" and BRAVE_API_KEY
                    else "duckduckgo" if SEARCH_PROVIDER == "auto"
                    else SEARCH_PROVIDER
                ),
                "brave_key_configured": bool(BRAVE_API_KEY),
            })
            return

        relative = "index.html" if path == "/" else unquote(path.lstrip("/"))
        target = (WEB_ROOT / relative).resolve()
        if not target.is_relative_to(WEB_ROOT.resolve()) or not target.is_file():
            self.send_error(404, "Not found")
            return

        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
        }.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urlparse(self.path).path != "/api/research":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 16_384:
                self._send_json(400, {"error": "Request body must be between 1 and 16384 bytes."})
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Request JSON must be an object.")
            if SEARCH_PROVIDER == "brave" and not BRAVE_API_KEY:
                self._send_json(503, {
                    "error": "Live search is configured for Brave, but BRAVE_SEARCH_API_KEY is not set on the server."
                })
                return
            question = payload.get("question")
            if not isinstance(question, str) or not question.strip():
                self._send_json(400, {"error": "Enter a research question."})
                return
            if len(question) > 500:
                self._send_json(400, {"error": "Question must be 500 characters or fewer."})
                return
            agent = ResearchAgent(
                search_provider=SEARCH_PROVIDER,
                brave_api_key=BRAVE_API_KEY,
                timeout=TOOL_TIMEOUT,
            )
            result = agent.research(question.strip())
            self._send_json(200, result)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
            self._send_json(400, {"error": str(error)})
        except Exception as error:
            logger.exception("Research request failed (%s)", type(error).__name__)
            self._send_json(500, {"error": "The research request failed unexpectedly."})

    def log_message(self, format_string, *args):
        print("%s - %s" % (self.address_string(), format_string % args))


if __name__ == "__main__":
    host = "127.0.0.1"
    port = 8000
    print("Research Agent: http://%s:%d" % (host, port))
    ThreadingHTTPServer((host, port), Handler).serve_forever()
