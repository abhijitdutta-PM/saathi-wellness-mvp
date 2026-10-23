const state = {
  user: null,
  system: null,
  view: "dashboard",
  conversations: [],
  conversationId: null,
  recording: null,
  recordedChunks: [],
  voiceBlob: null,
  lastJournalPrompt: "",
};

const PURPOSES = ["wellbeing_processing", "ai_processing", "voice_processing"];
const PURPOSE_LABELS = {
  wellbeing_processing: "Wellbeing records",
  ai_processing: "AI buddy processing",
  voice_processing: "Voice transcription",
};
const NAV = {
  student: [
    ["dashboard", "Overview", "⌂"], ["journal", "My journal", "▤"], ["buddy", "Talk to Saathi", "◉"],
    ["knowledge", "Resource library", "⌕"], ["consent", "Privacy & consent", "◇"],
  ],
  teacher: [["dashboard", "Overview", "⌂"], ["cases", "Assigned support", "♡"], ["knowledge", "Resource library", "⌕"]],
  counsellor: [["dashboard", "Overview", "⌂"], ["cases", "Case management", "♡"], ["consent", "Consent readiness", "◇"], ["reports", "Reports", "▥"], ["knowledge", "Resource library", "⌕"], ["retention", "Retention & privacy", "◇"], ["audit", "Audit log", "≋"]],
};
const TITLES = {
  dashboard: "Overview", journal: "My journal", buddy: "Talk to Saathi", knowledge: "Resource library",
  consent: "Privacy & consent", cases: "Support cases", reports: "Reports", retention: "Retention & privacy", audit: "Audit log",
};

const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
const fmtDate = (value) => {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
};
const shortDate = (value) => {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString([], { month: "short", day: "numeric" });
};
const roleLabel = (role) => ({ student: "Student", teacher: "Teacher", counsellor: "Counsellor" }[role] || "Restricted legacy role");
const urgencyClass = (value) => value === "immediate" ? "red" : value === "human_review" ? "yellow" : "green";
const urgencyLabel = (value) => ({ immediate: "Urgent", human_review: "Human review", routine: "Routine" }[value] || value || "Open");

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  let body = options.body;
  if (body && !(body instanceof FormData) && typeof body !== "string") {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  }
  const response = await fetch(path, { ...options, headers, body, credentials: "same-origin", cache: "no-store" });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json().catch(() => ({})) : await response.text();
  if (!response.ok) {
    const message = (data && data.detail) || (typeof data === "string" ? data : `Request failed (${response.status})`);
    throw new Error(message);
  }
  return data;
}
function toast(message, type = "success") {
  const node = document.createElement("div");
  node.className = `toast ${type === "error" ? "error" : type === "success" ? "success" : ""}`;
  node.textContent = message;
  $("toast-region").appendChild(node);
  setTimeout(() => node.remove(), 4600);
}
function pageHeader(eyebrow, title, subtitle, actions = "") {
  return `<div class="page-header"><div><div class="eyebrow small-label">${escapeHtml(eyebrow)}</div><h1>${escapeHtml(title)}</h1><p>${escapeHtml(subtitle)}</p></div><div class="page-actions">${actions}</div></div>`;
}
function card(title, content, extra = "") {
  return `<section class="card card-pad ${extra}"><div class="card-top"><h2>${title}</h2></div>${content}</section>`;
}
function statCard(icon, value, label, tone = "") {
  return `<div class="card mini-stat"><div class="stat-icon ${tone}">${icon}</div><div><div class="stat-value">${escapeHtml(value)}</div><div class="stat-label">${escapeHtml(label)}</div></div></div>`;
}
function consentEffective(purpose) {
  return Boolean(state.user?.consent?.[purpose]?.effective);
}
function consentGate(copy = "Complete the required privacy and consent steps before using wellbeing features.") {
  return `<section class="card card-pad"><div class="empty-state"><div class="empty-icon">◇</div><strong>Consent required</strong><p>${escapeHtml(copy)}</p><button class="btn btn-primary" data-action="navigate" data-view="consent">Review privacy & consent</button></div></section>`;
}
function wireNavigation() {
  const items = NAV[state.user.role] || NAV.student;
  $("main-nav").innerHTML = items.map(([view, label, icon]) => `<button class="nav-item ${state.view === view ? "active" : ""}" data-action="navigate" data-view="${view}"><span class="nav-icon">${icon}</span><span>${escapeHtml(label)}</span></button>`).join("");
  document.querySelectorAll("[data-action='navigate']").forEach((btn) => btn.addEventListener("click", () => navigate(btn.dataset.view)));
}
function showLogin() {
  $("app-shell").classList.add("hidden");
  $("login-screen").classList.remove("hidden");
}
async function loadApp(user) {
  state.user = user;
  $("login-screen").classList.add("hidden");
  $("app-shell").classList.remove("hidden");
  $("school-name").textContent = user.tenant_name;
  $("user-name").textContent = user.display_name;
  $("user-role").textContent = roleLabel(user.role);
  $("user-email").textContent = user.email || "Email not available";
  $("user-avatar").textContent = (user.display_name || "S").trim().charAt(0).toUpperCase();
  $("environment-badge").textContent = user.demo_mode ? "Preview" : "School space";
  $("demo-notice").classList.toggle("hidden", !user.demo_mode);
  const queryView = new URLSearchParams(location.search).get("view");
  const options = (NAV[user.role] || NAV.student).map((i) => i[0]);
  state.view = queryView && options.includes(queryView) ? queryView : (options.includes(state.view) ? state.view : "dashboard");
  wireNavigation();
  await renderCurrentView();
}
async function navigate(view) {
  const available = (NAV[state.user?.role] || NAV.student).map((i) => i[0]);
  if (!available.includes(view)) return;
  state.view = view;
  state.conversationId = view === "buddy" ? state.conversationId : state.conversationId;
  history.replaceState({}, "", view === "dashboard" ? "/" : `/?view=${encodeURIComponent(view)}`);
  $("sidebar").classList.remove("open");
  wireNavigation();
  await renderCurrentView();
}
async function renderCurrentView() {
  $("current-page-title").textContent = TITLES[state.view] || "Overview";
  $("view-container").innerHTML = `<div class="loading-card">Loading your workspace…</div>`;
  try {
    if (state.view === "dashboard") await renderDashboard();
    else if (state.view === "journal") await renderJournal();
    else if (state.view === "buddy") await renderBuddy();
    else if (state.view === "knowledge") await renderKnowledge();
    else if (state.view === "consent") await renderConsent();
    else if (state.view === "cases") await renderCases();
    else if (state.view === "reports") await renderReports();
    else if (state.view === "retention") await renderRetention();
    else if (state.view === "audit") await renderAudit();
    bindCommonActions();
  } catch (err) {
    $("view-container").innerHTML = `<div class="message error">${escapeHtml(err.message || "Something went wrong.")}</div>`;
  }
}
function bindCommonActions() {
  document.querySelectorAll("[data-action='navigate']").forEach((btn) => btn.addEventListener("click", () => navigate(btn.dataset.view)));
  document.querySelectorAll("[data-action='journal-prompt']").forEach((btn) => btn.addEventListener("click", () => {
    state.lastJournalPrompt = btn.dataset.prompt || "";
    navigate("journal");
  }));
  document.querySelectorAll("[data-action='say']").forEach((btn) => btn.addEventListener("click", () => speakText(btn.dataset.text || "")));
}

async function renderDashboard() {
  const role = state.user.role;
  const d = await api("/api/dashboard");
  let html = "";
  if (role === "student") {
    const consentOk = state.user.can_use_wellbeing;
    const greeting = new Date().getHours() < 12 ? "Good morning" : new Date().getHours() < 17 ? "Good afternoon" : "Good evening";
    html += pageHeader("YOUR SPACE", `${greeting}, ${state.user.display_name.split(" ")[0]}`, "A little room to notice how you're doing, at your own pace.", `<button class="btn btn-primary" data-action="navigate" data-view="buddy">Talk to Saathi ↗</button>`);
    if (!consentOk) html += `<div class="notice-strip" style="margin-bottom:16px"><strong>Before you begin</strong><span>Complete the privacy and consent steps to use your journal and buddy. You can still view general resources.</span><button class="btn btn-outline btn-small" data-action="navigate" data-view="consent">Review</button></div>`;
    html += `<div class="grid two"><section class="card quote-card"><div class="quote-symbol">“</div><blockquote>${escapeHtml(d.quote?.text || "Take a pause and notice what you need today.")}</blockquote><div class="quote-author">${escapeHtml(d.quote?.author || "Saathi reflection")} <span>· ${escapeHtml(d.quote?.theme || "reflection")}</span></div><div class="quote-card-actions"><button class="btn btn-primary" data-action="journal-prompt" data-prompt="Today's reflection: ${escapeHtml(d.quote?.text || "What is on your mind today?")}">Reflect on this</button><button class="btn btn-outline" data-action="navigate" data-view="knowledge">Explore resources</button></div></section><section class="card card-pad"><div class="card-overline">A GENTLE CHECK-IN</div><h2 style="margin-top:9px;font-size:20px">What feels closest today?</h2><p class="card-sub">You don't need to pick a feeling or explain anything before you're ready.</p><div class="prompt-list"><button class="prompt-option" data-action="journal-prompt" data-prompt="Right now, I am feeling worried about…"><span class="prompt-icon">◌</span><span>Something is on my mind</span></button><button class="prompt-option" data-action="journal-prompt" data-prompt="Something that went okay today was…"><span class="prompt-icon">✳</span><span>I'd like to notice something good</span></button><button class="prompt-option" data-action="navigate" data-view="buddy"><span class="prompt-icon">♡</span><span>I'd rather talk it through</span></button></div></section></div>`;
    html += `<div class="grid three" style="margin-top:17px">${statCard("▤", consentOk ? d.journal_count : "—", "Private reflections", "lilac")}${statCard("◉", consentOk ? d.conversation_count : "—", "Buddy conversations", "blue")}${statCard("♡", d.open_support_requests, "Support requests in progress", "amber")}</div>`;
    html += `<div class="section-head"><h2>Small steps for today</h2><span>Choose what feels right</span></div><div class="grid three"><section class="card card-pad"><div class="stat-icon">◎</div><h3 style="margin-top:15px">Try a grounding pause</h3><p class="card-sub">Notice your surroundings and take a breath at a comfortable pace.</p><button class="btn btn-outline btn-small" style="margin-top:17px" data-action="navigate" data-view="knowledge">Open exercise</button></section><section class="card card-pad"><div class="stat-icon lilac">▤</div><h3 style="margin-top:15px">Write without judgement</h3><p class="card-sub">Put a thought into words. Your journal is private by default.</p><button class="btn btn-outline btn-small" style="margin-top:17px" data-action="navigate" data-view="journal">Open journal</button></section><section class="card card-pad"><div class="stat-icon amber">☼</div><h3 style="margin-top:15px">Talk to someone you trust</h3><p class="card-sub">You deserve human support as well as digital guidance.</p><button class="btn btn-outline btn-small" style="margin-top:17px" data-action="navigate" data-view="knowledge">Help-seeking tips</button></section></div>`;
    html += `<div class="notice-strip" style="margin-top:17px"><strong>Remember</strong><span>Saathi offers supportive reflection, not therapy. If you feel unsafe or need immediate help, contact a trusted adult or local emergency services. The app cannot guarantee an immediate human response.</span></div>`;
  } else if (["counsellor", "teacher"].includes(role)) {
    html += pageHeader("SCHOOL SUPPORT", `Welcome, ${state.user.display_name.split(" ")[0]}`, "Review assigned support work and make sure each case has a clear next step.");
    if (role !== "teacher") html += `<div class="grid three">${statCard("♡", d.open_cases, "Open support cases", "lilac")}${statCard("!", d.immediate_cases, "Urgent cases", "amber")}${statCard("○", d.unassigned_cases, "Unassigned cases", "blue")}</div>`;
    else html += `<div class="grid three">${statCard("♡", d.assigned_cases, "Your open assignments", "lilac")}</div>`;
    html += `<div class="grid two" style="margin-top:17px"><section class="card card-pad"><div class="card-top"><h2>Case management</h2><span class="pill blue">Restricted access</span></div><p class="card-sub">Review only the cases permitted by your school role. Acknowledge assigned cases and record the next support action.</p><button class="btn btn-primary" style="margin-top:18px" data-action="navigate" data-view="cases">Open case queue →</button></section><section class="card card-pad"><h2>Support workflow</h2><div class="activity-row"><div class="activity-icon">1</div><div><strong>Review the evidence</strong><p>Read the relevant excerpt and reason for review.</p></div></div><div class="activity-row"><div class="activity-icon">2</div><div><strong>Assign a next step</strong><p>Record a check-in, referral, or other appropriate action.</p></div></div><div class="activity-row"><div class="activity-icon">3</div><div><strong>Close the loop</strong><p>Document acknowledgement and follow-up outcomes.</p></div></div></section></div>`;
    if (d.demo_mode) html += `<div class="notice-strip" style="margin-top:17px"><strong>Preview mode</strong><span>Case notifications are not sent to a live support team unless the n8n integration and notification credentials have been configured.</span></div>`;
  }
  $("view-container").innerHTML = html;
}

async function renderJournal() {
  if (!state.user.can_use_wellbeing) {
    $("view-container").innerHTML = pageHeader("PERSONAL REFLECTION", "My journal", "Write at your own pace. Your entry is private by default.") + consentGate();
    return;
  }
  const journals = await api("/api/journals");
  const prompt = state.lastJournalPrompt; state.lastJournalPrompt = "";
  let html = pageHeader("PERSONAL REFLECTION", "My journal", "A private-by-default space to put your thoughts into words.");
  html += `<div class="grid two"><section class="card form-card"><div class="card-top"><h2>Write a reflection</h2><span class="pill green">Private by default</span></div><p class="card-sub" style="margin-bottom:17px">You can keep this just for yourself or explicitly ask the school support team to follow up.</p><form id="journal-form" class="stack"><label>Title<input id="journal-title" maxlength="180" value="${prompt ? "Daily reflection" : "My reflection"}"></label><label>Your thoughts<textarea id="journal-content" placeholder="What has been on your mind? You can start with one sentence…" required>${escapeHtml(prompt)}</textarea></label><label class="checkbox-row"><input id="journal-request-support" type="checkbox"><span><strong>I'd like a human support check-in.</strong><br>If you select this, the designated support team may see relevant information needed to respond. You can also contact a trusted adult directly.</span></label><div class="form-actions"><button class="btn btn-primary" type="submit">Save reflection</button></div><div id="journal-error" class="message error hidden"></div></form></section><section class="card card-pad"><h2>Before you write</h2><p class="card-sub">There isn't a right or wrong way to describe a feeling. You do not need to use perfect words or solve the problem right now.</p><div class="activity-row" style="margin-top:17px"><div class="activity-icon">◌</div><div><strong>Notice the feeling</strong><p>What happened, and what did you feel?</p></div></div><div class="activity-row"><div class="activity-icon">✳</div><div><strong>Notice what you need</strong><p>Rest, clarity, a boundary, or someone to listen?</p></div></div><div class="activity-row"><div class="activity-icon">♡</div><div><strong>Choose support</strong><p>You can ask a trusted person for help whenever you need it.</p></div></div><div class="notice-strip" style="margin-top:14px"><strong>Privacy boundary</strong><span>Entries may be reviewed by designated safeguarding staff if a safety concern is identified or you request support. This is not a confidential clinical service.</span></div></section></div>`;
  html += `<div class="section-head"><h2>Recent reflections</h2><span>${journals.length} saved</span></div>`;
  if (!journals.length) html += `<div class="empty-state"><div class="empty-icon">▤</div><strong>Your journal begins here</strong><p>When you're ready, save a reflection above. You can also leave this page without writing anything.</p></div>`;
  else html += `<div class="journal-grid">${journals.map((j) => `<article class="card journal-card"><h3>${escapeHtml(j.title)}</h3><div class="journal-content">${escapeHtml(j.content)}</div><div class="journal-meta"><span>${fmtDate(j.created_at)}</span>${j.request_support ? '<span class="pill blue">Support requested</span>' : '<span class="pill gray">Private entry</span>'}</div></article>`).join("")}</div>`;
  $("view-container").innerHTML = html;
  const journalForm = $("journal-form");
  if (!journalForm) return;
  journalForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = $("journal-error"); error.classList.add("hidden");
    try {
      const result = await api("/api/journals", { method: "POST", body: {
        title: $("journal-title").value || "My reflection", content: $("journal-content").value,
        request_support: $("journal-request-support").checked,
      }});
      state.lastJournalPrompt = "";
      if (result.support_request_created) toast("Your reflection was saved and a support case was recorded. The app cannot guarantee an immediate response.", "success");
      else toast("Reflection saved.", "success");
      state.user = await api("/api/me");
      await renderJournal();
    } catch (err) { error.textContent = err.message; error.classList.remove("hidden"); }
  });
}

async function openNewConversation() {
  const channel = "text";
  const c = await api("/api/conversations", { method: "POST", body: { title: "Conversation with Saathi", channel } });
  state.conversationId = c.id;
  state.view = "buddy";
  await renderBuddy();
}
async function renderBuddy() {
  if (!state.user.can_use_wellbeing) {
    $("view-container").innerHTML = pageHeader("CONVERSATION", "Talk to Saathi", "Share as much or as little as feels comfortable.") + consentGate();
    return;
  }
  state.conversations = await api("/api/conversations");
  if (!state.conversationId || !state.conversations.some((c) => c.id === state.conversationId)) {
    state.conversationId = state.conversations[0]?.id || null;
  }
  if (!state.conversationId) {
    const c = await api("/api/conversations", { method: "POST", body: { title: "Conversation with Saathi", channel: "text" } });
    state.conversationId = c.id;
    state.conversations = await api("/api/conversations");
  }
  const messages = await api(`/api/conversations/${encodeURIComponent(state.conversationId)}/messages`);
  let html = pageHeader("YOUR VIRTUAL BUDDY", "Talk to Saathi", "A supportive conversation partner. It is not a therapist, and a live human response is not guaranteed.", `<button class="btn btn-outline" id="new-conversation">＋ New chat</button>`);
  html += `<div class="notice-strip" style="margin-bottom:14px"><strong>Safety & privacy</strong><span>Messages are saved according to your school's support-record policy. Designated staff may receive limited relevant information when safety review or a support request is needed. If you need urgent help, contact a trusted adult directly.</span></div>`;
  html += `<div class="conversation-layout"><section class="card conversation-list"><div class="conversation-list-head"><h3>Recent chats</h3><span class="pill gray">${state.conversations.length}</span></div>${state.conversations.map((c) => `<button class="conversation-choice ${c.id === state.conversationId ? "active" : ""}" data-conversation-id="${c.id}"><strong>${escapeHtml(c.title)}</strong><small>${fmtDate(c.updated_at)}</small></button>`).join("")}</section><section class="card chat-card"><div class="chat-head"><div class="chat-person"><div class="buddy-avatar">✳</div><div><strong>Saathi</strong><small>Listening, one step at a time</small></div></div><span class="pill green">Supportive companion</span></div><div id="chat-body" class="chat-body">${messages.map((m) => renderMessage(m)).join("")}</div><div class="chat-form"><div id="voice-panel" class="voice-panel ${consentEffective("voice_processing") ? "" : "hidden"}"><button class="btn btn-outline btn-small" id="record-start">● Record</button><button class="btn btn-outline btn-small hidden" id="record-stop">Stop</button><p id="voice-help">Voice recording is transcribed by the configured speech provider. Raw audio is not retained by this app.</p></div><div id="voice-transcript-wrap" class="hidden"><label class="helper" for="voice-transcript">Review the transcript before sending</label><textarea id="voice-transcript" class="field" rows="3" style="margin:6px 0 8px"></textarea><div class="inline-actions"><button class="btn btn-primary btn-small" id="send-voice-transcript">Send transcript</button><button class="btn btn-quiet btn-small" id="discard-voice-transcript">Discard</button></div></div><form id="chat-form"><div class="chat-compose"><textarea id="chat-input" maxlength="6000" rows="2" placeholder="What's on your mind?" required></textarea><button class="btn btn-primary" type="submit" aria-label="Send message">Send ↗</button></div><div class="chat-bottom"><span class="chat-hint">A small thought is enough. Press Shift + Enter for a new line.</span><div class="chat-tools"><button type="button" class="btn btn-quiet btn-small" id="voice-toggle">${consentEffective("voice_processing") ? "Hide voice" : "Voice & consent"}</button></div></div></form><div id="chat-error" class="message error hidden" style="margin-top:8px"></div></div></section></div>`;
  $("view-container").innerHTML = html;
  const chatBody = $("chat-body"); chatBody.scrollTop = chatBody.scrollHeight;
  document.querySelectorAll("[data-conversation-id]").forEach((button) => button.addEventListener("click", async () => { state.conversationId = button.dataset.conversationId; await renderBuddy(); }));
  $("new-conversation").addEventListener("click", async () => { try { await openNewConversation(); } catch (e) { toast(e.message, "error"); } });
  $("chat-form").addEventListener("submit", async (e) => { e.preventDefault(); await sendBuddyMessage($("chat-input").value, "text"); });
  $("chat-input").addEventListener("keydown", async (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("chat-form").requestSubmit(); } });
  $("voice-toggle").addEventListener("click", () => consentEffective("voice_processing") ? $("voice-panel").classList.toggle("hidden") : navigate("consent"));
  if (consentEffective("voice_processing")) wireVoiceControls();
  bindCommonActions();
}
function renderMessage(message) {
  const who = message.speaker === "student" ? "student" : "buddy";
  return `<div class="chat-message ${who}"><div class="bubble">${escapeHtml(message.content)}</div><span class="message-time">${message.speaker === "student" ? "You" : "Saathi"} · ${shortDate(message.created_at)} ${message.speaker === "buddy" ? `<button class="link-button" data-action="say" data-text="${escapeHtml(message.content).replace(/\n/g, " ")}" title="Read aloud">Listen</button>` : ""}</span></div>`;
}
async function sendBuddyMessage(content, channel) {
  const error = $("chat-error"); error.classList.add("hidden");
  const text = (content || "").trim();
  if (!text) return;
  const input = $("chat-input"); if (channel === "text" && input) input.value = "";
  try {
    const result = await api(`/api/conversations/${encodeURIComponent(state.conversationId)}/messages`, { method: "POST", body: { content: text, channel } });
    if (result.safety?.case_created) toast("A restricted support case was recorded. The app cannot guarantee an immediate human response.", "notice");
    await renderBuddy();
  } catch (err) {
    if (input && channel === "text") input.value = text;
    if (error) { error.textContent = err.message; error.classList.remove("hidden"); }
    else toast(err.message, "error");
  }
}
function wireVoiceControls() {
  const start = $("record-start"), stop = $("record-stop");
  if (!start || !stop) return;
  start.addEventListener("click", async () => {
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error("This browser does not support audio recording. You can type your message instead.");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferred = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
      state.recordedChunks = [];
      state.recording = new MediaRecorder(stream, { mimeType: preferred });
      state.recording.ondataavailable = (e) => { if (e.data?.size) state.recordedChunks.push(e.data); };
      state.recording.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        state.voiceBlob = new Blob(state.recordedChunks, { type: "audio/webm" });
        await transcribeVoiceBlob();
      };
      state.recording.start();
      start.classList.add("hidden"); stop.classList.remove("hidden");
      $("voice-help").textContent = "Recording… Press Stop when you are ready. The app does not store raw audio.";
    } catch (err) { toast(err.message || "Microphone access was not available.", "error"); }
  });
  stop.addEventListener("click", () => { if (state.recording && state.recording.state !== "inactive") state.recording.stop(); start.classList.remove("hidden"); stop.classList.add("hidden"); $("voice-help").textContent = "Transcribing the recording…"; });
  $("send-voice-transcript").addEventListener("click", async () => {
    const transcript = $("voice-transcript").value.trim();
    if (!transcript) return toast("Review or edit the transcript before sending.", "error");
    $("voice-transcript-wrap").classList.add("hidden");
    state.voiceBlob = null; state.recordedChunks = [];
    await sendBuddyMessage(transcript, "voice");
  });
  $("discard-voice-transcript").addEventListener("click", () => { state.voiceBlob = null; state.recordedChunks = []; $("voice-transcript").value = ""; $("voice-transcript-wrap").classList.add("hidden"); $("voice-help").textContent = "Recording discarded from this page; raw audio is not retained by this app."; });
}
async function transcribeVoiceBlob() {
  const help = $("voice-help");
  try {
    if (!state.voiceBlob) return;
    const form = new FormData(); form.append("file", state.voiceBlob, "voice-message.webm");
    const result = await api("/api/voice/transcribe", { method: "POST", body: form });
    $("voice-transcript").value = result.transcript;
    $("voice-transcript-wrap").classList.remove("hidden");
    help.textContent = "Transcript ready. Review it before sending it to Saathi.";
  } catch (err) {
    help.textContent = err.message || "Voice transcription failed.";
    toast(err.message || "Voice transcription failed.", "error");
    state.voiceBlob = null; state.recordedChunks = [];
  }
}
function speakText(text) {
  if (!text || !window.speechSynthesis || !window.SpeechSynthesisUtterance) return toast("Read-aloud is not supported in this browser.", "error");
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 0.92;
  window.speechSynthesis.speak(utterance);
}

async function renderKnowledge() {
  let items = await api("/api/knowledge");
  const canReview = state.user.role === "counsellor";
  let html = pageHeader("APPROVED CONTENT", "Resource library", "Explore reflection prompts and coping resources. Demo resources need qualified review before live student use.");
  html += `<form id="knowledge-search" class="search-row"><input id="knowledge-query" placeholder="Search by topic, e.g. exam stress or friendship" aria-label="Search knowledge library"><button class="btn btn-primary" type="submit">Search</button><button class="btn btn-outline" id="knowledge-reset" type="button">Reset</button></form><div id="knowledge-results" class="resource-list">${renderKnowledgeCards(items)}</div>`;
  if (canReview) html += `<div class="section-head"><h2>Publish a reviewed resource</h2><span>Counsellor review</span></div><section class="card form-card"><p class="card-sub" style="margin-bottom:18px">Published content may be retrieved in AI conversations. Use original or properly licensed content and complete clinical/safeguarding review before publishing for a live school.</p><form id="knowledge-form" class="stack"><label>Title<input id="knowledge-title" required maxlength="220"></label><div class="field-row"><label>Category<select id="knowledge-category"><option value="coping_skill">Coping skill</option><option value="philosophical_reflection">Philosophical reflection</option><option value="academic_stress">Academic stress</option><option value="relationships">Relationships</option><option value="help_seeking">Help-seeking</option><option value="safeguarding">Safeguarding</option></select></label><label>Age band<select id="knowledge-age"><option value="all">All ages</option><option value="6-10">6–10</option><option value="11-14">11–14</option><option value="15-17">15–17</option><option value="18+">18+</option></select></label></div><label>Resource content<textarea id="knowledge-content" required minlength="20" maxlength="12000"></textarea></label><label>Source / licence<input id="knowledge-source" required maxlength="240" placeholder="Author, source, or original material"></label><label class="checkbox-row"><input id="knowledge-review-attestation" type="checkbox" required><span>I confirm this item has been reviewed and is permitted for publication. This is not a substitute for clinical or safeguarding approval where applicable.</span></label><div class="form-actions"><button class="btn btn-primary" type="submit">Publish resource</button></div></form></section>`;
  $("view-container").innerHTML = html;
  $("knowledge-search").addEventListener("submit", async (e) => { e.preventDefault(); try { const q = $("knowledge-query").value.trim(); items = await api(`/api/knowledge?q=${encodeURIComponent(q)}`); $("knowledge-results").innerHTML = renderKnowledgeCards(items); if (!items.length) $("knowledge-results").innerHTML = `<div class="empty-state">No approved resources matched that search.</div>`; } catch (err) { toast(err.message, "error"); } });
  $("knowledge-reset").addEventListener("click", async () => { $("knowledge-query").value = ""; items = await api("/api/knowledge"); $("knowledge-results").innerHTML = renderKnowledgeCards(items); });
  if (canReview) $("knowledge-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/knowledge", { method: "POST", body: { title: $("knowledge-title").value, content: $("knowledge-content").value, category: $("knowledge-category").value, age_band: $("knowledge-age").value, source: $("knowledge-source").value, reviewer_attestation: $("knowledge-review-attestation").checked } });
      toast("Resource published for this school."); await renderKnowledge();
    } catch (err) { toast(err.message, "error"); }
  });
}
function renderKnowledgeCards(items) {
  if (!items.length) return `<div class="empty-state">No published resources yet.</div>`;
  return items.map((item) => `<article class="card resource-card"><span class="resource-badge">${escapeHtml(item.category.replaceAll("_", " "))}</span><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.content)}</p><div class="resource-meta"><strong>Source:</strong> ${escapeHtml(item.source)}<br><strong>Age:</strong> ${escapeHtml(item.age_band)} · <strong>Review:</strong> ${escapeHtml(item.reviewer || item.review_status)}</div></article>`).join("");
}

async function renderConsent() {
  const data = await api("/api/consent/status");
  let html = pageHeader("PRIVACY & PERMISSIONS", "Consent and data use", "Review what the platform processes and make a change when needed.");
  html += `<div class="notice-strip" style="margin-bottom:17px"><strong>MVP consent workflow</strong><span>Students record their own assent. For students under 18, a counsellor reviews and accepts that assent in the existing Counsellor role. No guardian account or new role is required in this MVP. This is a simplified MVP workflow, not a substitute for your school's formal consent policy.</span></div>`;
  if (state.user.role === "student") {
    const summary = data.own_student.consent;
    const minor = state.user.age_band !== "18+";
    const corePurposes = ["wellbeing_processing", "ai_processing"];
    const coreToGrant = corePurposes.filter((purpose) => summary[purpose]?.student_status !== "granted");
    const coreActive = corePurposes.every((purpose) => summary[purpose]?.effective);
    const voiceGranted = summary.voice_processing?.student_status === "granted";
    const voiceActive = Boolean(summary.voice_processing?.effective);
    html += `<div class="grid two"><section class="card consent-card"><h2>Your privacy settings</h2><p class="card-sub">${minor ? "Record your assent for wellbeing records and AI text processing. Your counsellor must review it before those features are enabled." : "As an adult student, you control your own consent settings."}</p>${PURPOSES.map((purpose) => renderConsentPurpose(purpose, summary[purpose], minor)).join("")}<div class="inline-actions" style="margin-top:18px"><button class="btn btn-primary" id="student-consent-grant" ${coreToGrant.length ? "" : "disabled"}>${coreToGrant.length ? (minor ? "Record assent for journal & AI buddy" : "Enable journal & AI buddy") : (coreActive ? "Journal & AI buddy enabled" : "Assent recorded — awaiting review")}</button><button class="btn btn-outline" id="student-consent-voice-grant" ${voiceGranted ? "disabled" : ""}>${voiceActive ? "Voice enabled" : voiceGranted ? "Voice assent awaiting review" : "Enable voice (optional)"}</button><button class="btn btn-outline" id="student-consent-withdraw">Withdraw consent / assent</button></div><p class="helper">Voice is optional and requires its own assent and counsellor review for students under 18.</p></section><section class="card card-pad"><h2>What these settings mean</h2><div class="activity-row"><div class="activity-icon">▤</div><div><strong>Wellbeing records</strong><p>Journal and conversation data is stored under the school's policy.</p></div></div><div class="activity-row"><div class="activity-icon">◉</div><div><strong>AI buddy processing</strong><p>Your message is sent to the configured AI service where applicable.</p></div></div><div class="activity-row"><div class="activity-icon">♩</div><div><strong>Voice transcription</strong><p>Your recording is sent to the configured speech provider for transcription. Raw audio is not saved by this application.</p></div></div><div class="notice-strip" style="margin-top:14px"><strong>Remember</strong><span>Do not use this app for urgent help. Speak directly to a trusted adult or emergency service if you are in danger.</span></div></section></div>`;
  } else if (state.user.role === "counsellor") {
    const students = data.students || [];
    html += `<section class="card card-pad"><div class="card-top"><h2>Student consent review</h2><span class="pill blue">Counsellor action</span></div><p class="card-sub" style="margin-bottom:16px">Review the student's recorded assent. Accept only after confirming the student has reviewed the privacy notice and understands the choices. This page shows consent status only, not journal entries or chat content.</p><div class="table-wrap"><table class="simple-table"><thead><tr><th>Student</th><th>Age band</th><th>Journal & AI buddy</th><th>Optional voice</th><th>Action</th></tr></thead><tbody>${students.map((s) => { const c = s.consent || {}; const core = ["wellbeing_processing", "ai_processing"]; const pending = core.filter((p) => c[p]?.student_status === "granted" && !(c[p]?.effective)); const voicePending = c.voice_processing?.student_status === "granted" && !c.voice_processing?.effective; const coreStatus = s.wellbeing_effective ? "Effective" : core.some((p) => c[p]?.student_status === "granted") ? "Awaiting review" : "Student action needed"; return `<tr><td>${escapeHtml(s.display_name)}</td><td>${escapeHtml(s.age_band || "—")}</td><td><span class="pill ${s.wellbeing_effective ? "green" : "yellow"}">${coreStatus}</span></td><td><span class="pill ${c.voice_processing?.effective ? "green" : "yellow"}">${c.voice_processing?.effective ? "Effective" : voicePending ? "Awaiting review" : c.voice_processing?.student_status === "granted" ? "Review needed" : "Not enabled"}</span></td><td>${pending.length ? `<button class="btn btn-primary btn-small" data-consent-approve="${s.student_id}" data-purposes="${pending.join(",")}">Accept core assent</button>` : ""}${voicePending ? ` <button class="btn btn-outline btn-small" data-consent-approve="${s.student_id}" data-purposes="voice_processing">Accept voice</button>` : ""}${!pending.length && !voicePending && !s.wellbeing_effective ? `<span class="helper">No assent ready to review</span>` : ""}</td></tr>`; }).join("")}</tbody></table></div></section>`;
  }
  $("view-container").innerHTML = html;
  // Bind only after the consent markup has been inserted into the DOM.
  // Previously these lookups ran before innerHTML was assigned, returning null.
  const grantButton = $("student-consent-grant");
  if (grantButton && !grantButton.disabled) grantButton.addEventListener("click", () => updateConsent(null, ["wellbeing_processing", "ai_processing"].filter((purpose) => state.user.consent?.[purpose]?.student_status !== "granted"), "granted"));
  const voiceButton = $("student-consent-voice-grant");
  if (voiceButton && !voiceButton.disabled) voiceButton.addEventListener("click", () => updateConsent(null, ["voice_processing"], "granted"));
  const withdrawButton = $("student-consent-withdraw");
  if (withdrawButton) withdrawButton.addEventListener("click", () => updateConsent(null, PURPOSES, "withdrawn"));
  document.querySelectorAll("[data-consent-approve]").forEach((button) => button.addEventListener("click", async () => {
    const studentId = button.getAttribute("data-consent-approve");
    const purposes = (button.getAttribute("data-purposes") || "").split(",").filter(Boolean);
    const yes = await confirmAction("Accept student assent", `Confirm that you reviewed the student's assent for ${purposes.map((p) => PURPOSE_LABELS[p]).join(", ")}. This will enable the approved features.`);
    if (!yes) return;
    try { await api("/api/consent/review", { method: "POST", body: { student_id: studentId, purposes } }); toast("Student assent accepted."); await renderConsent(); }
    catch (err) { toast(err.message, "error"); }
  }));
}
function renderConsentPurpose(purpose, data, minor) {
  const effective = data?.effective;
  const status = data?.student_status || "not_recorded";
  const reviewer = data?.counsellor_status || (minor ? "not_recorded" : "not_required");
  return `<div class="consent-purpose"><div><strong>${escapeHtml(PURPOSE_LABELS[purpose])}</strong><p>${purpose === "wellbeing_processing" ? "Store journal entries and permitted wellbeing records." : purpose === "ai_processing" ? "Process text with the configured AI buddy provider." : "Send an audio recording to the configured speech provider for transcription; raw audio is not retained by this app."}</p><p>Student / self: <span class="code-chip">${escapeHtml(status)}</span> · Counsellor review: <span class="code-chip">${escapeHtml(reviewer)}</span></p></div><span class="pill ${effective ? "green" : "yellow"}">${effective ? "Effective" : status === "granted" && reviewer !== "granted" && minor ? "Awaiting review" : "Needs action"}</span></div>`;
}
async function updateConsent(studentId, purposes, status) {
  const verb = status === "granted" ? "record this consent/assent" : "withdraw this consent/assent";
  const yes = await confirmAction("Confirm privacy change", `Are you sure you want to ${verb} for ${purposes.map((p) => PURPOSE_LABELS[p]).join(", ")}? The change will be recorded in the audit trail.`);
  if (!yes) return;
  try {
    await api("/api/consent", { method: "POST", body: { student_id: studentId, purposes, status } });
    state.user = await api("/api/me");
    toast("Consent status updated.");
    await renderConsent();
  } catch (err) { toast(err.message, "error"); }
}
function confirmAction(title, copy) {
  return new Promise((resolve) => {
    const dialog = $("confirm-dialog"); $("confirm-title").textContent = title; $("confirm-copy").textContent = copy;
    const continueButton = $("confirm-continue");
    const done = (value) => { dialog.removeEventListener("close", close); resolve(value); };
    const close = () => done(dialog.returnValue === "confirm");
    dialog.addEventListener("close", close, { once: true });
    if (typeof dialog.showModal === "function") dialog.showModal(); else resolve(window.confirm(copy));
    continueButton.onclick = () => { dialog.close("confirm"); };
  });
}

async function renderCases() {
  const role = state.user.role;
  if (!["counsellor", "teacher"].includes(role)) throw new Error("This role cannot access case-level records.");
  const cases = await api("/api/cases");
  let html = pageHeader("HUMAN SUPPORT", role === "teacher" ? "Your assigned support" : "Case management", role === "teacher" ? "Only cases assigned to you are listed; sensitive evidence is restricted by role." : "Review the evidence, acknowledge responsibility, and keep follow-up actions visible.");
  if (role !== "teacher") {
    const urgent = cases.filter((c) => c.urgency === "immediate" && c.status !== "closed").length;
    html += `<div class="grid three" style="margin-bottom:17px">${statCard("!", urgent, "Urgent open cases", "amber")}${statCard("♡", cases.filter((c) => c.status !== "closed").length, "Open / in review", "lilac")}${statCard("○", cases.filter((c) => c.assigned_to === "Unassigned").length, "Unassigned", "blue")}</div>`;
  }
  html += `<div class="notice-strip" style="margin-bottom:15px"><strong>Restricted information</strong><span>Case details are sensitive. Use the secure dashboard only, do not copy evidence into email, and record actions needed for continuity of care.</span></div>`;
  if (!cases.length) html += `<div class="empty-state"><div class="empty-icon">♡</div><strong>No cases in this queue</strong><p>New support cases will appear here if they are assigned to your role.</p></div>`;
  else html += `<div class="case-list">${cases.map((c) => `<div class="case-row" tabindex="0" role="button" data-case-id="${c.id}"><div><span class="case-title">${escapeHtml(c.title)}</span><span class="case-subtitle">${escapeHtml(c.student_display)}${c.student_school_class ? ` · ${escapeHtml(c.student_school_class)}` : " · Class not recorded"} · ${escapeHtml(c.summary)}</span></div><div><div class="case-cell-label">Urgency</div><span class="pill ${urgencyClass(c.urgency)}">${escapeHtml(urgencyLabel(c.urgency))}</span></div><div class="case-hide-tablet"><div class="case-cell-label">Owner</div><span class="subheading">${escapeHtml(c.assigned_to)}</span></div><div><span class="pill ${c.status === "closed" ? "gray" : c.status === "in_review" ? "blue" : "yellow"}">${escapeHtml(c.status.replaceAll("_", " "))}</span></div></div>`).join("")}</div>`;
  $("view-container").innerHTML = html;
  document.querySelectorAll("[data-case-id]").forEach((row) => { const open = () => renderCaseDetail(row.dataset.caseId); row.addEventListener("click", open); row.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); }); });
}
async function renderCaseDetail(id) {
  try {
    const c = await api(`/api/cases/${encodeURIComponent(id)}`);
    const privileged = state.user.role === "counsellor";
    let html = `<div class="page-header"><div><div class="eyebrow small-label">SUPPORT CASE · ${escapeHtml(id.slice(0, 8))}</div><h1>${escapeHtml(c.title)}</h1><p>Created ${fmtDate(c.created_at)} · Assigned to ${escapeHtml(c.assigned_to)}</p></div><div class="page-actions"><button class="btn btn-outline" id="back-cases">← Back to queue</button></div></div>`;
    html += `<div class="grid two"><section class="card case-detail"><div class="card-top"><h2>Case summary</h2><span class="pill ${urgencyClass(c.urgency)}">${escapeHtml(urgencyLabel(c.urgency))}</span></div><div class="student-case-profile" style="padding:13px 15px;margin:0 0 14px;border:1px solid var(--border, #dbe3ea);border-radius:12px"><div class="card-overline">STUDENT DETAILS</div><strong style="display:block;font-size:1.05rem;margin-top:5px">${escapeHtml(c.student_display || "Student")}</strong><div class="card-sub" style="margin-top:3px">${c.student_school_class ? `Standard / class: ${escapeHtml(c.student_school_class)}` : "Standard / class: Not recorded"}</div>${privileged ? `<form id="student-class-form" class="field-row" style="margin-top:10px;align-items:end"><label class="field-label" style="flex:1">Update standard / class<input id="student-school-class" class="field" maxlength="40" value="${escapeHtml(c.student_school_class || "")}" placeholder="e.g. Standard 9, Section B"></label><button class="btn btn-outline" type="submit">Save student details</button></form>` : ""}</div><p class="card-sub">${escapeHtml(c.summary)}</p>${privileged ? `<div class="divider"></div><div class="card-overline">RELEVANT EVIDENCE EXCERPT</div><div class="case-evidence">${escapeHtml(c.evidence_excerpt || "No excerpt saved.")}</div>` : `<div class="notice-strip" style="margin-top:14px"><strong>Limited view</strong><span>Raw evidence is available only to the assigned counsellor.</span></div>`}${privileged && c.status !== "closed" ? `<div class="divider"></div><form id="case-assignment-form" class="stack"><h3>Assign case owner</h3><label class="field-label">Assigned staff member<select id="case-assignee"><option value="">Unassigned</option></select></label><div class="form-actions"><button class="btn btn-outline" type="submit">Save assignment</button></div></form>` : ""}<div class="divider"></div><div class="field-row"><label class="field-label">Status<select id="case-status"><option value="open" ${c.status === "open" ? "selected" : ""}>Open</option><option value="in_review" ${c.status === "in_review" ? "selected" : ""}>In review</option>${privileged ? `<option value="closed" ${c.status === "closed" ? "selected" : ""}>Closed</option>` : ""}</select></label><label class="field-label">Acknowledged<input class="field" disabled value="${escapeHtml(fmtDate(c.acknowledged_at))}"></label></div>${privileged && c.status !== "closed" ? `<label class="field-label" style="margin-top:12px">Resolution note (required to close)<textarea id="case-resolution" rows="3" placeholder="Document the reviewed outcome; avoid unnecessary details."></textarea></label>` : ""}<div class="form-actions"><button class="btn btn-primary" id="save-case-status">Save case status</button></div></section><section class="card card-pad"><h2>Support actions</h2><p class="card-sub">Actions should be appropriate to the student's needs and school safeguarding policy.</p><div class="case-actions">${(c.actions || []).length ? c.actions.map((a) => `<div class="action-row"><div class="action-mark">${a.status === "completed" ? "✓" : a.status === "submitted_for_review" ? "↗" : "○"}</div><div style="min-width:0;flex:1"><strong>${escapeHtml(a.title)}</strong><p>${escapeHtml(a.notes || "No additional notes")}</p><small>${a.due_at ? `Due ${fmtDate(a.due_at)}` : "No due date"} · <strong>${escapeHtml(a.status.replaceAll("_", " "))}</strong>${a.completed_at ? ` · Completed ${fmtDate(a.completed_at)}` : ""}</small>${(a.progress_history || []).length ? `<div class="divider"></div><h4>Progress history</h4>${a.progress_history.map((p) => `<div class="notice-strip" style="margin:8px 0"><strong>${escapeHtml(p.author_name)} · ${fmtDate(p.created_at)}</strong><span><b>Work:</b> ${escapeHtml(p.work_performed)}${p.outcome ? `<br><b>Outcome:</b> ${escapeHtml(p.outcome)}` : ""}${p.further_concerns ? `<br><b>Further concerns:</b> ${escapeHtml(p.further_concerns)}` : ""}${p.next_step ? `<br><b>Next step:</b> ${escapeHtml(p.next_step)}` : ""}</span></div>`).join("")}` : ""}${!privileged && a.assigned_to_user_id === state.user.id && !["completed", "cancelled", "submitted_for_review"].includes(a.status) ? `<form class="action-progress-form stack" data-progress-action="${a.id}" style="margin-top:12px"><h4>Record progress</h4><label class="field-label">Work performed<textarea name="work_performed" required minlength="3" maxlength="2000" rows="2" placeholder="Describe the support action taken; keep details necessary and factual."></textarea></label><label class="field-label">Outcome<textarea name="outcome" maxlength="1000" rows="2" placeholder="What changed or was observed?"></textarea></label><label class="field-label">Further concerns<textarea name="further_concerns" maxlength="1000" rows="2" placeholder="Any concern the counsellor should review?"></textarea></label><label class="field-label">Recommended next step<textarea name="next_step" maxlength="1000" rows="2" placeholder="Optional next step"></textarea></label><div class="form-actions"><button class="btn btn-outline btn-small" type="submit" data-submit-review="false">Save progress</button><button class="btn btn-primary btn-small" type="submit" data-submit-review="true">Submit to counsellor</button></div></form>` : ""}${privileged && a.status === "submitted_for_review" ? `<div class="form-actions" style="margin-top:10px"><button class="btn btn-primary btn-small" data-review-action="${a.id}" data-review-decision="approve">Approve completion</button><button class="btn btn-outline btn-small" data-review-action="${a.id}" data-review-decision="request_changes">Request more work</button></div><label class="field-label" style="margin-top:8px">Review note<textarea id="review-note-${a.id}" maxlength="1000" rows="2" placeholder="Optional feedback for the teacher"></textarea></label>` : ""}${privileged && ["completed", "cancelled", "submitted_for_review"].includes(a.status) ? `<div style="margin-top:8px"><button class="btn btn-outline btn-small" data-review-action="${a.id}" data-review-decision="reopen">Reopen action</button></div>` : ""}</div></div>`).join("") : `<div class="empty-state">No actions recorded yet.</div>`}</div>${privileged && c.status !== "closed" ? `<div class="divider"></div><h3>Create follow-up</h3><form id="case-action-form" class="stack" style="margin-top:13px"><label class="field-label">Action title<input id="action-title" required maxlength="220" placeholder="Schedule a supportive check-in"></label><label class="field-label">Notes (minimum necessary)<textarea id="action-notes" rows="2" maxlength="1000"></textarea></label><label class="field-label">Assign to<select id="action-assignee"><option value="">Unassigned</option></select></label><label class="field-label">Due date<input id="action-due" class="field" type="datetime-local"></label><div class="form-actions"><button class="btn btn-primary" type="submit">Add action</button></div></form>` : ""}</section></div>`;
    $("view-container").innerHTML = html;
    $("back-cases").addEventListener("click", renderCases);
    if ($("student-class-form")) $("student-class-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await api(`/api/students/${encodeURIComponent(c.student_id)}/profile`, { method: "PATCH", body: { school_class: $("student-school-class").value.trim() || null } });
        toast("Student standard/class updated.");
        await renderCaseDetail(id);
      } catch (err) { toast(err.message, "error"); }
    });
    $("save-case-status").addEventListener("click", async () => {
      try { await api(`/api/cases/${encodeURIComponent(id)}`, { method: "PATCH", body: { status: $("case-status").value, resolution_note: $("case-resolution")?.value || null } }); toast("Case status saved."); await renderCaseDetail(id); }
      catch (err) { toast(err.message, "error"); }
    });
    document.querySelectorAll("[data-progress-action]").forEach((form) => form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const submitButton = e.submitter;
      const submitForReview = submitButton?.dataset.submitReview === "true";
      const fields = new FormData(form);
      try {
        const result = await api(`/api/actions/${encodeURIComponent(form.dataset.progressAction)}/progress`, { method: "POST", body: {
          work_performed: String(fields.get("work_performed") || "").trim(), outcome: String(fields.get("outcome") || "").trim(),
          further_concerns: String(fields.get("further_concerns") || "").trim(), next_step: String(fields.get("next_step") || "").trim(),
          submit_for_review: submitForReview
        }});
        toast(submitForReview ? (result.notification_queued ? "Progress submitted to counsellor; notification queued." : "Progress submitted to counsellor for review.") : "Progress saved.");
        await renderCaseDetail(id);
      } catch (err) { toast(err.message, "error"); }
    }));
    document.querySelectorAll("[data-review-action]").forEach((btn) => btn.addEventListener("click", async () => {
      const actionId = btn.dataset.reviewAction, decision = btn.dataset.reviewDecision;
      const reviewNote = $(`review-note-${actionId}`)?.value || "";
      try {
        await api(`/api/actions/${encodeURIComponent(actionId)}/review`, { method: "PATCH", body: { decision, review_note: reviewNote } });
        toast(decision === "approve" ? "Action completion approved." : decision === "request_changes" ? "Further work requested." : "Action reopened.");
        await renderCaseDetail(id);
      } catch (err) { toast(err.message, "error"); }
    }));
    if (privileged && ($("case-action-form") || $("case-assignment-form"))) {
      const staff = await api("/api/admin/users");
      const staffOptions = staff.filter((s) => ["teacher", "counsellor"].includes(s.role)).map((s) => `<option value="${s.id}">${escapeHtml(s.display_name)} · ${escapeHtml(roleLabel(s.role))}</option>`).join("");
      if ($("case-assignee")) {
        $("case-assignee").innerHTML = `<option value="">Unassigned</option>` + staffOptions;
        $("case-assignee").value = c.assigned_to_user_id || "";
        $("case-assignment-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          try {
            const result = await api(`/api/cases/${encodeURIComponent(id)}/assignment`, { method: "PATCH", body: { assigned_to_user_id: $("case-assignee").value || null } });
            toast(result.notification_queued ? "Case assigned. Email notification queued." : (result.notification_note || "Case assignment saved."));
            await renderCaseDetail(id);
          } catch (err) { toast(err.message, "error"); }
        });
      }
      if ($("action-assignee")) $("action-assignee").innerHTML = `<option value="">Unassigned</option>` + staffOptions;
      if ($("case-action-form")) $("case-action-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          let due = $("action-due").value ? new Date($("action-due").value).toISOString() : null;
          const result = await api(`/api/cases/${encodeURIComponent(id)}/actions`, { method: "POST", body: { title: $("action-title").value, notes: $("action-notes").value, assigned_to_user_id: $("action-assignee").value || null, due_at: due } });
          toast(result.notification_queued ? "Follow-up action recorded. Email notification queued." : (result.notification_note || "Follow-up action recorded.")); await renderCaseDetail(id);
        } catch (err) { toast(err.message, "error"); }
      });
    }
  } catch (err) { toast(err.message, "error"); await renderCases(); }
}

async function renderReports() {
  const report = await api("/api/reports/summary");
  let html = pageHeader("OPERATIONS", "Wellbeing support reports", "Review aggregate workload and follow-up measures. These counts are not diagnostic or student-ranking metrics.");
  html += `<div class="grid four">${statCard("♙", report.active_students, "Active students", "blue")}${statCard("♡", report.open_cases, "Open / in-review cases", "lilac")}${statCard("!", report.open_cases_by_urgency.immediate, "Urgent open cases", "amber")}${statCard("✓", report.completed_support_actions, "Completed support actions", "")}</div>`;
  html += `<div class="grid two" style="margin-top:17px"><section class="card card-pad"><h2>Open case mix</h2><p class="card-sub">Current open or in-review cases by operational urgency.</p><div style="margin-top:20px">${Object.entries(report.open_cases_by_urgency).map(([key, value]) => `<div style="margin-bottom:17px"><div class="card-top"><span class="subheading">${escapeHtml(urgencyLabel(key))}</span><strong>${value}</strong></div><div style="height:7px;background:#edf1f5;border-radius:10px;margin-top:8px;overflow:hidden"><div style="height:100%;width:${report.open_cases ? Math.max(2, value / report.open_cases * 100) : 0}%;background:${key === "immediate" ? "#c85f55" : key === "human_review" ? "#d5a648" : "#56a58e"};border-radius:10px"></div></div></div>`).join("")}</div></section><section class="card card-pad"><h2>How to interpret this</h2><p class="report-note">A change in case count can reflect better help-seeking or improved detection, not necessarily worsening wellbeing. Do not rank students, infer diagnoses, or use these totals for disciplinary or academic decisions.</p><div class="divider"></div><p class="report-note">Generated ${fmtDate(report.generated_at)}. This report uses tenant-scoped records and does not include message content.</p><button id="refresh-report" class="btn btn-outline btn-small" style="margin-top:12px">Refresh report</button></section></div>`;
  $("view-container").innerHTML = html;
  $("refresh-report").addEventListener("click", renderReports);
}

async function renderRetention() {
  const policies = await api("/api/retention/policies");
  let html = pageHeader("PRIVACY OPERATIONS", "Retention and legal holds", "Retention rules are inactive by default. Review the school's legal requirements before enabling deletion of live records.");
  html += `<div class="notice-strip" style="margin-bottom:15px"><strong>Careful by design</strong><span>Deletion rules can affect support continuity and legal obligations. Start with a dry-run. Active-case source content is protected; audit metadata is preserved. This MVP does not automate retention of audit/security logs or all external backups.</span></div>`;
  html += `<section class="card card-pad"><div class="card-top"><h2>Retention policies</h2><span class="pill yellow">Off by default</span></div><p class="card-sub">To activate a rule you must attest that the retention schedule has been approved for live data by the school's privacy/legal owner.</p><div id="retention-policies" style="margin-top:18px">${policies.map((p) => `<div class="settings-row" data-policy="${escapeHtml(p.data_category)}"><div><strong>${escapeHtml(p.data_category.replaceAll("_", " "))}</strong><small>${escapeHtml(p.policy_version)} · Updated ${fmtDate(p.updated_at)}</small></div><div class="retention-days"><input class="field" type="number" min="30" max="3650" value="${p.retention_days}" aria-label="Retention days for ${escapeHtml(p.data_category)}"> <small>days</small></div><label class="checkbox-row policy-active"><input type="checkbox" class="retention-active" ${p.active ? "checked" : ""}>Active</label><label class="checkbox-row policy-approval"><input type="checkbox" class="retention-approval" ${p.approved_for_live_data ? "checked" : ""}>Approved</label><button class="btn btn-outline btn-small policy-save" data-save-policy="${escapeHtml(p.data_category)}">Save</button></div>`).join("")}</div><div class="form-actions"><button class="btn btn-outline" id="retention-dry-run">Run dry-run</button><button class="btn btn-danger" id="retention-execute">Execute eligible deletions</button></div><div id="retention-results" class="helper" style="margin-top:14px"></div></section>`;
  html += `<div class="section-head"><h2>Safeguarding holds</h2><span>API-supported; operational process required</span></div><section class="card card-pad"><p class="card-sub">An authorized counsellor can place a hold on a specific journal, message, voice-session metadata record, or support case using the retention-holds API. A hold prevents automated deletion until an authorized counsellor releases it.</p><p class="helper">Document the legal/safeguarding reason and review the hold periodically. Hold records are audited.</p></section>`;
  $("view-container").innerHTML = html;
  document.querySelectorAll("[data-save-policy]").forEach((btn) => btn.addEventListener("click", async () => {
    const row = btn.closest("[data-policy]");
    const active = row.querySelector(".retention-active").checked;
    const approved = row.querySelector(".retention-approval").checked;
    try {
      await api(`/api/retention/policies/${encodeURIComponent(btn.dataset.savePolicy)}`, { method: "PUT", body: { retention_days: Number(row.querySelector("input[type=number]").value), active, approved_for_live_data: approved } });
      toast("Retention policy saved."); await renderRetention();
    } catch (err) { toast(err.message, "error"); }
  }));
  async function runRetention(dryRun) {
    if (!dryRun) {
      const ok = await confirmAction("Execute retention deletions?", "This permanently deletes eligible records according to active and approved policies. Review the dry-run first and ensure backups and legal holds are current.");
      if (!ok) return;
    }
    try {
      const result = await api("/api/retention/run", { method: "POST", body: { dry_run: dryRun } });
      $("retention-results").textContent = `${result.message} ${JSON.stringify(result.candidates || result.deleted_counts || {})}`;
      toast(dryRun ? "Dry-run complete. No records were deleted." : "Retention execution completed.");
    } catch (err) { toast(err.message, "error"); }
  }
  $("retention-dry-run").addEventListener("click", () => runRetention(true));
  $("retention-execute").addEventListener("click", () => runRetention(false));
}

async function renderAudit() {
  const rows = await api("/api/audit?limit=100");
  let html = pageHeader("SECURITY & ACCOUNTABILITY", "Audit log", "Review access and operational events for this school. Message content is intentionally excluded from routine audit metadata.");
  html += `<section class="card card-pad"><div class="card-top"><h2>Recent events</h2><span class="pill gray">${rows.length} entries</span></div><div class="table-wrap" style="margin-top:14px"><table class="simple-table"><thead><tr><th>Time</th><th>Action</th><th>Actor</th><th>Resource</th><th>Purpose</th><th>Outcome</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${fmtDate(r.created_at)}</td><td>${escapeHtml(r.action)}</td><td><span class="code-chip">${escapeHtml((r.actor_user_id || "system").slice(0, 8))}</span></td><td>${escapeHtml(r.resource_type)} ${r.resource_id ? `<span class="code-chip">${escapeHtml(r.resource_id.slice(0,8))}</span>` : ""}</td><td>${escapeHtml(r.purpose)}</td><td><span class="pill ${r.outcome === "success" ? "green" : "yellow"}">${escapeHtml(r.outcome)}</span></td></tr>`).join("")}</tbody></table></div></section>`;
  $("view-container").innerHTML = html;
}

function bindCommonActions() {
  document.querySelectorAll("[data-action='navigate']").forEach((btn) => btn.addEventListener("click", () => navigate(btn.dataset.view)));
  document.querySelectorAll("[data-action='journal-prompt']").forEach((btn) => btn.addEventListener("click", () => { state.lastJournalPrompt = btn.dataset.prompt || ""; navigate("journal"); }));
  document.querySelectorAll("[data-action='say']").forEach((btn) => btn.addEventListener("click", () => speakText(btn.dataset.text || "")));
}

async function init() {
  try { state.system = await api("/api/system/status"); }
  catch (_) { state.system = { environment: "unknown", demo_mode: true, demo_accounts_available: false }; }
  if (state.system.demo_accounts_available) {
    try {
      const accounts = await api("/api/system/demo-accounts");
      $("demo-account-buttons").innerHTML = accounts.map((account) => `<button type="button" data-demo-tenant="${escapeHtml(account.tenant_slug)}" data-demo-email="${escapeHtml(account.email)}" data-demo-password="${escapeHtml(account.password)}">${escapeHtml(account.role_label)} · ${escapeHtml(account.tenant_slug)}</button>`).join("");
      if (accounts.length) $("demo-credentials").classList.remove("hidden");
    } catch (_) { /* Demo convenience is optional and fails closed. */ }
  }
  const loginForm = $("login-form");
  const registrationForm = $("registration-form");
  const showRegistration = () => {
    loginForm.classList.add("hidden"); registrationForm.classList.remove("hidden");
    $("show-register-row").classList.add("hidden"); $("login-success").classList.add("hidden");
    $("register-tenant").value = $("tenant-slug").value.trim();
    $("register-email").value = $("email").value.trim();
    $("registration-error").classList.add("hidden");
    $("register-name").focus();
  };
  const showSignIn = () => {
    registrationForm.classList.add("hidden"); loginForm.classList.remove("hidden");
    $("show-register-row").classList.remove("hidden"); $("email").focus();
  };
  $("show-register").addEventListener("click", showRegistration);
  $("show-login").addEventListener("click", showSignIn);
  registrationForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const err = $("registration-error"); err.classList.add("hidden");
    const password = $("register-password").value;
    if (password !== $("register-password-confirm").value) {
      err.textContent = "The passwords do not match."; err.classList.remove("hidden"); return;
    }
    const submit = registrationForm.querySelector("button[type='submit']");
    submit.disabled = true;
    try {
      const payload = {
        tenant_slug: $("register-tenant").value.trim(),
        invitation_code: $("register-invite").value.trim(),
        display_name: $("register-name").value.trim(),
        email: $("register-email").value.trim(),
        school_class: $("register-class").value.trim() || null,
        age_band: $("register-age-band").value, password,
      };
      const result = await api("/api/auth/student/register", { method: "POST", body: payload });
      $("tenant-slug").value = payload.tenant_slug; $("email").value = payload.email; $("password").value = "";
      registrationForm.reset(); showSignIn();
      $("login-success").textContent = result.message || "Account created. You can now sign in.";
      $("login-success").classList.remove("hidden");
    } catch (e) { err.textContent = e.message || "Registration could not be completed."; err.classList.remove("hidden"); }
    finally { submit.disabled = false; }
  });
  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const err = $("login-error"); err.classList.add("hidden");
    try {
      await api("/api/auth/login", { method: "POST", body: { tenant_slug: $("tenant-slug").value.trim(), email: $("email").value.trim(), password: $("password").value } });
      state.user = await api("/api/me");
      state.view = "dashboard"; state.conversationId = null;
      await loadApp(state.user);
    } catch (e) { err.textContent = e.message || "Sign-in failed."; err.classList.remove("hidden"); }
  });
  document.querySelectorAll("[data-demo-email]").forEach((button) => button.addEventListener("click", () => {
    $("tenant-slug").value = button.dataset.demoTenant || "demo-school";
    $("email").value = button.dataset.demoEmail; $("password").value = button.dataset.demoPassword;
  }));
  $("logout-button").addEventListener("click", async () => {
    try { await api("/api/auth/logout", { method: "POST", body: {} }); } catch (_) {}
    state.user = null; state.conversationId = null; if (window.speechSynthesis) window.speechSynthesis.cancel(); showLogin();
  });
  $("mobile-menu").addEventListener("click", () => $("sidebar").classList.toggle("open"));
  try {
    state.user = await api("/api/me");
    await loadApp(state.user);
  } catch (_) { showLogin(); }
}

document.addEventListener("DOMContentLoaded", init);
