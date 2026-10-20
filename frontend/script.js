/**
 * script.js — SnapLink frontend
 *
 * - Shorten URLs (POST /shorten) with optional custom alias + expiry
 * - Copy / open the result, keep a "recent links" list in localStorage
 * - Analytics for any short code (GET /analytics/{code})
 * - Backend status pill (GET /health)
 */

(() => {
  "use strict";

  // ──────────────────────────────────────────────
  // API base URL
  //   1. ?api=https://… in the page URL (handy for testing a deploy)
  //   2. <meta name="snaplink-api" content="https://…"> in index.html
  //   3. localhost / 127.0.0.1  -> same host, port 8000
  //   4. otherwise the production API below
  // ──────────────────────────────────────────────
  const PROD_API_BASE = "https://url-shortner-xzz7.onrender.com";

  function resolveApiBase() {
    const fromQuery = new URLSearchParams(location.search).get("api");
    const fromMeta = document.querySelector('meta[name="snaplink-api"]')?.content;
    const explicit = (fromQuery || fromMeta || "").trim();
    if (explicit) return explicit.replace(/\/+$/, "");

    const host = location.hostname;
    if (host === "localhost" || host === "127.0.0.1" || host === "") {
      return `http://${host || "localhost"}:8000`;
    }
    return location.hostname.endsWith(".vercel.app") ? `${location.origin}/api` : PROD_API_BASE;
  }

  const API_BASE = resolveApiBase();
  const REQUEST_TIMEOUT_MS = 70_000; // free-tier hosts can take ~1 min to wake
  const SLOW_NOTICE_MS = 5_000;
  const STORAGE_KEY = "snaplink:recent";
  const MAX_RECENT = 20;

  // ──────────────────────────────────────────────
  // DOM
  // ──────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);

  const shortenForm = $("shorten-form");
  const urlInput = $("url-input");
  const urlError = $("url-error");
  const aliasInput = $("custom-code");
  const aliasError = $("alias-error");
  const aliasPrefix = $("alias-prefix");
  const advanced = $("advanced");
  const expirySelect = $("expiry-days");
  const shortenBtn = $("shorten-btn");
  const formStatus = $("form-status");

  const resultCard = $("result-card");
  const shortUrlEl = $("short-url-display");
  const originalUrlEl = $("original-url-display");
  const createdEl = $("created-display");
  const expiresEl = $("expires-display");
  const copyBtn = $("copy-btn");
  const openBtn = $("open-btn");
  const statsBtn = $("stats-btn");

  const recentList = $("recent-list");
  const recentTpl = $("recent-item-tpl");
  const clearRecentBtn = $("clear-recent");

  const analyticsForm = $("analytics-form");
  const analyticsInput = $("analytics-code");
  const analyticsError = $("analytics-error");
  const analyticsBtn = $("analytics-btn");
  const analyticsResults = $("analytics-results");

  const apiStatus = $("api-status");
  const toastEl = $("toast");

  let currentResult = null;

  $("api-docs-link").href = `${API_BASE}/docs`;
  aliasPrefix.textContent = `${hostOf(API_BASE)}/`;

  // ──────────────────────────────────────────────
  // Helpers
  // ──────────────────────────────────────────────
  function hostOf(url) {
    try { return new URL(url).host; } catch { return "snaplink"; }
  }

  /** Backend returns naive UTC timestamps (no "Z"); treat them as UTC. */
  function parseDate(value) {
    if (!value) return null;
    const hasZone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value);
    const d = new Date(hasZone ? value : `${value}Z`);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  function formatDate(value, withTime = true) {
    const d = parseDate(value);
    if (!d) return "Never";
    return d.toLocaleString(undefined, {
      day: "numeric", month: "short", year: "numeric",
      ...(withTime ? { hour: "numeric", minute: "2-digit" } : {}),
    });
  }

  function relativeTime(value) {
    const d = parseDate(value);
    if (!d) return "";
    const diff = (d.getTime() - Date.now()) / 1000;
    const abs = Math.abs(diff);
    const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
    const units = [["year", 31536000], ["month", 2592000], ["week", 604800], ["day", 86400], ["hour", 3600], ["minute", 60]];
    for (const [unit, secs] of units) {
      if (abs >= secs) return rtf.format(Math.round(diff / secs), unit);
    }
    return "just now";
  }

  function isExpired(expiresAt) {
    const d = parseDate(expiresAt);
    return !!d && d.getTime() < Date.now();
  }

  function prettyUrl(url) {
    return url.replace(/^https?:\/\//, "").replace(/\/$/, "");
  }

  const ICONS = {
    error: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.01"/></svg>',
    info: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.01"/></svg>',
  };

  function setStatus(message, tone = "info") {
    if (!message) {
      formStatus.textContent = "";
      formStatus.removeAttribute("data-tone");
      return;
    }
    formStatus.dataset.tone = tone;
    formStatus.innerHTML = tone === "error" || tone === "warning" ? ICONS.error : ICONS.info;
    const span = document.createElement("span");
    span.textContent = message;
    formStatus.appendChild(span);
  }

  function setFieldError(input, errorEl, message) {
    errorEl.textContent = message || "";
    if (message) input.setAttribute("aria-invalid", "true");
    else input.removeAttribute("aria-invalid");
  }

  function setLoading(btn, loading, label) {
    btn.disabled = loading;
    btn.classList.toggle("is-loading", loading);
    btn.setAttribute("aria-busy", String(loading));
    if (label) btn.querySelector(".btn-label").textContent = label;
  }

  let toastTimer;
  function toast(message) {
    toastEl.textContent = message;
    toastEl.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("is-visible"), 2200);
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fallback for non-secure contexts / older browsers
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch { ok = false; }
      ta.remove();
      return ok;
    }
  }

  /** Turn a FastAPI error payload into a readable sentence. */
  function errorMessage(data, status) {
    const detail = data && data.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail
        .map((d) => String(d.msg || "Invalid value").replace(/^Value error, /, ""))
        .join(" ");
    }
    if (status >= 500) return "The server ran into a problem. Please try again in a moment.";
    return `Request failed (HTTP ${status}).`;
  }

  class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status; }
  }

  async function api(path, options = {}, { onSlow } = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    const slow = onSlow ? setTimeout(onSlow, SLOW_NOTICE_MS) : null;
    try {
      const res = await fetch(`${API_BASE}${path}`, { ...options, signal: controller.signal });
      let data = null;
      try { data = await res.json(); } catch { /* non-JSON body */ }
      if (!res.ok) throw new ApiError(errorMessage(data, res.status), res.status);
      return data;
    } catch (err) {
      if (err instanceof ApiError) throw err;
      if (err.name === "AbortError") {
        throw new ApiError("The server took too long to respond. Please try again.", 0);
      }
      throw new ApiError("Can't reach the SnapLink server. Check your connection and try again.", 0);
    } finally {
      clearTimeout(timeout);
      if (slow) clearTimeout(slow);
    }
  }

  // ──────────────────────────────────────────────
  // Validation
  // ──────────────────────────────────────────────
  /** Returns { url } or { error }. Adds https:// when the scheme is missing. */
  function normalizeUrl(raw) {
    let value = raw.trim();
    if (!value) return { error: "Paste a link to shorten." };
    if (/\s/.test(value)) return { error: "URLs can't contain spaces." };
    if (!/^[a-z][a-z\d+.-]*:\/\//i.test(value)) value = `https://${value}`;

    let parsed;
    try { parsed = new URL(value); } catch { return { error: "That doesn't look like a valid URL." }; }
    if (!["http:", "https:"].includes(parsed.protocol)) {
      return { error: "Only http:// and https:// links can be shortened." };
    }
    const host = parsed.hostname;
    const looksLikeHost = host === "localhost" || /^\d{1,3}(\.\d{1,3}){3}$/.test(host) || /\.[a-z]{2,}$/i.test(host);
    if (!looksLikeHost) return { error: "Enter a full domain, like example.com." };
    return { url: value };
  }

  function validateAlias(value) {
    if (!value) return "";
    if (!/^[a-z0-9]+$/i.test(value)) return "Use letters and numbers only (no spaces, dashes or symbols).";
    if (value.length < 3 || value.length > 20) return "Aliases must be 3–20 characters long.";
    return "";
  }

  urlInput.addEventListener("input", () => {
    if (urlInput.getAttribute("aria-invalid")) setFieldError(urlInput, urlError, "");
    if (formStatus.dataset.tone) setStatus("");
  });
  urlInput.addEventListener("blur", () => {
    if (urlInput.value.trim()) {
      const { error } = normalizeUrl(urlInput.value);
      setFieldError(urlInput, urlError, error);
    }
  });
  aliasInput.addEventListener("input", () => {
    setFieldError(aliasInput, aliasError, validateAlias(aliasInput.value.trim()));
  });

  // ──────────────────────────────────────────────
  // Shorten
  // ──────────────────────────────────────────────
  shortenForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    setStatus("");

    const { url, error } = normalizeUrl(urlInput.value);
    setFieldError(urlInput, urlError, error);
    const alias = aliasInput.value.trim();
    const aliasProblem = validateAlias(alias);
    setFieldError(aliasInput, aliasError, aliasProblem);

    if (error) { urlInput.focus(); return; }
    if (aliasProblem) { advanced.open = true; aliasInput.focus(); return; }

    urlInput.value = url;
    const body = { url };
    if (alias) body.custom_code = alias;
    if (expirySelect.value) body.expires_in_days = Number(expirySelect.value);

    setLoading(shortenBtn, true, "Shortening…");
    try {
      const data = await api("/shorten", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }, {
        onSlow: () => setStatus("Checking the destination and waking up the server. This can take up to a minute on the first request.", "info"),
      });

      setStatus("");
      showResult(data);
      saveRecent(data);
      urlInput.value = "";
      aliasInput.value = "";
    } catch (err) {
      if (err.status === 409) {
        advanced.open = true;
        setFieldError(aliasInput, aliasError, `"${alias}" is already taken. Try another alias.`);
        aliasInput.focus();
        setStatus("");
      } else if (err.status === 400 && /not reachable/i.test(err.message)) {
        setStatus(`We couldn't reach that page. ${err.message.replace(/^URL is not reachable:\s*/i, "")}`, "error");
      } else {
        setStatus(err.message, "error");
      }
    } finally {
      setLoading(shortenBtn, false, "Shorten");
    }
  });

  function showResult(data) {
    currentResult = data;
    shortUrlEl.textContent = prettyUrl(data.short_url);
    shortUrlEl.href = data.short_url;
    openBtn.href = data.short_url;
    originalUrlEl.textContent = data.original_url;
    originalUrlEl.href = data.original_url;
    createdEl.textContent = formatDate(data.created_at);
    expiresEl.textContent = data.expires_at ? `${formatDate(data.expires_at)} (${relativeTime(data.expires_at)})` : "Never";
    resetCopyBtn();
    resultCard.hidden = false;
    resultCard.focus({ preventScroll: true });
    resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function resetCopyBtn() {
    copyBtn.classList.remove("is-success");
    copyBtn.querySelector(".btn-label").textContent = "Copy";
  }

  let copyTimer;
  copyBtn.addEventListener("click", async () => {
    if (!currentResult) return;
    const ok = await copyText(currentResult.short_url);
    if (ok) {
      copyBtn.classList.add("is-success");
      copyBtn.querySelector(".btn-label").textContent = "Copied!";
      toast("Link copied to clipboard");
      clearTimeout(copyTimer);
      copyTimer = setTimeout(resetCopyBtn, 2000);
    } else {
      toast("Couldn't copy. Select the link and copy it manually.");
    }
  });

  statsBtn.addEventListener("click", () => {
    if (currentResult) showAnalyticsFor(currentResult.short_code);
  });

  $("result-close").addEventListener("click", () => {
    resultCard.hidden = true;
    currentResult = null;
    urlInput.focus();
  });

  // ──────────────────────────────────────────────
  // Recent links (localStorage)
  // ──────────────────────────────────────────────
  function loadRecent() {
    try {
      const items = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      return Array.isArray(items) ? items.filter((i) => i && i.short_code && i.short_url) : [];
    } catch {
      return [];
    }
  }

  function storeRecent(items) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_RECENT))); } catch { /* storage unavailable */ }
  }

  function saveRecent(data) {
    const items = loadRecent().filter((i) => i.short_code !== data.short_code);
    items.unshift({
      short_code: data.short_code,
      short_url: data.short_url,
      original_url: data.original_url,
      created_at: data.created_at,
      expires_at: data.expires_at || null,
    });
    storeRecent(items);
    renderRecent();
  }

  $("recent-search").addEventListener("input", renderRecent);
  $("export-recent").addEventListener("click", () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(loadRecent(), null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = "snaplink-links.json"; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  function renderRecent() {
    const all = loadRecent();
    const query = $("recent-search").value.trim().toLowerCase();
    const items = all.filter(i => [i.short_code, i.original_url, i.short_url].join(" ").toLowerCase().includes(query));
    $("recent-count").textContent = `${items.length} of ${all.length} links`;
    $("export-recent").disabled = all.length === 0;
    recentList.replaceChildren(...items.map((item) => {
      const li = recentTpl.content.firstElementChild.cloneNode(true);
      li.dataset.code = item.short_code;
      const a = li.querySelector(".recent-short");
      a.href = item.short_url;
      a.textContent = prettyUrl(item.short_url);
      const orig = li.querySelector(".recent-original");
      orig.textContent = item.original_url;
      orig.title = item.original_url;
      const meta = li.querySelector(".recent-meta");
      if (isExpired(item.expires_at)) {
        meta.textContent = "Expired";
        meta.classList.add("is-expired");
      } else {
        meta.textContent = relativeTime(item.created_at);
        meta.title = formatDate(item.created_at);
      }
      return li;
    }));
    clearRecentBtn.hidden = all.length === 0;
  }

  recentList.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const code = btn.closest(".recent-item").dataset.code;
    const item = loadRecent().find((i) => i.short_code === code);
    if (!item) return;

    if (btn.dataset.action === "copy") {
      const ok = await copyText(item.short_url);
      toast(ok ? "Link copied to clipboard" : "Couldn't copy the link");
      if (ok) {
        btn.classList.add("is-success");
        setTimeout(() => btn.classList.remove("is-success"), 1500);
      }
    } else if (btn.dataset.action === "stats") {
      showAnalyticsFor(code);
    } else if (btn.dataset.action === "remove") {
      storeRecent(loadRecent().filter((i) => i.short_code !== code));
      renderRecent();
      toast("Removed from your list");
    }
  });

  clearRecentBtn.addEventListener("click", () => {
    if (!confirm("Remove all links from this list? The short links themselves keep working.")) return;
    storeRecent([]);
    renderRecent();
  });

  // ──────────────────────────────────────────────
  // Analytics
  // ──────────────────────────────────────────────
  /** Accepts "abc123" or "https://host/abc123" and returns the code. */
  function extractCode(raw) {
    const value = raw.trim();
    if (!value) return "";
    if (/^[a-z]+:\/\//i.test(value) || value.includes("/")) {
      try {
        const u = new URL(/^[a-z]+:\/\//i.test(value) ? value : `https://${value}`);
        return u.pathname.split("/").filter(Boolean).pop() || "";
      } catch { return ""; }
    }
    return value;
  }

  function showAnalyticsFor(code) {
    analyticsInput.value = code;
    analyticsForm.requestSubmit();
  }

  analyticsInput.addEventListener("input", () => setFieldError(analyticsInput, analyticsError, ""));

  analyticsForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const code = extractCode(analyticsInput.value);
    if (!code) {
      setFieldError(analyticsInput, analyticsError, "Enter a short code like 68g9xMH, or paste a full short link.");
      analyticsInput.focus();
      return;
    }
    if (!/^[a-z0-9]+$/i.test(code)) {
      setFieldError(analyticsInput, analyticsError, "Short codes only contain letters and numbers.");
      return;
    }
    setFieldError(analyticsInput, analyticsError, "");
    setLoading(analyticsBtn, true, "Loading…");
    try {
      const data = await api(`/analytics/${encodeURIComponent(code)}`);
      renderAnalytics(data);
      analyticsResults.hidden = false;
      analyticsResults.focus({ preventScroll: true });
      analyticsResults.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      analyticsResults.hidden = true;
      const msg = err.status === 404 ? `No link found for "${code}". Check the code and try again.` : err.message;
      setFieldError(analyticsInput, analyticsError, msg);
      document.getElementById("analytics").scrollIntoView({ behavior: "smooth", block: "start" });
    } finally {
      setLoading(analyticsBtn, false, "View stats");
    }
  });

  function renderAnalytics(data) {
    $("a-short-code").textContent = `${hostOf(API_BASE)}/${data.short_code}`;
    const orig = $("a-original-url");
    orig.textContent = data.original_url;
    orig.href = data.original_url;

    const state = $("a-state");
    if (isExpired(data.expires_at)) {
      state.textContent = "Expired";
      state.className = "badge badge-danger";
    } else {
      state.textContent = "Active";
      state.className = "badge badge-success";
    }

    $("a-total-clicks").textContent = data.total_clicks.toLocaleString();
    $("a-created").textContent = formatDate(data.created_at, false);
    $("a-expires").textContent = data.expires_at ? formatDate(data.expires_at, false) : "Never";

    const days = lastNDays(data.clicks_per_day || [], 14);
    const week = days.slice(-7).reduce((sum, d) => sum + d.count, 0);
    $("a-week-clicks").textContent = week.toLocaleString();

    renderChart(days);
    renderUserAgents(data.top_user_agents || []);
    renderClicksTable(data.recent_clicks || []);
  }

  /** Fill in zero-click days so the chart always shows a continuous range. */
  function lastNDays(clicksPerDay, n) {
    const byDate = new Map(clicksPerDay.map((d) => [d.date, d.count]));
    const out = [];
    const today = new Date();
    for (let i = n - 1; i >= 0; i--) {
      const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - i));
      const key = d.toISOString().slice(0, 10);
      out.push({ date: key, count: byDate.get(key) || 0, d });
    }
    return out;
  }

  function renderChart(days) {
    const container = $("chart-container");
    container.replaceChildren();
    const max = Math.max(...days.map((d) => d.count));
    const total = days.reduce((s, d) => s + d.count, 0);
    container.setAttribute("role", "img");
    container.setAttribute("aria-label", `${total} clicks in the last ${days.length} days`);

    if (total === 0) {
      const p = document.createElement("p");
      p.className = "muted-note";
      p.textContent = "No clicks in the last 14 days. Share your link to start collecting data.";
      container.appendChild(p);
      return;
    }

    for (const { count, d } of days) {
      const col = document.createElement("div");
      col.className = "chart-col";
      const label = d.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
      col.title = `${label}: ${count} click${count === 1 ? "" : "s"}`;

      const track = document.createElement("div");
      track.className = "chart-bar-track";
      const bar = document.createElement("div");
      bar.className = "chart-bar" + (count === 0 ? " is-zero" : "");
      bar.style.height = count === 0 ? "3px" : `${Math.max(6, (count / max) * 100)}%`;
      track.appendChild(bar);

      const lbl = document.createElement("span");
      lbl.className = "chart-label";
      lbl.textContent = String(d.getUTCDate());

      col.append(track, lbl);
      container.appendChild(col);
    }
  }

  /** Summarise a user-agent string as "Browser · OS". */
  function describeUA(ua) {
    if (!ua || ua === "unknown") return "Unknown";
    const browser =
      /Edg\//.test(ua) ? "Edge" :
      /OPR\/|Opera/.test(ua) ? "Opera" :
      /Firefox\//.test(ua) ? "Firefox" :
      /Chrome\//.test(ua) ? "Chrome" :
      /Safari\//.test(ua) ? "Safari" :
      /curl\//i.test(ua) ? "curl" :
      /bot|crawler|spider|preview/i.test(ua) ? "Bot / link preview" :
      /python|httpx|requests/i.test(ua) ? "Script" :
      ua.split(/[\s/]/)[0] || "Other";
    const os =
      /Android/.test(ua) ? "Android" :
      /iPhone|iPad|iOS/.test(ua) ? "iOS" :
      /Windows/.test(ua) ? "Windows" :
      /Mac OS X|Macintosh/.test(ua) ? "macOS" :
      /Linux/.test(ua) ? "Linux" : "";
    return os ? `${browser} · ${os}` : browser;
  }

  function renderUserAgents(list) {
    const container = $("ua-table");
    container.replaceChildren();
    if (!list.length) {
      const li = document.createElement("li");
      li.className = "muted-note";
      li.textContent = "No visits yet.";
      container.appendChild(li);
      return;
    }
    const max = Math.max(...list.map((u) => u.count));
    for (const { user_agent, count } of list) {
      const li = document.createElement("li");
      li.className = "ua-row";
      const name = document.createElement("span");
      name.className = "ua-name";
      name.textContent = describeUA(user_agent);
      name.title = user_agent || "Unknown";
      const c = document.createElement("span");
      c.className = "ua-count";
      c.textContent = count.toLocaleString();
      const bar = document.createElement("span");
      bar.className = "ua-bar";
      const fill = document.createElement("span");
      fill.style.width = `${(count / max) * 100}%`;
      bar.appendChild(fill);
      li.append(name, c, bar);
      container.appendChild(li);
    }
  }

  function renderClicksTable(clicks) {
    const tbody = $("clicks-tbody");
    tbody.replaceChildren();
    if (!clicks.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 3;
      td.className = "muted-note";
      td.textContent = "No clicks recorded yet.";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    for (const { timestamp, ip_address, user_agent } of clicks) {
      const tr = document.createElement("tr");
      const cells = [
        [formatDate(timestamp), ""],
        [ip_address || "—", "mono"],
        [describeUA(user_agent), ""],
      ];
      for (const [text, cls] of cells) {
        const td = document.createElement("td");
        td.textContent = text;
        if (cls) td.className = cls;
        tr.appendChild(td);
      }
      tr.lastChild.title = user_agent || "";
      tr.firstChild.title = relativeTime(timestamp);
      tbody.appendChild(tr);
    }
  }

  // ──────────────────────────────────────────────
  // Backend status
  // ──────────────────────────────────────────────
  async function checkHealth() {
    const text = apiStatus.querySelector(".api-status-text");
    apiStatus.dataset.state = "checking";
    text.textContent = "Connecting…";
    try {
      const data = await api("/health");
      const ok = data.status === "healthy";
      apiStatus.dataset.state = ok ? "ok" : "degraded";
      text.textContent = ok ? "All systems normal" : "Degraded";
      apiStatus.title = `Database: ${data.database}, cache: ${data.cache}`;
    } catch {
      apiStatus.dataset.state = "down";
      text.textContent = "Server offline";
      apiStatus.title = `Can't reach ${API_BASE}`;
    }
  }

  // ──────────────────────────────────────────────
  // Init
  // ──────────────────────────────────────────────
  renderRecent();
  checkHealth();
})();
