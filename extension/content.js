function extractPostInfo(element) {
  const video = element.querySelector('video');
  if (!video || !video.src) return null;

  const article = element.closest('article') || element.closest('[data-testid="tweet"]') || element;
  const textEl = article.querySelector('h1, h2, p, [data-testid="tweetText"], span');
  const caption = textEl ? textEl.innerText.slice(0, 500) : '';

  return {
    videoSrc: video.src,
    caption,
    platform: location.hostname.replace('www.', '')
  };
}

function injectBadge(element, result) {
  const existing = element.querySelector('[data-scam-badge]');
  if (existing) existing.remove();

  const badge = document.createElement('div');
  badge.dataset.scamBadge = 'true';
  badge.style.cssText = `
    position: absolute; top: 8px; right: 8px; z-index: 9999;
    padding: 4px 10px; border-radius: 12px; font: bold 12px/1.4 sans-serif;
    color: #fff; cursor: pointer; box-shadow: 0 2px 6px rgba(0,0,0,0.3);
  `;

  const score = result.risk_score ?? 0;
  if (result.verdict === 'SAFE' || score < 20) {
    badge.style.background = '#22c55e';
    badge.textContent = 'Safe';
  } else if (score < 50) {
    badge.style.background = '#eab308';
    badge.textContent = 'Suspicious';
  } else {
    badge.style.background = '#ef4444';
    badge.textContent = 'Scam Alert!';
  }

  badge.onclick = () => alert(
    `Risk Score: ${score}/100\n\nReason: ${result.reasoning || 'N/A'}\n\nFlags: ${(result.flags || []).join(', ') || 'None'}`
  );

  element.style.position = 'relative';
  element.appendChild(badge);
}

async function processPost(element) {
  const info = extractPostInfo(element);
  if (!info) return;

  if (element.querySelector('[data-scam-badge]')) return;

  const badge = document.createElement('div');
  badge.dataset.scamBadge = 'true';
  badge.style.cssText = `
    position: absolute; top: 8px; right: 8px; z-index: 9999;
    padding: 4px 10px; border-radius: 12px; font: bold 12px/1.4 sans-serif;
    color: #fff; background: #6b7280; box-shadow: 0 2px 6px rgba(0,0,0,0.3);
  `;
  badge.textContent = 'Analyzing...';
  element.style.position = 'relative';
  element.appendChild(badge);

  try {
    const resp = await chrome.runtime.sendMessage({
      type: 'ANALYZE_VIDEO',
      videoSrc: info.videoSrc,
      caption: info.caption,
      platform: info.platform
    });

    badge.remove();
    if (resp && resp.success) {
      injectBadge(element, resp.data);
    } else {
      badge.textContent = 'Error';
      badge.style.background = '#6b7280';
    }
  } catch {
    badge.textContent = 'Offline';
    badge.style.background = '#6b7280';
  }
}

const observer = new MutationObserver(() => {
  const posts = document.querySelectorAll(
    'article, [data-testid="tweet"], [data-e2e="recommend-list-item"]'
  );
  posts.forEach(processPost);
});

observer.observe(document.body, { childList: true, subtree: true });
