const page = document.body.dataset.page;
const collection = document.body.dataset.collection;
const operation = document.body.dataset.operation;

function setupSidebar() {
  const nav = document.querySelector(".nav");
  if (!nav) return;
  const isHome = page === "home";
  const isCompliance = document.body.dataset.agent === "compliance";
  const isIngest = operation === "upload";
  nav.setAttribute("aria-label", "Primary navigation");
  nav.innerHTML = `<a class="${isHome ? "active" : ""}" href="/ui/">Knowledge Agent</a><a class="${isCompliance ? "active" : ""}" href="/ui/compliance.html">Compliance Agent</a><details class="nav-group"${isIngest ? " open" : ""}><summary>Ingest Docs</summary><div><a class="${collection === "policies" && isIngest ? "active" : ""}" href="/ui/policies-upload.html">Policy</a><a class="${collection === "employees" && isIngest ? "active" : ""}" href="/ui/employees-upload.html">Employee Data</a></div></details>`;
  const ingestMenu = nav.querySelector(".nav-group");
  ingestMenu.addEventListener("pointerenter", () => { ingestMenu.open = true; });
  ingestMenu.addEventListener("pointerleave", () => { ingestMenu.open = false; });
  ingestMenu.addEventListener("focusin", () => { ingestMenu.open = true; });
  ingestMenu.addEventListener("focusout", (event) => {
    if (!ingestMenu.contains(event.relatedTarget)) ingestMenu.open = false;
  });
}

setupSidebar();

function setupSourcePicker() {
  const dialog = document.querySelector("#source-picker");
  const trigger = document.querySelector("#source-picker-trigger");
  if (!dialog || !trigger) return;
  trigger.addEventListener("click", () => dialog.showModal());
  dialog.querySelector("[data-close-source-picker]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });
}

setupSourcePicker();

function appendChatMessage(content, sender = "assistant", type = "evidence") {
  const thread = document.querySelector(".chat-thread");
  if (!thread) return;
  const message = document.createElement("article");
  message.className = `chat-message chat-message-${sender}${type === "error" ? " chat-message-error" : ""}`;
  if (typeof content === "string") {
    message.textContent = content;
  } else {
    message.append(content);
  }
  thread.append(message);
  if (sender === "assistant") {
    requestAnimationFrame(() => {
      message.scrollIntoView({ behavior: "smooth", block: "end" });
    });
  }
}

function animateDisclosure(details) {
  const summary = details.querySelector("summary");
  if (!summary) return;
  summary.addEventListener("click", (event) => {
    event.preventDefault();
    if (details.dataset.animating === "true") return;
    const startWidth = details.getBoundingClientRect().width;
    const opening = !details.open;
    if (opening) details.open = true;
    let endWidth = details.getBoundingClientRect().width;
    if (!opening) {
      details.open = false;
      endWidth = details.getBoundingClientRect().width;
      details.open = true;
    }
    details.dataset.animating = "true";
    details.style.flexBasis = `${startWidth}px`;
    details.style.overflow = "hidden";
    const animation = details.animate(
      { flexBasis: [`${startWidth}px`, `${endWidth}px`] },
      { duration: 220, easing: "cubic-bezier(.2, .8, .2, 1)" },
    );
    animation.onfinish = () => {
      if (!opening) details.open = false;
      details.style.flexBasis = "";
      details.style.overflow = "";
      delete details.dataset.animating;
    };
  });
}

function setupChatRoom() {
  if (operation !== "ask") return;
  const main = document.querySelector("main.page");
  const panel = main?.querySelector(".panel");
  const form = panel?.querySelector("#operation-form");
  const result = panel?.querySelector("#result");
  if (!main || !panel || !form || !result) return;
  form.querySelector(".inline")?.remove();
  const hrAccess = form.querySelector(".hr-access");
  if (hrAccess) {
    const hrKeyInput = hrAccess.querySelector("#hr-api-key");
    const hrSummary = hrAccess.querySelector("summary");
    if (hrSummary) hrSummary.textContent = "HR access for compensation data";
    hrKeyInput?.setAttribute("aria-label", "Authorized HR API key");
    hrKeyInput?.setAttribute("placeholder", "Paste authorized API key");
    const hrNote = hrAccess.querySelector("p");
    if (hrNote) hrNote.textContent = "For authorized HR users. Your key is used once and never stored.";
    if (hrNote && hrKeyInput) {
      const hrContent = document.createElement("div");
      hrContent.className = "hr-access-content";
      hrContent.append(hrNote, hrKeyInput);
      hrAccess.append(hrContent);
    }
    animateDisclosure(hrAccess);
  }
  const query = form.querySelector("textarea");
  const sendButton = form.querySelector("button");
  const isCompliance = document.body.dataset.agent === "compliance";
  query.placeholder = isCompliance ? "Add a review focus (optional)…" : "Ask a question…";
  sendButton.setAttribute("aria-label", "Send question");
  sendButton.innerHTML = `<svg class="send-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m21 3-7.4 18-3.7-7.3L3 10.1 21 3Z"/><path d="m9.9 13.7 4.4-4.4"/></svg>`;
  const inputRow = document.createElement("div");
  inputRow.className = "chat-input-row";
  inputRow.append(query, sendButton);
  form.prepend(inputRow);
  const subject = isCompliance ? "a PDF against your indexed policies" : collection === "employees" ? "the employee directory" : "company policies";
  const thread = document.createElement("div");
  thread.className = "chat-thread";
  thread.setAttribute("aria-live", "polite");
  const welcome = document.createElement("article");
  welcome.className = "chat-message chat-message-assistant chat-welcome";
  welcome.textContent = isCompliance
    ? "Attach a PDF and I’ll compare it against your indexed policies, then return a cited compliance review."
    : `Ask a question about ${subject}. I’ll answer using the indexed evidence and include citations.`;
  thread.append(welcome, result);
  main.classList.add("chat-page");
  const chatHeader = document.createElement("div");
  chatHeader.className = "chat-room-header";
  [main.querySelector(".breadcrumbs"), main.querySelector("h1"), main.querySelector(".lead")]
    .filter(Boolean)
    .forEach((element) => chatHeader.append(element));
  main.insertBefore(chatHeader, panel);
  const updateChatHeader = () => {
    chatHeader.classList.toggle("is-scrolled", window.scrollY > 8);
  };
  window.addEventListener("scroll", updateChatHeader, { passive: true });
  updateChatHeader();
  panel.classList.add("chat-shell");
  form.classList.add("chat-composer");
  if (isCompliance) {
    const fileInput = form.querySelector("input[type=file]");
    const fileLabel = form.querySelector('label[for="document"]');
    const fileNote = form.querySelector(".form-note");
    if (fileInput && fileLabel) {
      fileLabel.className = "attachment-button";
      fileLabel.setAttribute("aria-label", "Attach a PDF for compliance review");
      fileLabel.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>`;
      fileInput.className = "attachment-input";
      fileNote?.remove();
      inputRow.prepend(fileLabel, fileInput);
    }
  }
  panel.replaceChildren(thread, form);
}

setupChatRoom();

function showResult(content, type = "success") {
  if (operation === "ask" && document.querySelector(".chat-thread")) {
    appendChatMessage(content, "assistant", type);
    return;
  }
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
  button.dataset.label ||= button.innerHTML;
  button.innerHTML = loading ? "Working…" : button.dataset.label;
  const chatThread = operation === "ask" && document.querySelector(".chat-thread");
  if (chatThread) {
    activity.hidden = !loading;
    if (loading) {
      activity.className = "activity chat-typing";
      activity.textContent = "Finding supporting evidence…";
      chatThread.append(activity);
      requestAnimationFrame(() => { chatThread.scrollTop = chatThread.scrollHeight; });
    } else {
      activity.remove();
    }
    return;
  }
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
    meta.textContent = `${item.source_document}${item.page ? ` · page ${item.page}` : ""} · similarity ${item.score.toFixed(3)}`;
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

function renderComplianceReview(data) {
  const wrapper = document.createElement("div");
  const assessment = document.createElement("div");
  assessment.className = "answer";
  assessment.textContent = data.assessment;
  wrapper.append(assessment);
  if (data.citations.length) {
    const heading = document.createElement("strong");
    heading.textContent = "Policy evidence used";
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
  return wrapper;
}

function addActivityMessage(form) {
  const activity = document.createElement("p");
  activity.className = "activity";
  activity.hidden = true;
  activity.setAttribute("aria-live", "polite");
  const inputRow = form.querySelector(".chat-input-row");
  if (inputRow) inputRow.after(activity);
  else form.querySelector("button").after(activity);
  return activity;
}

function enhanceFileInput(form) {
  const input = form.querySelector("input[type=file]");
  if (!input) return () => {};
  const isChatAttachment = form.classList.contains("chat-composer")
    && document.body.dataset.agent === "compliance";
  const attachmentButton = form.querySelector(".attachment-button");
  const status = document.createElement("p");
  status.className = "file-status";
  status.textContent = isChatAttachment ? "No document attached." : "Choose a file to begin.";
  input.after(status);
  input.addEventListener("change", () => {
    const file = input.files[0];
    status.textContent = file
      ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(1)} MB ${isChatAttachment ? "ready to review" : "ready to index"}`
      : isChatAttachment ? "No document attached." : "Choose a file to begin.";
    attachmentButton?.classList.toggle("has-file", Boolean(file));
    if (file) attachmentButton?.setAttribute("aria-label", `Attached ${file.name}. Choose another PDF`);
    else attachmentButton?.setAttribute("aria-label", "Attach a PDF for compliance review");
  });
  return () => {
    input.value = "";
    status.textContent = isChatAttachment ? "No document attached." : "Choose a file to begin.";
    attachmentButton?.classList.remove("has-file");
    attachmentButton?.setAttribute("aria-label", "Attach a PDF for compliance review");
  };
}

function addQuerySuggestions(form) {
  if (operation === "upload" || document.body.dataset.agent === "compliance") return;
  const query = form.querySelector("textarea");
  const suggestions = document.body.dataset.agent === "compliance"
    ? ["Does our travel policy cover manager approval?", "What policy evidence supports cyber safety controls?", "Which policy defines procurement approval limits?"]
    : collection === "policies"
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
  if (form.classList.contains("chat-composer")) form.append(group);
  else query.after(group);
}

if (page === "operation") {
  const form = document.querySelector("#operation-form");
  const button = form.querySelector("button");
  const activity = addActivityMessage(form);
  const clearFileInput = enhanceFileInput(form);
  addQuerySuggestions(form);
  form.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      let response;
      if (operation === "upload") {
        const file = form.querySelector("input[type=file]").files[0];
        if (!file) throw new Error("Choose a file before uploading.");
        setLoading(button, true, activity);
        const formData = new FormData();
        formData.append("file", file);
        response = await fetch(`/v1/${collection}/upload`, { method: "POST", body: formData });
      } else if (document.body.dataset.agent === "compliance") {
        const file = form.querySelector("input[type=file]").files[0];
        if (!file) throw new Error("Choose a PDF to review.");
        const instructions = form.querySelector("textarea").value.trim();
        appendChatMessage(
          `${file.name}${instructions ? `\n${instructions}` : ""}`,
          "user",
        );
        setLoading(button, true, activity);
        const formData = new FormData();
        formData.append("file", file);
        formData.append("instructions", instructions);
        form.querySelector("textarea").value = "";
        response = await fetch("/v1/compliance/review", { method: "POST", body: formData });
      } else {
        const query = form.querySelector("textarea").value.trim();
        const limitInput = form.querySelector("input[type=number]");
        const limit = limitInput ? Number(limitInput.value) : collection === "employees" ? 50 : 10;
        if (!query) throw new Error("Enter a question or search query.");
        if (operation === "ask") {
          appendChatMessage(query, "user");
          form.querySelector("textarea").value = "";
        }
        setLoading(button, true, activity);
        const hrApiKey = form.querySelector("#hr-api-key")?.value.trim();
        const headers = { "Content-Type": "application/json" };
        if (hrApiKey) headers["X-API-Key"] = hrApiKey;
        response = await fetch(`/v1/${collection}/${operation}`, {
          method: "POST",
          headers,
          body: JSON.stringify({ query, limit }),
        });
      }
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(apiError(data));
      if (operation === "upload") {
        showResult(`Indexed ${data.records_indexed} ${collection === "policies" ? "policy chunks" : "employee records"} from ${data.filename}.`);
        if (response.status === 201) clearFileInput();
      } else if (operation === "search") {
        showResult(renderSearch(data), "evidence");
      } else if (document.body.dataset.agent === "compliance") {
        showResult(renderComplianceReview(data), "evidence");
        clearFileInput();
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
