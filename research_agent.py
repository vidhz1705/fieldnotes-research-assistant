"""Live-web research tools with bounded, evidence-first synthesis."""

import hashlib
import html
import html.parser
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request


TOKEN_RE = re.compile(r"[a-z0-9]+")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
STOP_WORDS = {
    "about", "after", "also", "and", "are", "based", "can", "does", "for", "from",
    "give", "how", "into", "its", "me", "more", "on", "our", "please", "should",
    "that", "the", "their", "these", "this", "through", "tell", "what", "when",
    "where", "which", "with", "would", "could", "city", "cities",
}
USER_AGENT = "FieldnotesResearchAssistant/1.0 (+read-only research assistant)"
MAX_SEARCH_BYTES = 1_000_000
MAX_PAGE_BYTES = 1_500_000
MAX_RESULTS = 5


class ToolFailure(Exception):
    """A safe, user-presentable tool failure."""


def _terms(text):
    return {
        token for token in TOKEN_RE.findall(text.casefold())
        if token not in STOP_WORDS and len(token) > 2
    }


def _is_https_url(url):
    if not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
        )
    except ValueError:
        return False


def _validate_public_url(url):
    """Reject non-HTTPS and non-public destinations before fetching untrusted URLs."""
    if not _is_https_url(url):
        raise ToolFailure("Source URL must be a public HTTPS address.")
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname.rstrip(".").casefold()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
        raise ToolFailure("Private or local source hosts are not allowed.")
    try:
        addresses = {
            ipaddress.ip_address(result[4][0])
            for result in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError) as error:
        raise ToolFailure("Source host could not be resolved.") from error
    if not addresses or any(
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        for address in addresses
    ):
        raise ToolFailure("Private or non-public source hosts are not allowed.")
    return parsed


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        _validate_public_url(new_url)
        return super().redirect_request(request, response, code, message, headers, new_url)


def _request(url, *, timeout, headers=None, max_bytes=MAX_PAGE_BYTES, opener=None):
    _validate_public_url(url)
    request_headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json;q=0.9"}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers)
    http = opener or urllib.request.build_opener(SafeRedirectHandler())
    try:
        with http.open(request, timeout=timeout) as response:
            content_type = response.headers.get_content_type()
            payload = response.read(max_bytes + 1)
            if len(payload) > max_bytes:
                raise ToolFailure("Remote response exceeded the size limit.")
            if not 200 <= response.status < 300:
                raise ToolFailure("Remote service returned an unsuccessful status.")
            return response, content_type, payload
    except ToolFailure:
        raise
    except urllib.error.HTTPError as error:
        raise ToolFailure(f"Remote service returned HTTP {error.code}.") from error
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as error:
        if isinstance(error, (TimeoutError, socket.timeout)) or isinstance(
            getattr(error, "reason", None), (TimeoutError, socket.timeout)
        ):
            raise ToolFailure("Remote request timed out.") from error
        raise ToolFailure("Remote service could not be reached.") from error


class SearchHTMLParser(html.parser.HTMLParser):
    """Extract DuckDuckGo's server-rendered result links and snippets."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._active = None
        self._snippet_depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())
        if tag == "a" and "result__a" in classes:
            href = attributes.get("href", "")
            parsed = urllib.parse.urlsplit(href)
            query = urllib.parse.parse_qs(parsed.query)
            target = query.get("uddg", [href])[0]
            self._active = {
                "url": urllib.parse.unquote(target),
                "title": "",
                "snippet": "",
            }
            self.results.append(self._active)
        elif tag in {"a", "div", "td"} and "result__snippet" in classes and self.results:
            self._snippet_depth += 1

    def handle_endtag(self, tag):
        if self._snippet_depth and tag in {"a", "div", "td"}:
            self._snippet_depth = max(0, self._snippet_depth - 1)
        if tag == "a":
            self._active = None

    def handle_data(self, data):
        text = re.sub(r"\s+", " ", data).strip()
        if not text:
            return
        if self._active is not None:
            self._active["title"] += (" " if self._active["title"] else "") + text
        elif self._snippet_depth and self.results:
            self.results[-1]["snippet"] += (" " if self.results[-1]["snippet"] else "") + text


class PageTextParser(html.parser.HTMLParser):
    """Extract visible page title and paragraph-like text, skipping executable UI."""

    IGNORED = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.in_title = False
        self.ignored_depth = 0
        self.current = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag in self.IGNORED:
            self.ignored_depth += 1
        if tag in {"p", "h1", "h2", "h3", "li", "article", "main"}:
            self._flush()

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in self.IGNORED and self.ignored_depth:
            self.ignored_depth -= 1
        if tag in {"p", "h1", "h2", "h3", "li", "article", "main", "br"}:
            self._flush()

    def handle_data(self, data):
        if self.in_title:
            self.title += " " + data
        elif not self.ignored_depth:
            cleaned = re.sub(r"\s+", " ", html.unescape(data)).strip()
            if cleaned:
                self.current.append(cleaned)

    def _flush(self):
        if self.current:
            block = re.sub(r"\s+", " ", " ".join(self.current)).strip()
            if len(block) > 25:
                self.blocks.append(block)
            self.current = []

    def text(self):
        self._flush()
        return re.sub(r"\s+", " ", " ".join(self.blocks)).strip()


class LiveWebTools:
    def __init__(self, *, provider="auto", brave_api_key="", timeout=8):
        if provider not in {"auto", "duckduckgo", "brave"}:
            raise ValueError("Search provider must be auto, duckduckgo, or brave.")
        self.brave_api_key = brave_api_key.strip()
        self.provider = "brave" if provider == "auto" and self.brave_api_key else (
            "duckduckgo" if provider == "auto" else provider
        )
        if self.provider == "brave" and not self.brave_api_key:
            raise ValueError("BRAVE_SEARCH_API_KEY is required when the Brave provider is selected.")
        self.timeout = max(1.0, min(float(timeout), 20.0))
        self.mode = "live"
        self.deadline = None

    def begin_research(self):
        self.deadline = time.monotonic() + min(self.timeout * (MAX_RESULTS + 1), 50.0)

    def _request_timeout(self):
        if self.deadline is None:
            return self.timeout
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ToolFailure("The live research time budget expired.")
        return min(self.timeout, remaining)

    def search_sources(self, query):
        if self.provider == "brave":
            return self._search_brave(query)
        return self._search_duckduckgo(query)

    def _search_brave(self, query):
        endpoint = "https://api.search.brave.com/res/v1/web/search?"
        url = endpoint + urllib.parse.urlencode({"q": query, "count": MAX_RESULTS})
        _, content_type, body = _request(
            url,
            timeout=self._request_timeout(),
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self.brave_api_key,
            },
            max_bytes=MAX_SEARCH_BYTES,
        )
        if content_type != "application/json":
            raise ToolFailure("Search API returned an unexpected response type.")
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ToolFailure("Search API returned malformed JSON.") from error
        web_results = payload.get("web") if isinstance(payload, dict) else None
        results = web_results.get("results") if isinstance(web_results, dict) else None
        if not isinstance(results, list):
            raise ToolFailure("Search API response did not contain a result list.")
        candidates = []
        terms = _terms(query)
        for item in results[:MAX_RESULTS]:
            if not isinstance(item, dict):
                continue
            candidate = self._candidate(
                item.get("url"),
                item.get("title"),
                item.get("description", ""),
                terms,
            )
            if candidate:
                candidates.append(candidate)
        return candidates

    def _search_duckduckgo(self, query):
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        _, content_type, body = _request(
            url,
            timeout=self._request_timeout(),
            max_bytes=MAX_SEARCH_BYTES,
        )
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ToolFailure("Search provider returned a non-HTML response.")
        source = body.decode("utf-8", errors="replace")
        if "anomaly-modal" in source or "challenge-form" in source:
            raise ToolFailure(
                "DuckDuckGo requires an anti-bot challenge from this network. "
                "Configure BRAVE_SEARCH_API_KEY and select the Brave provider, or retry later."
            )
        parser = SearchHTMLParser()
        parser.feed(source)
        if not parser.results and "no results" not in source.casefold():
            raise ToolFailure("DuckDuckGo returned an unrecognized or malformed search page.")
        terms = _terms(query)
        candidates = []
        for item in parser.results:
            candidate = self._candidate(item["url"], item["title"], item["snippet"], terms)
            if candidate:
                candidates.append(candidate)
        return candidates[:MAX_RESULTS]

    @staticmethod
    def _candidate(url, title, snippet, query_terms):
        if not all(isinstance(value, str) for value in (url, title, snippet)):
            return None
        title = re.sub(r"\s+", " ", html.unescape(title)).strip()
        snippet = re.sub(r"\s+", " ", html.unescape(snippet)).strip()
        if not title or not snippet:
            return None
        try:
            parsed = _validate_public_url(url)
        except ToolFailure:
            return None
        normalized_url = urllib.parse.urlunsplit((
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            parsed.query,
            "",
        ))
        overlap = query_terms & set(TOKEN_RE.findall(f"{title} {snippet}".casefold()))
        if query_terms and not overlap:
            return None
        score = len(overlap) / max(len(query_terms), 1)
        source_id = hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()[:16]
        host = parsed.hostname
        organization = host[4:] if host.startswith("www.") else host
        return {
            "id": source_id,
            "url": normalized_url,
            "title": title[:240],
            "organization": organization,
            "published": "Not provided by search provider",
            "snippet": snippet[:1000],
            "score": round(score, 3),
        }

    def fetch_sources(self, candidates):
        fetched = []
        for candidate in candidates:
            source_id = candidate["id"]
            try:
                fetched.append(self._fetch_one(candidate))
            except ToolFailure as error:
                fetched.append({
                    "id": source_id,
                    "status": "error",
                    "error": str(error),
                })
        return fetched

    def _fetch_one(self, candidate):
        response, content_type, body = _request(
            candidate["url"],
            timeout=self._request_timeout(),
            headers={"Accept": "text/html,application/xhtml+xml"},
            max_bytes=MAX_PAGE_BYTES,
        )
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ToolFailure("Source did not return an HTML page.")
        charset = response.headers.get_content_charset() or "utf-8"
        try:
            page = body.decode(charset, errors="replace")
        except LookupError as error:
            raise ToolFailure("Source page declared an unsupported text encoding.") from error
        parser = PageTextParser()
        parser.feed(page)
        content = parser.text()
        if len(content) < 80:
            raise ToolFailure("Source page did not contain enough readable text.")

        query_terms = _terms(candidate.get("query", ""))
        sentences = []
        for sentence in SENTENCE_RE.split(content):
            sentence = re.sub(r"\s+", " ", sentence).strip()
            overlap = query_terms & set(TOKEN_RE.findall(sentence.casefold()))
            if len(sentence) >= 45 and (not query_terms or overlap):
                sentences.append((len(overlap) / max(len(query_terms), 1), sentence))
        sentences.sort(key=lambda item: (-item[0], len(item[1])))
        evidence = []
        evidence_scores = []
        seen = set()
        for score, sentence in sentences:
            if sentence not in seen:
                seen.add(sentence)
                evidence.append(sentence)
                evidence_scores.append(score)
            if len(evidence) == 3:
                break
        if not evidence:
            raise ToolFailure("Source page was reachable but no query-matching evidence text was extracted.")

        final_url = response.geturl()
        final_parsed = _validate_public_url(final_url)
        organization = final_parsed.hostname
        if organization.startswith("www."):
            organization = organization[4:]
        return {
            "id": candidate["id"],
            "title": (parser.title.strip() or candidate["title"])[:240],
            "organization": organization,
            "url": final_url,
            "published": "Publication date not reliably identified",
            "summary": " ".join(evidence),
            "topics": "",
            "search_score": candidate["score"],
            "evidence_score": max(evidence_scores, default=0),
            "evidence_basis": "Extracted from the fetched page; verify in context.",
            "search_provider": self.provider,
        }


class ResearchAgent:
    def __init__(
        self,
        *,
        search_provider="auto",
        brave_api_key="",
        timeout=8,
    ):
        self.tools = LiveWebTools(
            provider=search_provider,
            brave_api_key=brave_api_key,
            timeout=timeout,
        )
        self.mode = "live"

    def research(self, question):
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Enter a research question.")
        question = question.strip()
        if len(question) > 500:
            raise ValueError("Question must be 500 characters or fewer.")
        if self.mode == "live":
            self.tools.begin_research()

        plan = [
            {"step": "Identify the question's main terms and relevant evidence needs.", "status": "done"},
            {
                "step": "Search the live web for relevant evidence.",
                "status": "in_progress",
            },
            {"step": "Fetch source pages and validate readable, query-relevant content.", "status": "pending"},
            {"step": "Filter evidence and synthesize only supported claims.", "status": "pending"},
        ]
        trace = []
        limitations = []
        limitations.append(
            f"Live search uses {self.tools.provider}; extracted page text and dates may be incomplete."
        )

        candidates = []
        search_failed = False
        try:
            candidates = self.tools.search_sources(question)
            if not isinstance(candidates, list):
                raise ToolFailure("Source search returned malformed data; expected a list.")
            candidate_ids = self._validate_candidates(candidates, require_urls=self.mode == "live")
            trace.append({
                "tool": "search_sources",
                "purpose": "Find potentially relevant evidence.",
                "provider": self.tools.provider,
                "status": "success",
                "result_count": len(candidates),
                "candidate_ids": candidate_ids,
            })
        except ToolFailure as error:
            search_failed = True
            limitations.append(str(error))
            trace.append({
                "tool": "search_sources",
                "purpose": "Find potentially relevant evidence.",
                "provider": self.tools.provider,
                "status": "error",
                "error": str(error),
                "result_count": 0,
            })
            candidates = []
            candidate_ids = []
        plan[1]["status"] = "error" if search_failed else "done"
        plan[2]["status"] = "in_progress"

        fetched = None
        try:
            fetched = self.tools.fetch_sources(
                [{**candidate, "query": question} for candidate in candidates],
            )
            if not isinstance(fetched, list):
                raise ToolFailure("Source verifier returned malformed data; expected a list.")
            verified_sources, fetch_errors = self._validate_fetched(
                candidate_ids,
                fetched,
                require_scores=self.mode == "live",
            )
            if fetch_errors:
                limitations.extend(f"Source {item['id']}: {item['error']}" for item in fetch_errors)
                fetch_status = "partial" if verified_sources else "error"
            else:
                fetch_status = "success"
            trace.append({
                "tool": "fetch_sources",
                "purpose": "Fetch pages and verify evidence before citation.",
                "provider": self.tools.provider,
                "status": fetch_status,
                "result_count": len(verified_sources),
                "source_ids": [source["id"] for source in verified_sources],
                "errors": fetch_errors,
            })
        except ToolFailure as error:
            verified_sources = []
            limitations.append(str(error))
            trace.append({
                "tool": "fetch_sources",
                "purpose": "Fetch pages and verify evidence before citation.",
                "provider": self.tools.provider,
                "status": "error",
                "error": str(error),
                "result_count": 0,
                "errors": [],
            })
        plan[2]["status"] = "done" if verified_sources or not candidate_ids else "error"

        evidence = [
            {
                "id": item["id"],
                "title": item["title"],
                "organization": item["organization"],
                "url": item["url"],
                "published": item["published"],
                "summary": item["summary"],
                **(
                    {
                        "search_score": item["search_score"],
                        "evidence_score": item["evidence_score"],
                    }
                    if self.mode == "live" else {}
                ),
                **(
                    {
                        "evidence_basis": item["evidence_basis"],
                        "search_provider": item["search_provider"],
                    }
                    if self.mode == "live" else {}
                ),
            }
            for item in verified_sources
        ]
        if search_failed or (candidate_ids and not verified_sources):
            short_answer = "I could not produce a verified answer because the search or source-fetch tools failed."
            confidence, confidence_reason = "Low", "No usable source content passed validation."
            limitations.append("No unverified search result or inaccessible page was used to support a finding.")
        elif not evidence:
            short_answer = "The search did not return sources with enough verified evidence to answer this question."
            confidence, confidence_reason = "Low", "No relevant, accessible source content was retrieved."
            limitations.append("No relevant evidence was verified.")
        else:
            short_answer = self._synthesize(evidence)
            confidence, confidence_reason = self._confidence(
                evidence,
                incomplete=len(fetch_errors) > 0,
            )
            if len(evidence) < len(candidates):
                limitations.append("One or more search results were inaccessible or lacked query-relevant extracted text.")
            if len({self._domain(source["url"]) for source in evidence}) < 2:
                limitations.append("Evidence comes from fewer than two distinct source domains.")

        findings = [
            {"claim": item["summary"], "source_ids": [item["id"]]}
            for item in evidence
        ]
        plan[3]["status"] = "done"
        return {
            "question": question,
            "mode": self.mode,
            "search_provider": self.tools.provider,
            "plan": plan,
            "tools": trace,
            "short_answer": short_answer,
            "key_findings": findings,
            "sources": evidence,
            "confidence": confidence,
            "confidence_reason": confidence_reason,
            "limitations_assumptions": limitations,
            "next_steps": self._next_steps(evidence, trace),
        }

    @staticmethod
    def _validate_candidates(candidates, require_urls=False):
        candidate_ids = []
        for candidate in candidates:
            if (
                not isinstance(candidate, dict)
                or not isinstance(candidate.get("id"), str)
                or not candidate["id"]
                or not isinstance(candidate.get("score"), (int, float))
                or isinstance(candidate.get("score"), bool)
                or not 0 <= candidate["score"] <= 1
            ):
                raise ToolFailure("Source search returned malformed candidate data; results were not trusted.")
            if candidate.get("url") is not None and not isinstance(candidate["url"], str):
                raise ToolFailure("Source search returned an invalid source URL.")
            if require_urls and (
                not _is_https_url(candidate.get("url"))
            ):
                raise ToolFailure("Live search returned a candidate without an HTTPS source URL.")
            candidate_ids.append(candidate["id"])
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ToolFailure("Source search returned duplicate candidate IDs; results were not trusted.")
        return candidate_ids

    @staticmethod
    def _validate_fetched(expected_ids, fetched, require_scores=False):
        by_id = {}
        errors = []
        for item in fetched:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                raise ToolFailure("Source verifier returned a malformed record; evidence was not trusted.")
            if item["id"] in by_id:
                raise ToolFailure("Source verifier returned duplicate IDs; evidence was not trusted.")
            by_id[item["id"]] = item
        if set(by_id) != set(expected_ids):
            raise ToolFailure("Source verifier omitted or changed candidate IDs; evidence was not trusted.")

        verified = []
        for source_id in expected_ids:
            item = by_id[source_id]
            if item.get("status") == "error":
                if not isinstance(item.get("error"), str) or not item["error"]:
                    raise ToolFailure("Source verifier returned an invalid per-source error.")
                errors.append({"id": source_id, "error": item["error"]})
                continue
            required = ("title", "organization", "url", "published", "summary")
            if any(not isinstance(item.get(key), str) or not item[key].strip() for key in required):
                raise ToolFailure("Source verifier returned incomplete source metadata.")
            for score_name in ("search_score", "evidence_score"):
                score = item.get(score_name)
                if require_scores and (
                    not isinstance(score, (int, float))
                    or isinstance(score, bool)
                    or not 0 <= score <= 1
                ):
                    raise ToolFailure("Source verifier returned an invalid relevance score.")
                if score is not None and (
                    not isinstance(score, (int, float))
                    or isinstance(score, bool)
                    or not 0 <= score <= 1
                ):
                    raise ToolFailure("Source verifier returned an invalid relevance score.")
            if not _is_https_url(item["url"]):
                raise ToolFailure("Source verifier returned a non-HTTPS citation.")
            verified.append(item)
        return verified, errors

    @staticmethod
    def _synthesize(evidence):
        # Findings are source text, not model-generated claims.
        summaries = [source["summary"] for source in evidence]
        if len(summaries) == 1:
            return summaries[0]
        return "Across the verified sources: " + " ".join(summaries)

    def _confidence(self, evidence, incomplete=False):
        domains = {self._domain(source["url"]) for source in evidence}
        search_scores = [source.get("search_score", 0) for source in evidence]
        evidence_scores = [source.get("evidence_score", 0) for source in evidence]
        mean_search_score = sum(search_scores) / len(search_scores)
        mean_evidence_score = sum(evidence_scores) / len(evidence_scores)
        if (
            not incomplete
            and len(evidence) >= 3
            and len(domains) >= 2
            and mean_search_score >= 0.35
            and mean_evidence_score >= 0.35
        ):
            return "Moderate to high", (
                "At least three pages yielded query-matching text across two or more domains, with search-result overlap and extracted-text overlap averaging at least 0.35; this heuristic is not a probability."
            )
        if (
            len(evidence) >= 2
            and len(domains) >= 2
            and mean_search_score >= 0.25
            and mean_evidence_score >= 0.25
        ):
            return "Moderate", (
                (
                    "Some candidate pages were unavailable, so confidence is capped at Moderate; "
                    if incomplete else ""
                )
                + "At least two accessible pages from distinct domains yielded query-matching text with search and extracted-text overlap averaging at least 0.25; source authority is not independently validated."
            )
        if len(evidence) == 1:
            return "Low", (
                "Only one page yielded query-matching text; there is no independent corroboration."
                + (" and some candidate pages were unavailable." if incomplete else "")
            )
        return "Low", (
            "The available evidence has limited source diversity or relevance"
            + (" and some candidate pages were unavailable; " if incomplete else "; ")
            + "treat it as leads to verify."
        )

    @staticmethod
    def _domain(url):
        return urllib.parse.urlsplit(url).hostname or ""

    @staticmethod
    def _next_steps(evidence, trace):
        if any(item["status"] in {"error", "partial"} for item in trace):
            return ["Retry inaccessible sources or provider errors, then verify citations in the original pages."]
        if not evidence:
            return ["Try different terms, or configure another search provider if live search is blocked."]
        return [
            "Open the cited source links and check their current guidance, context, and publication dates.",
            "For consequential decisions, consult authoritative primary sources and a qualified professional.",
        ]
