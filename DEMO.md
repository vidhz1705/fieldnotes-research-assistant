# 3–5 minute live demo plan

**Target length: about 4 minutes.** Use a terminal in the project folder and a browser. Configure either the default DuckDuckGo provider on a network that permits it, or Brave with a server-side API key as described in `README.md`. DuckDuckGo may be challenged and Brave needs a valid key. No recording or live-hosted deployment is included.

## 0:00–0:45 — Start and orient

1. Run `python server.py` and open <http://127.0.0.1:8000>.
2. Show the research question field and the live-provider badge.
3. Explain that this version always performs live search and page fetch; it has no fixture or offline research fallback.

**Say:** “Fieldnotes plans the work visibly, calls a source search and then a separate verifier, and only cites records whose fetched content passes validation. Live mode is read-only and the answer text is extracted rather than generated.”

## 0:45–2:10 — Happy path

1. Ask: **“How can cities reduce urban heat?”**
2. Submit and point out the plan and the two tool cards.
3. Inspect the source-backed finding, linked page, confidence rationale, limitations, and next steps.
4. Open the source in a new tab and check the cited passage in context.

**Say:** “The answer uses query-matching text fetched from each cited page. Token overlap is only a relevance signal, not proof of truth or authority.”

## 2:10–2:50 — No evidence / boundary

1. Ask: **“Tell me about quantum cooking on Mars.”**
2. If search succeeds with no relevant pages, show no sources, Low confidence, and the no-evidence answer.
3. If the provider returns a challenge or error, show the error in the tool trace and explain no empty-result claim is made.

**Say:** “The agent doesn't fill a gap with an invented citation or unsupported finding.”

## 2:50–3:40 — Failure path

1. Submit a question whose results include several pages.
2. Show an inaccessible or non-readable candidate reported in the `fetch_sources` trace while any verified independent page remains cited.
3. If the provider is unavailable, show its explicit search failure and no unsupported findings.

**Say:** “Malformed records, timeouts, blocked providers, and inaccessible pages are reported as tool failures; verified pages can still be retained when another candidate fails.”

## 3:40–4:00 — Close

Mention `python -m unittest discover -s tests -v` and `EVALUATION.md`. Be explicit that mocked live tests do not prove a provider is currently reachable. No recording or hosted deployment has been created.
