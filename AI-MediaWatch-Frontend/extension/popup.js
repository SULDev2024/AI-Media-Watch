document.addEventListener("DOMContentLoaded", async () => {
  const statusDot = document.getElementById("statusDot");
  const statusText = document.getElementById("statusText");
  const checkBtn = document.getElementById("checkBtn");
  const checkText = document.getElementById("checkText");
  const resultDiv = document.getElementById("result");
  const scannedEl = document.getElementById("scanned");
  const detectedEl = document.getElementById("detected");

  // Check API connection
  try {
    const status = await chrome.runtime.sendMessage({ type: "GET_STATUS" });
    if (status.connected) {
      statusDot.className = "dot green";
      statusText.textContent = status.version
        ? `Connected — v${status.version}`
        : "Connected to AI MediaWatch";
    } else {
      statusDot.className = "dot red";
      statusText.textContent = "API offline — run start_demo.ps1";
    }
  } catch {
    statusDot.className = "dot red";
    statusText.textContent = "Extension error";
  }

  // Load stats from storage
  chrome.storage.local.get(["scanCount", "scamCount"], (data) => {
    scannedEl.textContent = data.scanCount || 0;
    detectedEl.textContent = data.scamCount || 0;
  });

  // Quick check button
  checkBtn.addEventListener("click", async () => {
    const text = checkText.value.trim();
    if (!text) return;

    checkBtn.disabled = true;
    checkBtn.textContent = "Analyzing...";
    resultDiv.className = "result";
    resultDiv.removeAttribute("style");

    try {
      const result = await chrome.runtime.sendMessage({
        type: "CHECK_SCAM",
        text,
        url: "extension:quick-check",
      });

      if (result.error) {
        resultDiv.className = "result error";
        resultDiv.textContent = result.error;
      } else if (
        result.level === "HIGH" ||
        result.level === "CRITICAL"
      ) {
        resultDiv.className = "result high";
        resultDiv.innerHTML =
          `<strong>SCAM DETECTED - ${result.level}</strong><br>` +
          `Risk: ${Math.round(result.score * 100)}% | ` +
          `Confidence: ${Math.round(result.confidence * 100)}%`;
      } else if (result.level === "MEDIUM") {
        resultDiv.className = "result medium";
        resultDiv.innerHTML =
          `<strong>SUSPICIOUS - ${result.level}</strong><br>` +
          `Risk: ${Math.round(result.score * 100)}% | ` +
          `Confidence: ${Math.round(result.confidence * 100)}%`;
      } else if (result.level === "PENDING" || result.level === "UNKNOWN") {
        resultDiv.className = "result medium";
        resultDiv.innerHTML =
          `<strong>Analysis in progress</strong><br>` +
          `Check the Dashboard for full video results.`;
      } else {
        resultDiv.className = "result low";
        resultDiv.textContent = "No scam detected — content appears safe.";
      }
    } catch (e) {
      resultDiv.className = "result error";
      resultDiv.textContent = "Error: " + e.message;
    }

    checkBtn.disabled = false;
    checkBtn.textContent = "Analyze";
  });
});
