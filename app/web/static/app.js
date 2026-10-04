const page = document.body.dataset.page;
const collection = document.body.dataset.collection;
const operation = document.body.dataset.operation;

function showResult(content, type = "success") {
  const result = document.querySelector("#result");
  result.className = `result ${type}`;
  result.innerHTML = "";
  if (typeof content === "string") {
    result.textContent = content;
  } else {
    result.append(content);
  }
  requestAnimationFrame(() => result.classList.add("show"));
}

function setLoading(button, loading, activity) {
  button.disabled = loading;
  button.dataset.label ||= button.textContent;
  button.textContent = loading ? "Working…" : button.dataset.label;
  activity.hidden = !loading;
  if (loading) {
    const action = operation === "upload" ? "Indexing your file" : operation === "ask" ? "Retrieving evidence and preparing an answer" : "Searching the knowledge base";
    activity.textContent = `${action}…`;
  }
}

function apiError(data) {
  if (typeof data?.detail === "string") return data.detail;
  if (Array.isArray(data?.detail)) return data.detail.map((item) => item.msg).join(", ");
  return "The request could not be completed.";
}

function renderSearch(data) {
  const wrapper = document.createElement("div");
  if (!data.results.length) {
    wrapper.textContent = "No matching records were found. Upload and ingest data first.";
    return wrapper;
  }
  data.results.forEach((item) => {
    const element = document.createElement("article");
    element.className = "result-item";
    const title = document.createElement("strong");
    title.textContent = item.section;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${item.source_document}${item.page ? ` · page ${item.page}` : ""} · distance ${item.distance.toFixed(3)}`;
    const content = document.createElement("div");
    content.className = "content";
    const fullContent = item.content.trim();
    const excerpt = fullContent.length > 520 ? `${fullContent.slice(0, 520).trimEnd()}…` : fullContent;
    content.textContent = excerpt;
    element.append(title, meta, content);
    if (fullContent.length > 520) {
      const toggle = document.createElement("button");
      toggle.className = "text-button";
      toggle.type = "button";
      toggle.textContent = "Show full evidence";
      toggle.addEventListener("click", () => {
        const expanded = toggle.dataset.expanded === "true";
        content.textContent = expanded ? excerpt : fullContent;
        toggle.dataset.expanded = String(!expanded);
        toggle.textContent = expanded ? "Show full evidence" : "Show less";
      });
      element.append(toggle);
    }
    wrapper.append(element);
  });
  return wrapper;
}

function renderAnswer(data) {
  const wrapper = document.createElement("div");
  const answer = document.createElement("div");
  answer.className = "answer";
  answer.textContent = data.answer;
  wrapper.append(answer);
  if (data.citations.length) {
    const heading = document.createElement("strong");
    heading.textContent = "Sources";
    heading.style.display = "block";
    heading.style.marginTop = "18px";
    wrapper.append(heading);
    data.citations.forEach((citation) => {
      const source = document.createElement("div");
      source.className = "meta";
      source.textContent = `[${citation.citation_id}] ${citation.source_document} · ${citation.section}${citation.page ? ` · page ${citation.page}` : ""}`;
      wrapper.append(source);
    });
  }
  const copy = document.createElement("button");
  copy.className = "text-button copy-button";
  copy.type = "button";
  copy.textContent = "Copy answer";
  copy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(data.answer);
      copy.textContent = "Copied";
      window.setTimeout(() => { copy.textContent = "Copy answer"; }, 1600);
    } catch {
      copy.textContent = "Copy unavailable";
    }
  });
  wrapper.append(copy);
  return wrapper;
}

function addActivityMessage(form) {
  const activity = document.createElement("p");
  activity.className = "activity";
  activity.hidden = true;
  activity.setAttribute("aria-live", "polite");
  form.querySelector("button").after(activity);
  return activity;
}

function enhanceFileInput(form) {
  const input = form.querySelector("input[type=file]");
  if (!input) return;
  const status = document.createElement("p");
  status.className = "file-status";
  status.textContent = "Choose a file to begin.";
  input.after(status);
  input.addEventListener("change", () => {
    const file = input.files[0];
    status.textContent = file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB ready to index` : "Choose a file to begin.";
  });
}

function addQuerySuggestions(form) {
  if (operation === "upload") return;
  const query = form.querySelector("textarea");
  const suggestions = collection === "policies"
    ? ["What is the travel reimbursement policy?", "Who approves cyber safety policy?", "What is the leave policy?"]
    : ["Who works in Finance?", "Find people in Operations", "Who has Python experience?"];
  const group = document.createElement("div");
  group.className = "suggestions";
  group.setAttribute("aria-label", "Example queries");
  suggestions.forEach((suggestion) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "suggestion";
    chip.textContent = suggestion;
    chip.addEventListener("click", () => {
      query.value = suggestion;
      query.focus();
    });
    group.append(chip);
  });
  query.after(group);
}

if (page === "operation") {
  const form = document.querySelector("#operation-form");
  const button = form.querySelector("button");
  const activity = addActivityMessage(form);
  enhanceFileInput(form);
  addQuerySuggestions(form);
  form.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    setLoading(button, true, activity);
    try {
      let response;
      if (operation === "upload") {
        const file = form.querySelector("input[type=file]").files[0];
        if (!file) throw new Error("Choose a file before uploading.");
        const formData = new FormData();
        formData.append("file", file);
        response = await fetch(`/v1/${collection}/upload`, { method: "POST", body: formData });
      } else {
        const query = form.querySelector("textarea").value.trim();
        const limit = Number(form.querySelector("input[type=number]").value);
        if (!query) throw new Error("Enter a question or search query.");
        response = await fetch(`/v1/${collection}/${operation}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query, limit }),
        });
      }
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(apiError(data));
      if (operation === "upload") {
        showResult(`Indexed ${data.records_indexed} ${collection === "policies" ? "policy chunks" : "employee records"} from ${data.filename}.`);
      } else if (operation === "search") {
        showResult(renderSearch(data), "evidence");
      } else {
        showResult(renderAnswer(data), "evidence");
      }
    } catch (error) {
      showResult(error.message, "error");
    } finally {
      setLoading(button, false, activity);
    }
  });
}
