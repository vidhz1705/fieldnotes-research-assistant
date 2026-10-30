# Evaluation notes

The automated suite uses mocked provider/network responses so it is deterministic and does not require credentials or internet. It validates orchestration and evidence handling, not real provider uptime or research accuracy. A real DuckDuckGo connectivity probe in the development environment received an anti-bot challenge; a Brave key was not available, so no successful end-to-end live run is claimed.

| Query / scenario | Expected behavior | Evaluation status / limits |
|---|---|---|
| “How might extreme heat affect health?” with mocked relevant results and fetched pages | Show a plan, call both tools, return only fetched query-matching text and source citations. | Orchestration and source validation are covered by mocked tool tests; not a real web answer. |
| “Tell me about quantum cooking on Mars” with a valid empty search result | Return no citations/findings, Low confidence, and a no-evidence answer. | Tested with an empty provider response; semantic completeness is not measured. |
| Brave search response with relevant and unrelated records | Parse valid provider JSON and omit irrelevant candidates. | Offline unit tested with mocked response; no real Brave credentials/request used. |
| Empty and malformed Brave responses | A valid empty result is a no-match; invalid shape/content type is a visible search-tool failure. | Offline unit tested with mocked responses. |
| DuckDuckGo challenge or unrecognized search HTML | Report provider challenge/malformed page; do not mislabel it as no results. | Offline unit tested with mocked HTML. Earlier direct probe also encountered an anti-bot challenge on this network. |
| Fetched page contains relevant and unrelated paragraphs | Extract only query-overlapping readable sentences and cite only the fetched page. | Offline unit tested using synthetic HTML and a mocked request; not a live site. |
| Timeout, non-HTML page, or private/non-HTTPS URL | Return a safe tool failure; do not cite invalid/unavailable content. | Offline unit tested with mocked network errors and URL resolution. |
| Two live candidates, one accessible and one inaccessible | Preserve only the verified page, mark fetch partial, show limitation, and keep confidence conservative. | Offline unit tested with mocked search and fetch adapters. |
| Malformed search candidate or fetch ID mismatch | Reject the returned data and produce no unsupported citation. | Offline unit tested. |
| Empty question / more than 500 characters | Return a clear client error without running research. | API validation is implemented; direct HTTP smoke checks should be run when starting the local server. |

Automated checks live in `tests/test_research_agent.py`. They cover mocked Brave and DuckDuckGo parsing, empty/malformed provider responses, live page text filtering, timeouts, URL rejection, malformed candidates, ID mismatches, partial success, and confidence thresholds. These checks do **not** establish current provider availability or API compatibility, factual accuracy, browser compatibility, semantic recall, source authority, entailment, or production performance.

## Gaps and interpretation

- Relevance is token overlap rather than semantic retrieval; sentence overlap does not prove a claim is fully supported or accurate.
- No benchmark with coverage labels or ground-truth research answers is included.
- Live network behavior was not verified end-to-end here. Configure a Brave key or use a network where the DuckDuckGo endpoint is available, then manually verify fetched citations against their original context.
- Browser rendering and API edge cases are not covered by automated browser tests.
- Sources and pages can change; always check the linked source and local context before relying on an answer.
