import sys
import os
import json
import tempfile
from pathlib import Path

import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vision_engine import process_video_optimized, preload as preload_vision
from audio_engine import preload as preload_audio
from agents import analyze, preload as preload_agents
from cache import compute_hash, get_cached, set_cached

st.set_page_config(
    page_title="Scam Video Detector",
    page_icon="🕵️",
    layout="wide",
)

if "models_loaded" not in st.session_state:
    with st.spinner("Preloading AI models (Whisper, EasyOCR, Ollama)..."):
        preload_vision()
        preload_audio()
        preload_agents()
    st.session_state.models_loaded = True

st.title("🕵️ Scam Video Detector")
st.markdown("Upload a video or paste a URL to analyze it for scam indicators using **3 AI models**.")

tab1, tab2 = st.tabs(["📤 Upload Video", "🔗 Video URL"])

video_path = None

with tab1:
    uploaded = st.file_uploader("Choose a video file", type=["mp4", "avi", "mov", "mkv", "webm"])
    if uploaded is not None:
        suffix = Path(uploaded.name).suffix or ".mp4"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.write(uploaded.read())
        video_path = tmp.name
        st.success(f"Loaded: {uploaded.name} ({(len(uploaded.getvalue()) / 1024 / 1024):.1f} MB)")

with tab2:
    url = st.text_input("Enter video URL")
    if url and st.button("Fetch from URL"):
        import httpx
        with st.spinner("Downloading video..."):
            resp = httpx.get(url, timeout=60, follow_redirects=True)
            resp.raise_for_status()
            tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp.write(resp.content)
            video_path = tmp.name
        st.success(f"Downloaded ({len(resp.content) / 1024 / 1024:.1f} MB)")

if video_path is None:
    st.info("Upload or provide a URL to get started.")
    st.stop()

video_hash = compute_hash(video_path)
cached = get_cached(video_hash)
if cached:
    st.success("Returning cached result for this video.")
    result = cached
    result_opt = cached.get("_data", {"ocr": {"ocr_results": []}})
else:
    with st.status("Running optimized pipeline...", expanded=True) as status:
        st.write("### Phase 1: Parallel extraction (i7-14700KF)")
        st.write("  Stream A: Audio extraction (ffmpeg) | Stream B: Frame sampling (360p, 3s interval)")

        result_opt = process_video_optimized(video_path, max_height=360, interval=3.0)

        frames = result_opt["frames"]
        transcript_data = result_opt["transcript"]
        ocr_data = result_opt["ocr"]
        st.write(f"  Frames: {len(frames)} at 480p | Audio: {transcript_data.get('duration', 0):.1f}s")

        st.write("### Phase 2: GPU inference (RTX 5080)")
        st.write("  Whisper distil-large-v3 + EasyOCR batch")
        transcript = transcript_data["text"]
        st.write(f"  Transcript: {(transcript[:80] + '...') if transcript else '(none)'}")
        st.write(f"  OCR: {len(ocr_data['ocr_results'])} frames with text")

        st.write("### Phase 3: 3-model analysis")
        st.write("  mistral + qwen2.5vl (parallel, num_ctx=4096) -> llama3 (auditor)")
        result = analyze("", transcript, frames)
        risk = result["risk_score"]
        result["transcript"] = transcript
        result["_data"] = {"ocr": ocr_data}
        status.update(label="Complete", state="complete")

    set_cached(video_hash, result)

risk = result["risk_score"]
col1, col2, col3 = st.columns([1, 2, 1])
with col2:
    if risk >= 70:
        st.error(f"### Risk Score: {risk}/100 - HIGH RISK")
    elif risk >= 40:
        st.warning(f"### Risk Score: {risk}/100 - MEDIUM RISK")
    else:
        st.success(f"### Risk Score: {risk}/100 - LOW RISK")

tab_a, tab_b, tab_c, tab_d = st.tabs(["Transcript", "OCR Text", "Speech Analysis", "Final Verdict"])

with tab_a:
    t = result.get("transcript", "")
    if t.strip():
        st.text_area("Full Transcript", t, height=200)
    else:
        st.info("No speech detected.")

with tab_b:
    ocr_data = result_opt.get("ocr", {"ocr_results": []})
    if ocr_data["ocr_results"]:
        for entry in ocr_data["ocr_results"]:
            with st.expander(f"Time: {entry['time']}s - {len(entry['texts'])} text(s)"):
                for t in entry["texts"]:
                    st.write(f"- {t}")
    else:
        st.info("No on-screen text detected.")

with tab_c:
    st.markdown(result.get("speech_report", "N/A"))

with tab_d:
    st.subheader("Flags")
    if result.get("flags"):
        for flag in result["flags"]:
            st.warning(flag)
    else:
        st.success("No flags raised.")
    st.subheader("Reasoning")
    st.markdown(result.get("reasoning", "N/A"))
    st.subheader("Raw JSON")
    st.json(result)

try:
    if os.path.exists(video_path):
        os.unlink(video_path)
except:
    pass
