/**
 * script.js — SnapLink URL Shortener Frontend Logic
 *
 * Handles:
 * - URL shortening (POST /shorten)
 * - Copy / Open / Verify short link
 * - Analytics loading and chart rendering (GET /analytics/{code})
 */

// ──────────────────────────────────────────────
// Configuration — change BASE_URL to your deployed backend
// ──────────────────────────────────────────────
const BASE_URL = "http://localhost:8000";

// ──────────────────────────────────────────────
// DOM References (cached for performance)
// ──────────────────────────────────────────────
const urlInput = document.getElementById("url-input");
const shortenBtn = document.getElementById("shorten-btn");
const statusMsg = document.getElementById("status-msg");
const resultCard = document.getElementById("result-card");
const shortUrlDisplay = document.getElementById("short-url-display");
const originalUrlDisplay = document.getElementById("original-url-display");
const expiresDisplay = document.getElementById("expires-display");
const checkResult = document.getElementById("check-result");

// ──────────────────────────────────────────────
// Utility Helpers
// ──────────────────────────────────────────────

/** Show a status message below the input card */
function showStatus(msg, type = "info") {
    statusMsg.textContent = msg;
    statusMsg.className = `status-msg ${type}`;
    statusMsg.classList.remove("hidden");
}

/** Hide the status message */
function clearStatus() {
    statusMsg.classList.add("hidden");
    statusMsg.textContent = "";
}

/** Toggle the Shorten button spinner vs text */
function setLoading(isLoading) {
    const btnText = shortenBtn.querySelector(".btn-text");
    const btnLoader = shortenBtn.querySelector(".btn-loader");
    shortenBtn.disabled = isLoading;
    btnText.classList.toggle("hidden", isLoading);
    btnLoader.classList.toggle("hidden", !isLoading);
}

/** Format a UTC date string to a readable local format */
function formatDate(isoStr) {
    if (!isoStr) return "Never";
    const d = new Date(isoStr);
    return d.toLocaleDateString("en-IN", {
        day: "2-digit", month: "short", year: "numeric",
        hour: "2-digit", minute: "2-digit",
    });
}

// ──────────────────────────────────────────────
// Main: Shorten URL
// ──────────────────────────────────────────────
async function shortenUrl() {
    clearStatus();
    checkResult.classList.add("hidden");

    const longUrl = urlInput.value.trim();
    const customCode = document.getElementById("custom-code").value.trim();
    const expiryDays = parseInt(document.getElementById("expiry-days").value) || null;

    // Basic client-side validation
    if (!longUrl) {
        showStatus("⚠️ Please enter a URL to shorten.", "error");
        return;
    }
    if (!longUrl.startsWith("http://") && !longUrl.startsWith("https://")) {
        showStatus("⚠️ URL must start with http:// or https://", "error");
        return;
    }

    setLoading(true);
    showStatus("⏳ Validating and shortening your URL…", "info");

    const body = { url: longUrl };
    if (customCode) body.custom_code = customCode;
    if (expiryDays) body.expires_in_days = expiryDays;

    try {
        const response = await fetch(`${BASE_URL}/shorten`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });

        const data = await response.json();

        if (!response.ok) {
            // Server returned an error
            const detail = data.detail || "Failed to shorten URL.";
            showStatus(`❌ ${detail}`, "error");
            return;
        }

        // Success — populate result card
        clearStatus();
        shortUrlDisplay.textContent = data.short_url;
        shortUrlDisplay.href = data.short_url;
        originalUrlDisplay.textContent = `Original: ${data.original_url}`;
        expiresDisplay.textContent = data.expires_at
            ? `Expires: ${formatDate(data.expires_at)}`
            : "Expires: Never";

        resultCard.classList.remove("hidden");
        resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });

    } catch (err) {
        console.error("Shorten error:", err);
        showStatus("❌ Network error — is the backend running?", "error");
    } finally {
        setLoading(false);
    }
}

// ──────────────────────────────────────────────
// Copy Link
// ──────────────────────────────────────────────
async function copyLink() {
    const shortUrl = shortUrlDisplay.textContent;
    if (!shortUrl) return;
    try {
        await navigator.clipboard.writeText(shortUrl);
        const copyBtn = document.getElementById("copy-btn");
        copyBtn.querySelector("span").textContent = "✅ Copied!";
        setTimeout(() => {
            copyBtn.querySelector("span").textContent = "📋 Copy";
        }, 2000);
    } catch {
        // Fallback for older browsers
        const input = document.createElement("input");
        input.value = shortUrl;
        document.body.appendChild(input);
        input.select();
        document.execCommand("copy");
        document.body.removeChild(input);
    }
}

// ──────────────────────────────────────────────
// Open Link in New Tab
// ──────────────────────────────────────────────
function openLink() {
    const shortUrl = shortUrlDisplay.textContent;
    if (shortUrl) window.open(shortUrl, "_blank", "noopener,noreferrer");
}

// ──────────────────────────────────────────────
// Check / Verify Link (GET /preview/{short_code})
// ──────────────────────────────────────────────
async function checkLink() {
    const shortUrl = shortUrlDisplay.textContent;
    if (!shortUrl) return;

    // Extract short_code from full URL
    const shortCode = shortUrl.split("/").pop();

    checkResult.className = "check-result";
    checkResult.classList.remove("hidden");
    checkResult.textContent = "⏳ Checking…";

    try {
        const res = await fetch(`${BASE_URL}/preview/${shortCode}`);
        const data = await res.json();

        if (res.ok) {
            checkResult.classList.add("ok");
            checkResult.innerHTML = `
        ✅ Link is <strong>active</strong><br/>
        Destination: <em>${data.original_url}</em><br/>
        Total clicks: <strong>${data.total_clicks}</strong>
      `;
        } else {
            checkResult.classList.add("fail");
            checkResult.textContent = `❌ ${data.detail || "Link not found or expired."}`;
        }
    } catch {
        checkResult.classList.add("fail");
        checkResult.textContent = "❌ Network error while checking link.";
    }
}

// ──────────────────────────────────────────────
// Analytics Loader
// ──────────────────────────────────────────────
async function loadAnalytics() {
    const code = document.getElementById("analytics-code").value.trim();
    if (!code) {
        alert("Please enter a short code.");
        return;
    }

    const resultsDiv = document.getElementById("analytics-results");
    resultsDiv.classList.add("hidden");

    try {
        const res = await fetch(`${BASE_URL}/analytics/${code}`);
        const data = await res.json();

        if (!res.ok) {
            alert(data.detail || "Short code not found.");
            return;
        }

        // Populate header
        document.getElementById("a-short-code").textContent = `⚡ ${data.short_code}`;
        const aUrl = document.getElementById("a-original-url");
        aUrl.textContent = data.original_url;
        aUrl.href = data.original_url;

        document.getElementById("a-total-clicks").textContent = data.total_clicks;
        document.getElementById("a-created").textContent = formatDate(data.created_at);
        document.getElementById("a-expires").textContent = formatDate(data.expires_at);

        // Render chart
        renderChart(data.clicks_per_day);

        // Render user agents
        renderUserAgents(data.top_user_agents, data.total_clicks);

        // Render recent clicks
        renderClicksTable(data.recent_clicks);

        resultsDiv.classList.remove("hidden");
        resultsDiv.scrollIntoView({ behavior: "smooth", block: "start" });

    } catch (err) {
        console.error("Analytics error:", err);
        alert("Network error — is the backend running?");
    }
}

// ──────────────────────────────────────────────
// Render Bar Chart (clicks per day)
// ──────────────────────────────────────────────
function renderChart(clicksPerDay) {
    const container = document.getElementById("chart-container");
    container.innerHTML = "";

    if (!clicksPerDay || clicksPerDay.length === 0) {
        container.innerHTML = `<span style="color:var(--text-muted);font-size:13px">No click data yet.</span>`;
        return;
    }

    const maxCount = Math.max(...clicksPerDay.map(d => d.count));

    clicksPerDay.forEach(({ date, count }) => {
        const heightPct = maxCount > 0 ? (count / maxCount) * 80 : 4;
        const label = date.slice(5); // MM-DD

        const wrapper = document.createElement("div");
        wrapper.className = "chart-bar-wrapper";
        wrapper.title = `${date}: ${count} clicks`;

        const bar = document.createElement("div");
        bar.className = "chart-bar";
        bar.style.height = `${heightPct}px`;

        const dateLabel = document.createElement("div");
        dateLabel.className = "chart-date";
        dateLabel.textContent = label;

        wrapper.appendChild(bar);
        wrapper.appendChild(dateLabel);
        container.appendChild(wrapper);
    });
}

// ──────────────────────────────────────────────
// Render User Agents Bar List
// ──────────────────────────────────────────────
function renderUserAgents(userAgents, totalClicks) {
    const container = document.getElementById("ua-table");
    container.innerHTML = "";

    if (!userAgents || userAgents.length === 0) {
        container.innerHTML = `<span style="color:var(--text-muted);font-size:13px">No data yet.</span>`;
        return;
    }

    const maxCount = Math.max(...userAgents.map(u => u.count));

    userAgents.forEach(({ user_agent, count }) => {
        const pct = maxCount > 0 ? (count / maxCount) * 100 : 0;

        const row = document.createElement("div");
        row.className = "ua-row";
        row.innerHTML = `
      <div class="ua-agent" title="${user_agent}">${user_agent || "Unknown"}</div>
      <div class="ua-bar-bg"><div class="ua-bar-fill" style="width:${pct}%"></div></div>
      <div class="ua-label">${count}</div>
    `;
        container.appendChild(row);
    });
}

// ──────────────────────────────────────────────
// Render Recent Clicks Table
// ──────────────────────────────────────────────
function renderClicksTable(recentClicks) {
    const tbody = document.getElementById("clicks-tbody");
    tbody.innerHTML = "";

    if (!recentClicks || recentClicks.length === 0) {
        tbody.innerHTML = `<tr><td colspan="3" style="color:var(--text-muted)">No clicks recorded yet.</td></tr>`;
        return;
    }

    recentClicks.forEach(({ timestamp, ip_address, user_agent }) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
      <td>${formatDate(timestamp)}</td>
      <td>${ip_address || "—"}</td>
      <td title="${user_agent || ""}">${(user_agent || "—").slice(0, 60)}</td>
    `;
        tbody.appendChild(tr);
    });
}

// ──────────────────────────────────────────────
// Allow pressing Enter in the URL input
// ──────────────────────────────────────────────
urlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") shortenUrl();
});

document.getElementById("analytics-code").addEventListener("keydown", (e) => {
    if (e.key === "Enter") loadAnalytics();
});
