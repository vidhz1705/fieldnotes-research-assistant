# Fieldnotes: transparent live research assistant

Fieldnotes researches a question using a live web-search provider and a separate source-fetch/verification tool. It visibly presents its plan and tool activity, then returns a structured answer with query-matched evidence, citations, confidence rationale, limitations, and next steps. It uses Python's standard library and does not depend on Nyay AI or another repository.

## Setup and run

Requires Python 3.10 or later. No package installation is required.

```powershell
python server.py
```

Open <http://127.0.0.1:8000>. The server binds to loopback and is intended for local use only. Run the tests with:

```powershell
python -m unittest discover -s tests -v
```

Live research needs internet access and an available search provider. If search is blocked or unavailable, Fieldnotes reports the failure; there is no fixture or offline research fallback.

## Search provider configuration

The default provider is DuckDuckGo's HTML search endpoint and requires no API key. It may be challenged, rate-limited, or unavailable depending on network/provider policy. Fieldnotes reports a detected challenge rather than treating it as an empty result.

Brave Search is an optional API provider. Obtain a key directly from Brave and configure it in the server environment. Keep the key server-side; never put it in browser code or commit it to GitHub.

```powershell
$env:FIELDNOTES_SEARCH_PROVIDER = "brave"
$env:BRAVE_SEARCH_API_KEY = "<your key>"
python server.py
```

To select DuckDuckGo explicitly:

```powershell
$env:FIELDNOTES_SEARCH_PROVIDER = "duckduckgo"
python server.py
```

| Variable | Default | Description |
|---|---|---|
| `FIELDNOTES_SEARCH_PROVIDER` | `auto` | `auto` chooses Brave when a key exists, otherwise DuckDuckGo; may also be `brave` or `duckduckgo`. |
| `BRAVE_SEARCH_API_KEY` | unset | Server-side Brave Search credential. Required when the provider is Brave. Never returned to the frontend. |
| `FIELDNOTES_TOOL_TIMEOUT_SECONDS` | `8` | Per-request timeout for remote search/fetch calls; clamped to 1–20 seconds. |

`GET /api/health` reports the configured/effective provider and whether a Brave key is set, but never returns the key. `POST /api/research` accepts `{ "question": "..." }`; questions are limited to 500 characters.

## Architecture and tools

- `web/` contains the responsive, dependency-free frontend. It shows the provider, research plan, two-tool trace, source-backed findings, confidence rationale, limitations, and next steps.
- `server.py` serves the UI and JSON API, reads server-only configuration, validates requests, logs unexpected server errors, and reports a missing Brave key as a service-unavailable error.
- `research_agent.py` owns orchestration, the DuckDuckGo and Brave adapters, URL and response checks, text extraction, evidence filtering, and extractive synthesis.
- `tests/` contains deterministic tests with mocked provider/network responses. Ordinary tests need neither internet nor an API key.

The agent plans the work, calls `search_sources`, filters candidates, and calls `fetch_sources` on the selected pages. Live mode validates the provider response and candidate URLs; fetches candidate pages over HTTPS; checks redirect destinations, response size/type, readable text, and query-matching sentences; then validates the fetched records before citation. If a candidate cannot be fetched or validated, its error appears in the trace and limitations. A partial fetch can return only the sources that passed; a total failure or empty evidence does not produce invented findings.

## Evidence, AI usage, and confidence

There is **no generative AI / LLM call** in this implementation. The planner is a fixed, visible sequence; search results determine the fetch inputs; and answer synthesis concatenates source text that passed validation. Each finding cites its own source. Fetched text is limited to a few extracted sentences that overlap the query terms. This design favors inspectable, literal evidence over fluent but unsupported paraphrase. It can miss relevant evidence, and lexical overlap does not establish that a passage fully answers the question or that it is true.

Confidence is categorical and heuristic, not a probability. It considers the number of accessible pages, distinct domains, average search-result token overlap, and average extracted-text overlap. A lone source is Low; a multi-source result needs at least two domains and minimum overlap to be Moderate; the higher category requires at least three pages, two domains, stronger overlap, and no known failed candidate fetches. Incomplete retrieval is disclosed and prevents the higher category. These signals do **not** score source authority, independence, truth, entailment, or freshness.

## Failure handling and bad tool results

Network calls have bounded per-request timeouts and response sizes, plus a shared 50-second orchestration budget for live search and sequential page fetches. HTTP/network failures, provider challenges, unexpected content types, malformed JSON/search pages, empty search results, inaccessible pages, unsupported encodings, and pages without enough readable or query-matching text are handled without fabricating source content. Live fetch rejects non-HTTPS, credentialed, nonstandard-port, local/private, or non-public destinations and checks redirect targets. Tool data is schema-checked; duplicate, missing, changed, or malformed IDs and invalid metadata/scores are rejected. Per-source fetch failures preserve valid independent results while being shown as partial success.

## Limitations and future improvements

- Free DuckDuckGo HTML search can be blocked; Brave requires a valid API key and account access. Live provider/network success was not established in the development environment, so configure and verify a provider where you plan to use the app.
- Page extraction is simple HTML text parsing. It misses JavaScript-rendered content, some encodings/layouts, structured metadata, publication dates, and relevant pages whose wording does not overlap the query.
- Token overlap is a weak relevance signal. Extracted sentences are verbatim text, but the app does not perform claim-level entailment, detect contradictions, assess source authority, or prove that a page is accurate.
- A source can change between search and fetch; remote content may be incomplete or misleading. Open and inspect the cited originals.
- No retries, caching, persistence, authentication, rate limiting, database, user isolation, durable observability, or browser automation are included. The server is a local app, not ready to expose to the internet.

For production, add authenticated/HTTPS hosting, stronger HTML extraction and provider adapters, robots/terms and source-licensing review, claim-to-passage entailment and contradiction checks, source-quality/freshness policies, bounded retries for transient errors, request IDs, privacy controls, and human review for consequential use. Monitor request latency, provider and fetch success/partial/error rates, empty retrievals, validation rejection rates, source/domain coverage, and citation audits. Avoid logging full questions or page text without a defined consent and retention policy.

## Why agentic?

Fieldnotes is agentic in a narrow, observable way: it makes a plan, uses the first tool's results to select inputs to the second, checks tool output, filters evidence, and changes its response based on tool failures or missing evidence. It does not browse open-endedly or take actions beyond read-only search and page fetches.

## Assignment deliverables

- [`EVALUATION.md`](EVALUATION.md): expected outcomes and the mocked/live evaluation scope.
- [`SAMPLE_OUTPUTS.md`](SAMPLE_OUTPUTS.md): illustrative outputs from mocked live-provider tests.
- [`DEMO.md`](DEMO.md): a 3–5 minute live-only demo script.
