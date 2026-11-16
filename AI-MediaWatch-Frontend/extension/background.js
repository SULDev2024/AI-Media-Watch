const API_BASE = "http://127.0.0.1:8000";

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "CHECK_SCAM") {
    checkScam({ text: msg.text, url: msg.url })
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ error: e.message }));
    return true;
  }
  if (msg.type === "GET_STATUS") {
    getStatus()
      .then((r) => sendResponse(r))
      .catch((e) => sendResponse({ connected: false, error: e.message }));
    return true;
  }
  if (msg.type === "UPDATE_BADGE") {
    try {
      chrome.storage.local.set({
        scanCount: msg.scanCount || 0,
        scamCount: msg.scamCount || 0,
      });
      if (msg.scamCount > 0) {
        chrome.action.setBadgeText({ text: String(msg.scamCount) });
        chrome.action.setBadgeBackgroundColor({ color: "#ef4444" });
      }
    } catch (e) {
      console.warn("[AIMW BG] badge error:", e);
    }
  }
});

function isSupportedUrl(url) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    return (
      parsed.protocol === "http:" ||
      parsed.protocol === "https:"
    ) && (
      host.endsWith("youtube.com") ||
      host === "youtu.be" ||
      host.endsWith("t.me") ||
      host.endsWith("telegram.org") ||
      host.endsWith("tiktok.com") ||
      host.endsWith("instagram.com")
    );
  } catch {
    return false;
  }
}

function normalizeYouTubeUrl(url) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    // Convert /shorts/VIDEO_ID → standard watch URL that yt-dlp understands
    if (host.endsWith("youtube.com") && parsed.pathname.startsWith("/shorts/")) {
      const videoId = parsed.pathname.split("/shorts/")[1].split(/[?&#/]/)[0];
      if (videoId) return `https://www.youtube.com/watch?v=${videoId}`;
    }
    // youtu.be/VIDEO_ID is already handled by yt-dlp
    return url;
  } catch {
    return url;
  }
}

function isShortsOrReel(url) {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    if (host.endsWith("youtube.com") && parsed.pathname.startsWith("/shorts/")) return true;
    if (host.endsWith("instagram.com") && parsed.pathname.includes("/reel/")) return true;
    if (host.endsWith("tiktok.com")) return true;
    return false;
  } catch {
    return false;
  }
}

async function checkScam(input) {
  const rawUrl = input && isSupportedUrl(input.url) ? input.url : null;
  const url = rawUrl ? normalizeYouTubeUrl(rawUrl) : null;
  const text = String((input && input.text) || "").trim();
  const hasText = text.length >= 10;
  const shortForm = rawUrl && isShortsOrReel(rawUrl);

  // Strategy depends on content type:
  //
  // SHORTS / REELS (short-form video):
  //   → Text-first for instant verdict (2-5s) — user sees result NOW
  //   → URL queued in background for deep scan → Dashboard gets full result
  //
  // REGULAR VIDEOS (long-form):
  //   → URL-first for full pipeline (download → Whisper → Vision LLM)
  //   → Text as fire-and-forget backup
  //
  // TEXT ONLY (no URL):
  //   → Text analysis only

  let primaryBody;
  let deepScanUrl = null;

  if (shortForm && hasText) {
    // Shorts/Reels: fast text verdict first, deep URL scan in background
    primaryBody = { text };
    deepScanUrl = url;
    console.log("[AIMW BG] Short-form content — text-first for speed, URL deep-scan queued");
  } else if (url) {
    // Regular video: URL as primary for full pipeline
    primaryBody = { url };
    if (hasText) {
      fetch(`${API_BASE}/api/v1/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      }).catch(() => {});
    }
  } else if (hasText) {
    primaryBody = { text };
  } else {
    return { error: "No content to analyze" };
  }

  // Submit primary analysis
  const resp = await fetch(`${API_BASE}/api/v1/check`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(primaryBody),
  });
  if (!resp.ok) {
    const errBody = await resp.text();
    console.warn("[AIMW BG] API submit error:", resp.status, errBody);
    return { error: `API ${resp.status}: ${errBody}` };
  }
  const data = await resp.json();
  const videoId = data.video_id;
  console.log("[AIMW BG] Submitted, polling:", videoId);

  // Fire-and-forget deep scan for Shorts/Reels (shows in Dashboard later)
  if (deepScanUrl) {
    fetch(`${API_BASE}/api/v1/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: deepScanUrl }),
    }).catch(() => {});
  }

  // Poll for result — text analysis is fast (5-10s), URL takes longer
  const isTextPrimary = shortForm || !url;
  const maxIter = isTextPrimary ? 20 : 60;
  for (let i = 0; i < maxIter; i++) {
    await sleep(i < 10 ? 500 : 1000);
    try {
      const rResp = await fetch(`${API_BASE}/api/v1/check/${videoId}`);
      if (!rResp.ok) continue;
      const r = await rResp.json();
      if (r.status === "done") {
        const level = r.risk_level || "LOW";
        const score = r.risk_score || 0;
        const result = {
          videoId,
          level,
          score,
          confidence: score,
          action: r.recommended_action || "clear",
          summary: r.summary || "",
          videoPipelineQueued: !!deepScanUrl,
        };
        console.log("[AIMW BG] Result:", level, score, shortForm ? "(short-form)" : "");
        if (shortForm) {
          // Shorts/Reels: always notify so user sees every verdict
          showNotification(result, (text || url || "").substring(0, 100));
        } else if (level === "HIGH" || level === "CRITICAL") {
          showNotification(result, (text || url || "").substring(0, 100));
        }
        return result;
      }
      if (r.status === "failed") {
        return { level: "UNKNOWN", score: 0, confidence: 0, error: "Analysis failed" };
      }
    } catch (e) {
      console.warn("[AIMW BG] Poll error:", e.message);
    }
  }
  return {
    level: "PENDING",
    score: 0,
    confidence: 0,
    action: "review",
    summary: "Analysis in progress — check Dashboard for full results.",
    videoPipelineQueued: !!deepScanUrl,
  };
}

function showNotification(result, snippet) {
  const level = result.level || "UNKNOWN";
  const pct = Math.round((result.score || 0) * 100);
  let title, priority;
  if (level === "HIGH" || level === "CRITICAL") {
    title = `🚨 SCAM DETECTED — ${level}`;
    priority = 2;
  } else if (level === "MEDIUM") {
    title = `⚠️ SUSPICIOUS — Medium Risk`;
    priority = 1;
  } else {
    title = `✅ SAFE — No Scam Detected`;
    priority = 0;
  }
  chrome.notifications.create(`aimw-${Date.now()}`, {
    type: "basic",
    iconUrl: "icons/icon128.png",
    title,
    message: `Risk: ${pct}% | ${snippet}`,
    priority,
  });
}

async function getStatus() {
  try {
    const resp = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(3000) });
    if (resp.ok) {
      const data = await resp.json().catch(() => ({}));
      return { connected: true, version: data.version || "?" };
    }
  } catch (e) {
    // fall through
  }
  return { connected: false, error: "API not reachable" };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

console.log("[AIMW BG] Service worker loaded");
