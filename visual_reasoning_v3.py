"""V3 structural checks and cautious consistency flags, never scam scoring.

All quotes remain model-reported, NOT pixel-verified facts. Narrow lexical checks
only flag possible logical conflicts; they do not infer promotion or a risk score.
Malformed/incomplete/invalid-frame reports are retained but blocked for review.
"""
import hashlib
import json
import re

PIPELINE_VERSION = 'local-agent-visual-v3'
CONTEXTS = {'promotion', 'warning', 'reporting', 'unclear'}
MAX_RAW_BYTES = 32768


def _unique_object(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key; report must not silently overwrite claims')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Non-JSON numeric constant: '+value)


def consistency_flags(quotes, interpretation, context):
    """High-precision hints, not semantic proof or a keyword fraud detector.

    Presence of a displayed claim is distinct from promoting or verifying it.
    'Profits are not guaranteed' or 'not verified' must not be treated as denying
    that a quote appears. Warning/reporting context can quote a scam's claims.
    """
    has_guarantee = any(re.search(r'\bguaranteed?\s+(?:profits?|returns?|earnings?)\b', q, re.I)
                        for q in quotes)
    has_accuracy = any(re.search(r'100\s*%\s*(?:accurate|accuracy)', q, re.I) for q in quotes)
    if not (has_guarantee or has_accuracy):
        return []
    # Explicit absence of visible text conflicts even in a warning video.
    absence = re.search(
        r'\bno (?:visible |financial |profit )?(?:claims?|guarantees?)'
        r'(?: or guarantees?)?(?: is| are| was| were)? '
        r'(?:visible|displayed|shown|present|appears?|observed)\b'
        r'|\b(?:does not|doesn\x27t) (?:display|show|contain) '
        r'(?:any |a |specific )?(?:financial |profit )?(?:claims?|guarantees?)\b',
        interpretation, re.I)
    flags = []
    if absence:
        flags.append({'code':'possible_quote_presence_conflict',
                      'message':'A displayed claim is quoted, but interpretation denies visible claims/guarantees. Reconcile scope; do not assume the claim is true.'})
    # Broader denials are ambiguous (claim vs genuine guarantee). Only flag an
    # explicitly promotional interpretation; NEVER turn a warning into promotion.
    if context == 'promotion' and re.search(
            r'\b(?:does not|doesn\x27t) (?:provide|make|offer) '
            r'(?:any |a |specific )?(?:financial )?(?:claims? or )?guarantees?\b',
            interpretation, re.I):
        flags.append({'code':'possible_promotional_claim_conflict',
                      'message':'Interpretation labels promotion and denies guarantees despite a quoted claim. It may confuse a displayed promise with verified truth; unresolved.'})
    return flags


def validate_visual_report(raw, supplied_frame_count, metadata=None):
    """Keep original text. Validate schema/references; do not repair model text."""
    metadata = metadata or {}
    reason = metadata.get('done_reason')
    generation = ('incomplete' if reason == 'length' or metadata.get('done') is False
                  else 'complete' if reason == 'stop' else 'unknown')
    issues = []
    def flag(code, message, blocking=False):
        issues.append({'code':code, 'message':message, 'blocking':blocking})
    known_count = (isinstance(supplied_frame_count, int) and not isinstance(supplied_frame_count, bool)
                   and 1 <= supplied_frame_count <= 3)
    if not known_count:
        flag('frame_count_unknown', 'A trusted count of 1–3 supplied images is required.', True)
    if generation != 'complete':
        flag('generation_'+generation, 'Generation is not confirmed complete; retain raw output for review.', True)
    parsed = None
    if not isinstance(raw, str):
        raise TypeError('Raw visual report must be preserved as a string')
    if len(raw.encode('utf-8')) > MAX_RAW_BYTES:
        flag('oversized_report', 'Report exceeds validator resource ceiling; no truncation or repair.', True)
    else:
        try:
            parsed = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
        except (ValueError, RecursionError):
            flag('malformed_report', 'Expected one complete JSON object; no fence stripping, completion or quote reconstruction.', True)
    schema_valid = False
    quotes, frame_checks = [], []
    context = 'unclear'
    if parsed is None and not any(i['code'] in ('malformed_report','oversized_report') for i in issues):
        flag('malformed_schema', 'A JSON null value is not a structured visual report.', True)
    if parsed is not None:
        schema_valid = (isinstance(parsed, dict)
                        and set(parsed) == {'OBSERVED','INTERPRETATION','UNCERTAINTY'}
                        and isinstance(parsed.get('OBSERVED'), list)
                        and isinstance(parsed.get('INTERPRETATION'), dict)
                        and set(parsed.get('INTERPRETATION', {})) == {'context','summary'}
                        and isinstance(parsed['INTERPRETATION'].get('context'),str)
                        and parsed['INTERPRETATION']['context'] in CONTEXTS
                        and isinstance(parsed['INTERPRETATION'].get('summary'), str)
                        and isinstance(parsed.get('UNCERTAINTY'), list)
                        and all(isinstance(s,str) for s in parsed['UNCERTAINTY']))
        if schema_valid:
            context = parsed['INTERPRETATION']['context']
            seen = []
            for position, observation in enumerate(parsed['OBSERVED']):
                shape_ok = (isinstance(observation,dict) and set(observation)=={'frame','text','objects'}
                            and isinstance(observation.get('text'),list) and isinstance(observation.get('objects'),list)
                            and all(isinstance(s,str) for s in observation['text']+observation['objects']))
                if not shape_ok:
                    schema_valid = False
                    continue
                frame = observation['frame']
                valid = (known_count and isinstance(frame,int) and not isinstance(frame,bool)
                         and 1 <= frame <= supplied_frame_count)
                frame_checks.append({'observation_index':position,'frame':frame,'reference_valid':valid})
                if not valid:
                    flag('invalid_frame_reference', f'OBSERVED entry {position} references {frame!r}; supplied image count is {supplied_frame_count!r}. No remapping.', True)
                elif frame in seen:
                    flag('duplicate_frame_entry', f'Frame {frame} occurs more than once; no automatic merge.', True)
                else:
                    seen.append(frame)
                quotes.extend(observation['text'])
            if known_count and set(seen) != set(range(1,supplied_frame_count+1)):
                flag('missing_frame_entry', 'Require one OBSERVED entry for each supplied image, including blank/unreadable images.', True)
            for item in consistency_flags(quotes, parsed['INTERPRETATION']['summary'], context):
                flag(item['code'], item['message'])
            # Free-form interpretation may also cite an unsupported image number.
            for match in re.finditer(r'\bframe\s*#?\s*(\d+)\b', parsed['INTERPRETATION']['summary'], re.I):
                if known_count and not 1 <= int(match.group(1)) <= supplied_frame_count:
                    flag('unverified_interpretation_frame', 'Interpretation refers to a nonexistent frame; retain raw report for review.', True)
        if not schema_valid:
            flag('malformed_schema', 'Require OBSERVED frame/text/objects, INTERPRETATION context/summary and UNCERTAINTY exactly.', True)
    # Diagnostic for saved legacy/free-text regressions. A heading is a frame
    # reference; a literal quoted 'frame 4' inside educational text is not scanned.
    if not schema_valid:
        for match in re.finditer(r'^\s*(?:#{1,6}\s*)?(?:\*\*)?Frame\s+(\d+)\s*:', raw, re.I|re.M):
            if known_count and not 1 <= int(match.group(1)) <= supplied_frame_count:
                flag('invalid_frame_heading', 'Legacy report heading references a nonexistent supplied frame.', True)
        if 'Guaranteed Profits' in raw and re.search(r'does not provide specific financial claims or guarantees of earnings',raw,re.I):
            flag('possible_unstructured_conflict', 'Raw report contains both a guarantee quote and a broad denial. Scope is unvalidated; no automatic resolution.')
    return {'pipeline_version':PIPELINE_VERSION, 'raw_report':raw,
            'raw_sha256':hashlib.sha256(raw.encode('utf-8')).hexdigest(),
            'generation_status':generation,'done_reason':reason,'supplied_frame_count':supplied_frame_count,
            'schema_valid':schema_valid,'parsed_report':parsed,'frame_checks':frame_checks,
            'context':context,'issues':issues,
            'requires_uncertainty':bool(issues) or context=='unclear' or (schema_valid and bool(parsed['UNCERTAINTY'])),
            'can_forward':schema_valid and not any(i['blocking'] for i in issues)}


def render_validated_report(validation):
    """Separate original model sections from code-generated flags, without edits."""
    if not validation['can_forward']:
        raise ValueError('Visual report needs review; do not request an auditor prediction')
    envelope = {'MODEL_REPORT':validation['parsed_report'],
                'VALIDATOR':{'generation_status':validation['generation_status'],
                             'supplied_frame_count':validation['supplied_frame_count'],
                             'flags':validation['issues'],
                             'uncertainty_required':validation['requires_uncertainty']}}
    return json.dumps(envelope,ensure_ascii=False,separators=(',',':'))
