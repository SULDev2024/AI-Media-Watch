(() => {
  "use strict";

  const SCAN_INTERVAL_MS = 2000;
  const MIN_TEXT_LENGTH = 20;
  const scannedHashes = new Set();
  let scanCount = 0;
  let scamCount = 0;
  let lastUrl = location.href;
  // Token increments on every URL change; in-flight analyses captured at older
  // tokens are stale and must be discarded so verdicts never leak between videos.
  let currentToken = 0;

  function clearAllOverlays() {
    document.querySelectorAll(".aimw-scanning, .aimw-warning, .aimw-safe, .aimw-toast")
      .forEach((el) => el.remove());
  }

  function getPlatform() {
    const host = location.hostname;
    if (host.includes("instagram.com")) return "instagram";
    if (host.includes("youtube.com") || host === "youtu.be") return "youtube";
    if (host.includes("tiktok.com")) return "tiktok";
    if (host.includes("telegram.org") || host === "t.me") return "telegram";
    return null;
  }

  function isVideoPage() {
    const platform = getPlatform();
    if (platform === "youtube") {
      return (
        location.pathname === "/watch" ||
        location.pathname.startsWith("/shorts/") ||
        location.hostname === "youtu.be"
      );
    }
    if (platform === "tiktok") return location.pathname.includes("/video/");
    if (platform === "instagram")
      return location.pathname.includes("/reel/") || location.pathname.includes("/p/");
    if (platform === "telegram") return location.pathname.length > 1;
    return false;
  }

  function isShorts() {
    return location.pathname.startsWith("/shorts/");
  }

  function extractTexts() {
    const platform = getPlatform();
    if (!platform) return [];

    const selectors = {
      instagram: [
        "span[dir='auto']",
        "h1",
        "article span",
        "section span",
      ],
      youtube: isShorts()
        ? [
            // Shorts-specific selectors
            "ytd-reel-video-renderer[is-active] #channel-name",
            "ytd-reel-video-renderer[is-active] .ytShortsVideoTitleViewModelShortsVideoTitle",
            "ytd-reel-video-renderer[is-active] .title",
            "ytd-reel-video-renderer[is-active] yt-formatted-string",
            "ytd-reel-video-renderer[is-active] #description",
            // Fallback: any visible shorts text
            "#shorts-container .title",
            "#shorts-container yt-formatted-string",
            "ytd-reel-video-renderer .ytShortsVideoTitleViewModelShortsVideoTitle",
            "ytd-reel-video-renderer yt-formatted-string.title",
            // Generic shorts overlay text
            "[is-active] .metadata-container yt-formatted-string",
            "[is-active] #text-container",
            "ytd-engagement-panel-section-list-renderer yt-formatted-string",
          ]
        : [
            // Regular video selectors
            "#title h1",
            "#video-title",
            "#description-inline-expander",
            "ytd-text-inline-expander",
            "#content-text",
          ],
      tiktok: [
        "[data-e2e='browse-video-desc']",
        "[data-e2e='video-desc']",
        ".tiktok-j2a19r-SpanText",
        "[data-e2e='comment-level-1'] span",
      ],
      telegram: [
        ".tgme_widget_message_text",
        ".tgme_widget_message_author",
        ".js-message_text",
        ".message",
        ".text-content",
        "[dir='auto']",
        "div.tgme_widget_message_bubble",
      ],
    };

    const results = [];
    const seen = new Set();
    const sels = selectors[platform] || [];

    for (const sel of sels) {
      try {
        document.querySelectorAll(sel).forEach((el) => {
          const t = (el.innerText || "").trim();
          if (t.length >= MIN_TEXT_LENGTH && !seen.has(t)) {
            seen.add(t);
            results.push({ text: t, el });
          }
        });
      } catch (e) {
        // invalid selector, skip
      }
    }

    console.log(`[AIMW] Found ${results.length} text blocks on ${platform}${isShorts() ? " (Shorts)" : ""}`);
    return results;
  }

  function currentShortsUrl() {
    // YouTube Shorts swipe between videos without page navigation.
    // The URL updates but no page load fires. Detect the active reel's
    // video ID from either the URL or the active renderer element.
    if (!isShorts()) return location.href;

    // The URL is the most reliable source during scroll
    return location.href;
  }

  function pageContextText() {
    const title = (document.title || "").trim();
    const metaDescription =
      document.querySelector("meta[name='description']")?.getAttribute("content") ||
      document.querySelector("meta[property='og:description']")?.getAttribute("content") ||
      "";
    const visible = extractTexts()
      .slice(0, 8)
      .map((item) => item.text)
      .join("\n");

    return [title, metaDescription, visible, location.href]
      .filter(Boolean)
      .join("\n")
      .slice(0, 5000);
  }

  function hashText(text) {
    let h = 0;
    for (let i = 0; i < text.length; i++) {
      h = ((h << 5) - h + text.charCodeAt(i)) | 0;
    }
    return String(h);
  }

  function showToast(level, score, summary) {
    // Remove any existing toast
    document.querySelectorAll(".aimw-toast").forEach((t) => t.remove());

    let toastClass, icon, title;
    if (level === "HIGH" || level === "CRITICAL") {
      toastClass = "aimw-toast-scam";
      icon = "🚨";
      title = "SCAM DETECTED";
    } else if (level === "MEDIUM") {
      toastClass = "aimw-toast-suspicious";
      icon = "⚠️";
      title = "SUSPICIOUS";
    } else if (level === "PENDING" || level === "UNKNOWN") {
      toastClass = "aimw-toast-pending";
      icon = "🔄";
      title = "ANALYZING...";
    } else {
      toastClass = "aimw-toast-safe";
      icon = "✅";
      title = "SAFE";
    }

    const pct = Math.round((score || 0) * 100);
    const cleanSummary = summary
      ? summary.replace(/\*\*/g, "").replace(/[#_~`]/g, "").substring(0, 120)
      : "";
    const detail = cleanSummary
      ? cleanSummary
      : level === "LOW" || level === "CLEAN"
        ? "No scam signals detected"
        : `Risk score: ${pct}%`;

    const toast = document.createElement("div");
    toast.className = `aimw-toast ${toastClass}`;
    toast.innerHTML = `
      <div class="aimw-toast-icon">${icon}</div>
      <div class="aimw-toast-body">
        <div class="aimw-toast-title">${title}<span class="aimw-toast-badge">${level} ${pct}%</span></div>
        <div class="aimw-toast-detail">${detail}</div>
      </div>
      <button class="aimw-toast-close">&times;</button>
    `;

    const closeBtn = toast.querySelector(".aimw-toast-close");
    closeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      toast.classList.add("aimw-toast-out");
      setTimeout(() => toast.remove(), 350);
    });

    document.body.appendChild(toast);

    // Auto-dismiss after 6s (scam stays 10s)
    const duration = (level === "HIGH" || level === "CRITICAL") ? 10000 : 6000;
    setTimeout(() => {
      if (toast.parentElement) {
        toast.classList.add("aimw-toast-out");
        setTimeout(() => toast.remove(), 350);
      }
    }, duration);
  }

  function addOverlay(el, type, label) {
    if (!el || !el.parentElement) return;
    const existing = el.parentElement.querySelector(`.aimw-${type}`);
    if (existing) return;

    const node = document.createElement("div");
    node.className = `aimw-${type}`;

    if (type === "warning") {
      node.innerHTML = `
        <div class="aimw-warning-inner">
          <span class="aimw-icon">&#9888;</span>
          <span class="aimw-label">${label}</span>
          <button class="aimw-dismiss" title="Dismiss">&times;</button>
        </div>`;
      const btn = node.querySelector(".aimw-dismiss");
      if (btn) btn.addEventListener("click", (e) => { e.stopPropagation(); node.remove(); });
    } else {
      node.textContent = label;
    }

    try {
      el.parentElement.style.position = "relative";
      el.parentElement.insertBefore(node, el);
    } catch (e) {
      console.warn("[AIMW] overlay insert failed:", e.message);
    }
  }

  async function analyzeText(text, el, url = null) {
    const hash = hashText(`${url || ""}\n${text}`);
    if (scannedHashes.has(hash)) return;
    scannedHashes.add(hash);
    scanCount++;

    const myToken = currentToken;
    addOverlay(el, "scanning", "Scanning...");

    const removeScanning = () => {
      if (el && el.parentElement) {
        const ind = el.parentElement.querySelector(".aimw-scanning");
        if (ind) ind.remove();
      }
      // Also clean up any orphan scanning indicators from prior failed scans
      document.querySelectorAll(".aimw-scanning").forEach((n) => {
        if (n.textContent && n.textContent.trim() === "Scanning...") n.remove();
      });
    };

    try {
      const result = await chrome.runtime.sendMessage({
        type: "CHECK_SCAM",
        text: text.substring(0, 5000),
        url,
      });

      // Discard stale verdicts from previous pages
      if (myToken !== currentToken) {
        console.log("[AIMW] Discarding stale verdict — user navigated");
        removeScanning();
        return;
      }

      removeScanning();

      if (!result || result.error) {
        const errMsg = result ? result.error : "no response from API";
        console.warn("[AIMW] Error:", errMsg);
        // Always show feedback so user knows scan completed, even on error
        showToast("UNKNOWN", 0, `Analysis unavailable — ${errMsg}`);
        addOverlay(el, "safe", "Could not analyze — see Dashboard");
        return;
      }

      console.log("[AIMW] Verdict:", result.level, result.score);

      showToast(result.level, result.score, result.summary);

      if (result.level === "HIGH" || result.level === "CRITICAL") {
        scamCount++;
        addOverlay(el, "warning",
          `<strong>SCAM ALERT</strong> &mdash; ${result.level} risk (${Math.round((result.score || 0) * 100)}%)`
        );
      } else if (result.level === "MEDIUM") {
        addOverlay(el, "warning",
          `<strong>SUSPICIOUS</strong> &mdash; Medium risk (${Math.round((result.score || 0) * 100)}%)`
        );
      } else if (result.level === "PENDING" || result.level === "UNKNOWN") {
        addOverlay(el, "safe", "Analysis in progress — check Dashboard");
      } else {
        addOverlay(el, "safe", "Checked ✓");
      }
    } catch (e) {
      console.warn("[AIMW] sendMessage failed:", e.message);
      removeScanning();
      if (myToken === currentToken) {
        showToast("UNKNOWN", 0, "Analysis failed — check API connection");
        addOverlay(el, "safe", "Connection error — see Dashboard");
      }
    }

    try {
      chrome.runtime.sendMessage({ type: "UPDATE_BADGE", scanCount, scamCount });
    } catch (e) { /* ignore */ }
  }

  function scan() {
    // Detect URL changes (Shorts swiping, SPA navigation)
    if (location.href !== lastUrl) {
      console.log("[AIMW] URL changed:", lastUrl, "→", location.href);
      lastUrl = location.href;
      currentToken++;
      clearAllOverlays();
    }

    if (isVideoPage()) {
      const url = currentShortsUrl();
      const text = pageContextText();
      const hash = hashText(`${url}\n${text}`);
      if (text.length >= MIN_TEXT_LENGTH && !scannedHashes.has(hash)) {
        let anchor;
        if (isShorts()) {
          anchor =
            document.querySelector("ytd-reel-video-renderer[is-active]") ||
            document.querySelector("#shorts-container") ||
            document.querySelector("ytd-shorts") ||
            document.querySelector("main") ||
            document.body;
        } else {
          anchor =
            document.querySelector("#above-the-fold") ||
            document.querySelector("main") ||
            document.body;
        }
        analyzeText(text, anchor, url);
      }
      return;
    }

    // Non-video pages (feed, search, etc.): scan individual text blocks
    const items = extractTexts();
    for (const { text, el } of items) {
      const hash = hashText(text);
      if (!scannedHashes.has(hash)) {
        analyzeText(text, el);
      }
    }
  }

  // Start scanning
  const platform = getPlatform();
  if (platform) {
    console.log("[AI MediaWatch] Active on", platform, "- scanning in 1s");
    setTimeout(scan, 1000);
    setInterval(scan, SCAN_INTERVAL_MS);

    // Detect YouTube SPA navigation (Shorts swiping, clicking between videos)
    if (platform === "youtube") {
      // YouTube fires yt-navigate-finish on SPA page transitions
      document.addEventListener("yt-navigate-finish", () => {
        console.log("[AIMW] YouTube SPA navigation detected");
        currentToken++;
        clearAllOverlays();
        setTimeout(scan, 500);
      });

      // For Shorts: watch for URL changes caused by swiping (no event fires)
      let shortsCheckUrl = location.href;
      setInterval(() => {
        if (location.href !== shortsCheckUrl) {
          shortsCheckUrl = location.href;
          console.log("[AIMW] Shorts swipe detected:", shortsCheckUrl);
          currentToken++;
          clearAllOverlays();
          setTimeout(scan, 300);
        }
      }, 800);
    }

    // Scroll-triggered scan (new content loaded)
    window.addEventListener("scroll", () => {
      clearTimeout(window._aimwScrollTimer);
      window._aimwScrollTimer = setTimeout(scan, 600);
    }, { passive: true });
  } else {
    console.log("[AI MediaWatch] Not a supported platform:", location.hostname);
  }
})();
