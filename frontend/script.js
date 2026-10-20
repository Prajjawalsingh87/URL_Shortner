/**
 * script.js — SnapLink frontend
 *
 * - Shorten URLs (POST /shorten) with optional custom alias + expiry
 * - Copy / open the result, keep a "recent links" list in localStorage
 * - Bulk shorten up to 20 links (POST /shorten/bulk), copy all / CSV
 * - QR code for every short link (generated in the browser), PNG download
 * - Link preview card (title / image / description fetched by the backend)
 * - Analytics for any short code (GET /analytics/{code}): countries,
 *   devices, browsers, OS and referrers
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
  const PROD_API_BASE = "https://snaplink-api-six.vercel.app";

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
  const resultPreview = $("result-preview");
  const resultQr = $("result-qr");

  const bulkForm = $("bulk-form");
  const bulkInput = $("bulk-input");
  const bulkError = $("bulk-error");
  const bulkCount = $("bulk-count");
  const bulkBtn = $("bulk-btn");
  const bulkResults = $("bulk-results");
  const bulkList = $("bulk-list");
  const BULK_MAX = 20;

  const qrDialog = $("qr-dialog");

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
  // QR codes (qrcode-generator, loaded from jsDelivr)
  // ──────────────────────────────────────────────
  /** Draw `text` as a QR code onto `canvas` (black on white, 4-module quiet zone). */
  function drawQR(canvas, text, size) {
    const ctx = canvas.getContext("2d");
    if (typeof window.qrcode !== "function") {
      canvas.width = canvas.height = size;
      ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, size, size);
      ctx.fillStyle = "#555"; ctx.font = "13px sans-serif"; ctx.textAlign = "center";
      ctx.fillText("QR unavailable", size / 2, size / 2);
      return false;
    }
    const qr = window.qrcode(0, "M");
    qr.addData(text);
    qr.make();
    const modules = qr.getModuleCount();
    const quiet = 4;
    const total = modules + quiet * 2;
    // On-screen canvases are sized by CSS; draw at >= device resolution so they stay sharp
    const dpr = canvas.dataset.export ? 1 : Math.max(2, window.devicePixelRatio || 1);
    const scale = Math.max(1, Math.ceil((size * dpr) / total));
    const px = total * scale;
    canvas.width = px;
    canvas.height = px;
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, px, px);
    ctx.fillStyle = "#0f1222";
    for (let r = 0; r < modules; r++) {
      for (let c = 0; c < modules; c++) {
        if (qr.isDark(r, c)) ctx.fillRect((c + quiet) * scale, (r + quiet) * scale, scale, scale);
      }
    }
    canvas.dataset.qrText = text;
    return true;
  }

  /** Render a 1024px QR code off-screen and download it as a PNG. */
  function downloadQR(text, code) {
    const canvas = document.createElement("canvas");
    canvas.dataset.export = "1";
    if (!drawQR(canvas, text, 1024)) { toast("QR code library didn't load. Try reloading the page."); return; }
    canvas.toBlob((blob) => {
      if (!blob) { toast("Couldn't create the PNG"); return; }
      downloadBlob(blob, `snaplink-${code}-qr.png`);
      toast("QR code downloaded");
    }, "image/png");
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  let dialogItem = null;
  function openQrDialog(item) {
    dialogItem = item;
    $("qr-dialog-link").textContent = prettyUrl(item.short_url);
    drawQR($("qr-dialog-canvas"), item.short_url, 240);
    if (typeof qrDialog.showModal === "function") qrDialog.showModal();
    else qrDialog.setAttribute("open", "");
  }
  function closeQrDialog() {
    if (typeof qrDialog.close === "function") qrDialog.close();
    else qrDialog.removeAttribute("open");
  }
  $("qr-dialog-close").addEventListener("click", closeQrDialog);
  qrDialog.addEventListener("click", (e) => { if (e.target === qrDialog) closeQrDialog(); });
  $("qr-dialog-download").addEventListener("click", () => {
    if (dialogItem) downloadQR(dialogItem.short_url, dialogItem.short_code);
  });

  // ──────────────────────────────────────────────
  // Link preview card
  // ──────────────────────────────────────────────
  function renderPreview(el, data) {
    if (!data.title && !data.image_url) { el.hidden = true; return; }
    el.href = data.original_url;
    el.querySelector(".link-preview-host").textContent = hostOf(data.original_url).replace(/^www\./, "");
    el.querySelector(".link-preview-title").textContent = data.title || prettyUrl(data.original_url);
    const desc = el.querySelector(".link-preview-desc");
    desc.textContent = data.description || "";
    desc.hidden = !data.description;
    const img = el.querySelector(".link-preview-img");
    if (data.image_url && /^https?:\/\//i.test(data.image_url)) {
      img.hidden = false;
      img.onerror = () => { img.hidden = true; img.removeAttribute("src"); };
      img.src = data.image_url;
    } else {
      img.hidden = true;
      img.removeAttribute("src");
    }
    el.hidden = false;
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
      saveRecentAndRender(data);
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
    renderPreview(resultPreview, data);
    drawQR(resultQr, data.short_url, 148);
    resultQr.setAttribute("aria-label", `QR code for ${prettyUrl(data.short_url)}`);
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

  $("qr-download-btn").addEventListener("click", () => {
    if (currentResult) downloadQR(currentResult.short_url, currentResult.short_code);
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
  // Bulk shorten
  // ──────────────────────────────────────────────
  let bulkData = [];

  function bulkLines() {
    return bulkInput.value.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  }

  function updateBulkCount() {
    const n = bulkLines().length;
    bulkCount.textContent = `${n} / ${BULK_MAX}`;
    bulkCount.classList.toggle("is-over", n > BULK_MAX);
  }
  bulkInput.addEventListener("input", () => {
    updateBulkCount();
    if (bulkInput.getAttribute("aria-invalid")) setFieldError(bulkInput, bulkError, "");
  });

  bulkForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const lines = bulkLines();
    if (!lines.length) {
      setFieldError(bulkInput, bulkError, "Paste at least one link, one per line.");
      bulkInput.focus();
      return;
    }
    if (lines.length > BULK_MAX) {
      setFieldError(bulkInput, bulkError, `That's ${lines.length} links. Bulk shorten takes up to ${BULK_MAX} at a time.`);
      bulkInput.focus();
      return;
    }
    setFieldError(bulkInput, bulkError, "");
    const body = { urls: lines };
    const expiry = $("bulk-expiry").value;
    if (expiry) body.expires_in_days = Number(expiry);

    setLoading(bulkBtn, true, `Shortening ${lines.length}…`);
    try {
      const data = await api("/shorten/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      bulkData = data.results;
      // Save successes to "recent", keeping the pasted order (first line on top)
      for (const r of [...data.results].reverse()) if (r.ok) saveRecent(r.link);
      renderRecent();
      renderBulk(data);
      if (data.failed === 0) bulkInput.value = "";
      else bulkInput.value = data.results.filter((r) => !r.ok).map((r) => r.input).join("\n");
      updateBulkCount();
    } catch (err) {
      setFieldError(bulkInput, bulkError, err.message);
    } finally {
      setLoading(bulkBtn, false, "Shorten all");
    }
  });

  function renderBulk(data) {
    $("bulk-summary").textContent = data.failed
      ? `${data.succeeded} of ${data.total} links shortened · ${data.failed} failed (left in the box so you can fix them)`
      : `All ${data.total} link${data.total === 1 ? "" : "s"} shortened`;
    $("bulk-copy").disabled = $("bulk-csv").disabled = data.succeeded === 0;
    bulkList.replaceChildren(...data.results.map((r) => {
      const li = document.createElement("li");
      li.className = "bulk-item" + (r.ok ? "" : " is-error");
      const main = document.createElement("div");
      main.className = "bulk-main";
      const orig = document.createElement("span");
      orig.className = "bulk-original";
      orig.textContent = r.ok ? (r.link.title || r.link.original_url) : r.input;
      orig.title = r.ok ? r.link.original_url : r.input;
      main.appendChild(orig);
      if (r.ok) {
        const a = document.createElement("a");
        a.className = "bulk-short";
        a.href = r.link.short_url; a.target = "_blank"; a.rel = "noopener";
        a.textContent = prettyUrl(r.link.short_url);
        main.prepend(a);
      } else {
        const err = document.createElement("span");
        err.className = "bulk-err";
        err.textContent = r.error;
        main.appendChild(err);
      }
      li.appendChild(main);
      if (r.ok) {
        const actions = document.createElement("div");
        actions.className = "recent-actions";
        for (const [action, label, icon] of [
          ["copy", "Copy link", '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>'],
          ["qr", "Show QR code", '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><path d="M14 14h2v2h-2zM18 18h2v2h-2z"/>'],
        ]) {
          const b = document.createElement("button");
          b.type = "button"; b.className = "icon-btn";
          b.dataset.action = action; b.dataset.code = r.link.short_code;
          b.setAttribute("aria-label", label);
          b.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${icon}</svg>`;
          actions.appendChild(b);
        }
        li.appendChild(actions);
      }
      return li;
    }));
    bulkResults.hidden = false;
    bulkResults.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  bulkList.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const r = bulkData.find((x) => x.ok && x.link.short_code === btn.dataset.code);
    if (!r) return;
    if (btn.dataset.action === "copy") {
      const ok = await copyText(r.link.short_url);
      toast(ok ? "Link copied to clipboard" : "Couldn't copy the link");
    } else {
      openQrDialog(r.link);
    }
  });

  $("bulk-copy").addEventListener("click", async () => {
    const urls = bulkData.filter((r) => r.ok).map((r) => r.link.short_url);
    const ok = await copyText(urls.join("\n"));
    toast(ok ? `Copied ${urls.length} link${urls.length === 1 ? "" : "s"}` : "Couldn't copy the links");
  });

  /** CSV cell: quote, double quotes, and neutralise spreadsheet formulas. */
  function csvCell(value) {
    let v = value == null ? "" : String(value);
    if (/^[=+\-@\t\r]/.test(v)) v = `'${v}`;
    return `"${v.replace(/"/g, '""')}"`;
  }

  $("bulk-csv").addEventListener("click", () => {
    const rows = [["original_url", "short_url", "short_code", "title", "status", "error"]];
    for (const r of bulkData) {
      rows.push(r.ok
        ? [r.link.original_url, r.link.short_url, r.link.short_code, r.link.title || "", "ok", ""]
        : [r.input, "", "", "", "error", r.error || ""]);
    }
    const csv = rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
    downloadBlob(new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" }), "snaplink-bulk.csv");
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
      title: data.title || null,
    });
    storeRecent(items);
  }

  function saveRecentAndRender(data) {
    saveRecent(data);
    renderRecent();
  }

  $("recent-search").addEventListener("input", renderRecent);
  $("export-recent").addEventListener("click", () => {
    downloadBlob(new Blob([JSON.stringify(loadRecent(), null, 2)], { type: "application/json" }), "snaplink-links.json");
  });
  function renderRecent() {
    const all = loadRecent();
    const query = $("recent-search").value.trim().toLowerCase();
    const items = all.filter(i => [i.short_code, i.original_url, i.short_url, i.title || ""].join(" ").toLowerCase().includes(query));
    $("recent-count").textContent = `${items.length} of ${all.length} links`;
    $("export-recent").disabled = all.length === 0;
    recentList.replaceChildren(...items.map((item) => {
      const li = recentTpl.content.firstElementChild.cloneNode(true);
      li.dataset.code = item.short_code;
      const a = li.querySelector(".recent-short");
      a.href = item.short_url;
      a.textContent = prettyUrl(item.short_url);
      const orig = li.querySelector(".recent-original");
      orig.textContent = item.title ? `${item.title} · ${prettyUrl(item.original_url)}` : item.original_url;
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
    } else if (btn.dataset.action === "qr") {
      openQrDialog(item);
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
    const title = $("a-title");
    title.textContent = data.title || "";
    title.hidden = !data.title;

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
    renderBreakdown($("bd-countries"), data.top_countries || [], countryLabel,
      "No country data yet. Countries are recorded for visits through the live site.");
    renderBreakdown($("bd-devices"), data.top_devices || [], deviceLabel);
    renderBreakdown($("bd-browsers"), data.top_browsers || []);
    renderBreakdown($("bd-os"), data.top_os || []);
    renderBreakdown($("bd-referrers"), data.top_referrers || []);
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

  const regionNames = (() => {
    try { return new Intl.DisplayNames(undefined, { type: "region" }); } catch { return null; }
  })();

  function flagEmoji(code) {
    if (!/^[A-Z]{2}$/.test(code)) return "";
    return String.fromCodePoint(...[...code].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
  }

  function countryLabel(code) {
    if (!code) return "—";
    let name = code;
    try { name = regionNames?.of(code) || code; } catch { /* unknown code */ }
    const flag = flagEmoji(code);
    return flag ? `${flag} ${name}` : name;
  }

  const DEVICE_LABELS = { desktop: "Desktop", mobile: "Mobile", tablet: "Tablet", bot: "Bot / script", unknown: "Unknown" };
  function deviceLabel(d) { return DEVICE_LABELS[d] || d || "—"; }

  /** Horizontal bar list for a [{name, count}] breakdown. */
  function renderBreakdown(container, list, label = (x) => x, emptyText = "No visits yet.") {
    container.replaceChildren();
    if (!list.length) {
      const li = document.createElement("li");
      li.className = "muted-note";
      li.textContent = emptyText;
      container.appendChild(li);
      return;
    }
    const max = Math.max(...list.map((u) => u.count));
    for (const { name, count } of list) {
      const li = document.createElement("li");
      li.className = "ua-row";
      const n = document.createElement("span");
      n.className = "ua-name";
      n.textContent = label(name);
      n.title = name;
      const c = document.createElement("span");
      c.className = "ua-count";
      c.textContent = count.toLocaleString();
      const bar = document.createElement("span");
      bar.className = "ua-bar";
      const fill = document.createElement("span");
      fill.style.width = `${(count / max) * 100}%`;
      bar.appendChild(fill);
      li.append(n, c, bar);
      container.appendChild(li);
    }
  }

  function renderClicksTable(clicks) {
    const tbody = $("clicks-tbody");
    tbody.replaceChildren();
    if (!clicks.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 6;
      td.className = "muted-note";
      td.textContent = "No clicks recorded yet.";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    for (const { timestamp, ip_address, user_agent, country, device, browser, os, referrer } of clicks) {
      const tr = document.createElement("tr");
      const cells = [
        [formatDate(timestamp), ""],
        [country ? countryLabel(country) : "—", ""],
        [deviceLabel(device), ""],
        [[browser, os].filter((x) => x && x !== "Unknown" && x !== "Other").join(" · ") || "Unknown", ""],
        [referrer || "Direct", ""],
        [ip_address || "—", "mono"],
      ];
      for (const [text, cls] of cells) {
        const td = document.createElement("td");
        td.textContent = text;
        if (cls) td.className = cls;
        tr.appendChild(td);
      }
      tr.children[3].title = user_agent || "";
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
  updateBulkCount();
  checkHealth();
})();
