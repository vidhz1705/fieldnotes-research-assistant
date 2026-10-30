const form = document.querySelector("#research-form");
const questionInput = document.querySelector("#question");
const submitButton = document.querySelector("#submit");
const errorBox = document.querySelector("#error");
const emptyState = document.querySelector("#empty-state");
const results = document.querySelector("#results");
const modeBadge = document.querySelector("#mode-badge");

fetch("/api/health")
  .then((response) => {
    if (!response.ok) throw new Error(`Configuration request failed (${response.status}).`);
    return response.json();
  })
  .then((config) => {
    const provider = config.effective_search_provider || config.configured_search_provider;
    if (provider) modeBadge.append(document.createTextNode(` · ${provider}`));
  })
  .catch((error) => {
    errorBox.textContent = `Could not read server mode configuration: ${error.message}`;
    errorBox.hidden = false;
  });

document.querySelectorAll(".suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    questionInput.value = button.textContent;
    questionInput.focus();
  });
});

function addListItems(container, values) {
  container.replaceChildren();
  values.forEach((value) => {
    const item = document.createElement("li");
    item.textContent = value;
    container.append(item);
  });
}

function renderResearch(data) {
  document.querySelector("#result-question").textContent = data.question;
  document.querySelector("#short-answer").textContent = data.short_answer;
  document.querySelector("#confidence").textContent = `${data.confidence} confidence`;
  document.querySelector("#confidence-reason").textContent = data.confidence_reason || "";
  document.querySelector("#result-mode").textContent = `LIVE · ${data.search_provider}`;
  document.querySelector("#disclaimer").textContent =
    "Live search is not a guarantee of authoritative or complete research. Verify every claim in the original cited context.";

  const plan = document.querySelector("#plan");
  plan.replaceChildren();
  data.plan.forEach((step) => {
    const item = document.createElement("li");
    item.textContent = step.step;
    item.className = step.status;
    plan.append(item);
  });

  const tools = document.querySelector("#tools");
  tools.replaceChildren();
  document.querySelector(".tool-count").textContent = `· ${data.tools.length} tools`;
  data.tools.forEach((tool) => {
    const item = document.createElement("div");
    item.className = "tool-item";
    const details = document.createElement("div");
    const name = document.createElement("div");
    name.className = "tool-name";
    name.textContent = tool.tool;
    const purpose = document.createElement("div");
    purpose.className = tool.error ? "tool-error" : "tool-purpose";
    const provider = tool.provider ? ` (${tool.provider})` : "";
    const failures = (tool.errors || []).map((failure) => failure.error).join(" ");
    purpose.textContent = tool.error || `${tool.purpose}${provider} ${tool.result_count} result(s)${failures ? ` · ${failures}` : ""}`;
    details.append(name, purpose);
    const status = document.createElement("span");
    status.className = `status ${tool.status}`;
    status.textContent = tool.status;
    item.append(details, status);
    tools.append(item);
  });

  const findings = document.querySelector("#findings");
  findings.replaceChildren();
  if (!data.key_findings.length) {
    const note = document.createElement("p");
    note.className = "finding";
    note.textContent = "No findings are stated without matching, verified evidence.";
    findings.append(note);
  }
  data.key_findings.forEach((finding) => {
    const item = document.createElement("p");
    item.className = "finding";
    item.textContent = finding.claim;
    const citedSources = data.sources.filter((source) => finding.source_ids.includes(source.id));
    if (citedSources.length) {
      item.append(document.createTextNode(" "));
      citedSources.forEach((source, index) => {
        if (index) item.append(document.createTextNode(", "));
        const citation = document.createElement("a");
        citation.href = source.url;
        citation.target = "_blank";
        citation.rel = "noopener noreferrer";
        citation.textContent = `[${source.title}]`;
        item.append(citation);
      });
    }
    findings.append(item);
  });

  const sources = document.querySelector("#sources");
  sources.replaceChildren();
  document.querySelector("#source-count").textContent = `· ${data.sources.length}`;
  if (!data.sources.length) {
    const note = document.createElement("p");
    note.className = "source-summary";
    note.textContent = "No verified sources to cite for this answer.";
    sources.append(note);
  }
  data.sources.forEach((source) => {
    const card = document.createElement("article");
    card.className = "source-card";
    const title = document.createElement("a");
    title.className = "source-title";
    title.href = source.url;
    title.target = "_blank";
    title.rel = "noopener noreferrer";
    title.textContent = source.title;
    const meta = document.createElement("div");
    meta.className = "source-meta";
    meta.textContent = `${source.organization} · ${source.published}`;
    const summary = document.createElement("p");
    summary.className = "source-summary";
    summary.textContent = source.summary;
    card.append(title, meta, summary);
    sources.append(card);
  });
  addListItems(document.querySelector("#limitations"), data.limitations_assumptions);
  addListItems(document.querySelector("#next-steps"), data.next_steps);
  emptyState.hidden = true;
  results.hidden = false;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.hidden = true;
  submitButton.disabled = true;
  submitButton.textContent = "Researching…";
  emptyState.hidden = true;
  results.hidden = true;
  const controller = new AbortController();
  const requestTimeout = window.setTimeout(() => controller.abort(), 60000);
  try {
    const response = await fetch("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: questionInput.value,
      }),
      signal: controller.signal,
    });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error("The research service returned an invalid response.");
    }
    if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
    renderResearch(data);
  } catch (error) {
    errorBox.textContent = error.name === "AbortError"
      ? "Research timed out. Try again or check the live search provider."
      : error.message || "Could not reach the research service.";
    errorBox.hidden = false;
    emptyState.hidden = false;
  } finally {
    window.clearTimeout(requestTimeout);
    submitButton.disabled = false;
    submitButton.innerHTML = 'Research <span aria-hidden="true">→</span>';
  }
});
