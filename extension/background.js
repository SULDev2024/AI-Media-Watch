async function analyzeVideo(videoSrc, caption, platform) {
  try {
    const formData = new FormData();
    formData.append('video_url', videoSrc);
    formData.append('caption', caption);
    formData.append('platform', platform);

    const apiResp = await fetch('http://localhost:8000/analyze-url', {
      method: 'POST',
      body: formData
    });

    const data = await apiResp.json();
    return { success: true, data };
  } catch (err) {
    return { success: false, error: err.message };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'ANALYZE_VIDEO') {
    analyzeVideo(message.videoSrc, message.caption, message.platform).then(sendResponse);
    return true;
  }
});
