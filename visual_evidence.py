"""Documented visual-v2 text budget. Pure standard library; no model calls."""

VISUAL_PIPELINE_VERSION = "local-agent-visual-v2"
VISUAL_MAX_UTF8_BYTES = 3072
# Conservative byte-based bound for this byte-level tokenizer, with space for
# the unchanged 128-token output and chat/template overhead. Not token counting.
PROMPT_MAX_UTF8_BYTES = 4096 - 128 - 256
OMISSION = "\n[Visual report excerpt omitted by byte budget]\n"


def _prefix(text, limit):
    return text.encode('utf-8')[:max(0, limit)].decode('utf-8', errors='ignore')


def _suffix(text, limit):
    return text.encode('utf-8')[-limit:].decode('utf-8', errors='ignore') if limit > 0 else ''


def prepare_visual_evidence(report, metadata=None, available_bytes=VISUAL_MAX_UTF8_BYTES):
    """Keep full reports when possible; flag bounded head+tail excerpts otherwise.

    The prompt asks for financial claims first. On overflow preserve the head
    and tail rather than silently dropping every later claim. No interpretation,
    invented claims or risk re-scoring happens here. Middle evidence can still
    be omitted and is explicitly recorded as such. Caller retains the full report.
    """
    metadata = metadata or {}
    reason = metadata.get('done_reason')
    completion = ('unavailable' if str(reason).startswith('skipped_')
                  else 'incomplete' if reason == 'length' or metadata.get('done') is False
                  else 'complete' if reason == 'stop' else 'unknown')
    state = dict(pipeline_version=VISUAL_PIPELINE_VERSION,
                 generation_status=completion, done_reason=reason,
                 original_utf8_bytes=len(report.encode('utf-8')),
                 evidence_truncated=False, report_budget_bytes=0,
                 selection_policy='full-otherwise-head-and-tail')
    if not report:
        return '', state  # Preserve the original Speech Only prompt exactly.
    budget = min(VISUAL_MAX_UTF8_BYTES, available_bytes)
    trailer = f"\n[Visual report generation: {completion}; evidence_truncated: false]"
    room = budget - len(trailer.encode('utf-8'))
    if len(report.encode('utf-8')) <= room:
        body = report
        retained = len(report.encode('utf-8'))
    else:
        trailer = f"\n[Visual report generation: {completion}; evidence_truncated: true]"
        room = budget - len(trailer.encode('utf-8')) - len(OMISSION.encode('utf-8'))
        if room < 128:
            raise ValueError('Insufficient visual evidence budget; no auditor prediction requested')
        head = int(room * 0.7)
        prefix, suffix = _prefix(report, head), _suffix(report, room-head)
        body = prefix + OMISSION + suffix
        retained = len(prefix.encode('utf-8')) + len(suffix.encode('utf-8'))
        state['evidence_truncated'] = True
    rendered = body + trailer
    if len(rendered.encode('utf-8')) > budget:
        raise ValueError('Insufficient evidence budget')
    state.update(report_budget_bytes=budget, passed_utf8_bytes=len(rendered.encode('utf-8')),
                 retained_report_utf8_bytes=retained,
                 omitted_report_utf8_bytes=state['original_utf8_bytes']-retained)
    return rendered, state
