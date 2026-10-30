# Sample output shapes

These are illustrative outputs from mocked adapters used in offline tests, not actual live search results. The example.org pages and source excerpts below are synthetic test data; do not treat them as research or factual findings.

## 1. Verified evidence (synthetic mock)

**Question:** extreme heat health

**Plan:** Identify question terms → search live web → fetch and validate pages → filter and synthesize.

**Short answer:** Extreme heat can cause serious health risks.

**Key finding:** Extreme heat can cause serious health risks. [Heat Safety]

**Source:** `Heat Safety` — example.org — `https://example.org/heat`

**Confidence:** Low — only one page yielded query-matching text; there is no independent corroboration.

**Limitations / next steps:** Mock adapter output only. In real use, open the cited page and check context, authority, and publication date.

## 2. Valid search with no matching sources

**Question:** topic with no results

**Short answer:** The search did not return sources with enough verified evidence to answer this question.

**Key findings / sources:** None.

**Confidence:** Low — no relevant, accessible source content was retrieved.

**Tool trace:** `search_sources` — success, 0 candidates; `fetch_sources` — success, 0 verified sources.

## 3. Partial fetch failure

**Question:** extreme heat health

**Short answer:** Extreme heat can cause serious health risks.

**Key finding / source:** One fetched example.org page passed validation; a second candidate timed out and is not cited.

**Confidence:** Low — only one page yielded query-matching text; there is no independent corroboration and one candidate was unavailable.

**Tool trace:** `search_sources` — success, 2 candidates; `fetch_sources` — partial, 1 verified source, 1 timeout.

**Limitations / next steps:** Retry the inaccessible source and verify the fetched passage in its original page context.
