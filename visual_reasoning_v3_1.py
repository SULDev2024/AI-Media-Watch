"""V3.1: two recorded compatibility normalizations, then unchanged V3 checks.

No evidence repair: only unwrap a sole JSON code block and default an absent
objects list to 'not supplied'. Never default observed text or a frame ID.
"""
import copy
import hashlib
import json
import re
import visual_reasoning_v3 as strict

PIPELINE_VERSION = 'local-agent-visual-v3.1-format-compat'
consistency_flags = strict.consistency_flags

# The whole response must be this one block. No prose/extra blocks/brace search.
_FENCE = re.compile(r'\A\s*```(?P<language>json)?[ \t]*\r?\n'
                    r'(?P<body>.*?)\r?\n```[ \t]*\s*\Z', re.I|re.S)


def validate_visual_report(raw, supplied_frame_count, metadata=None):
    if not isinstance(raw,str):
        return strict.validate_visual_report(raw,supplied_frame_count,metadata)
    normalizations = []
    parse_text = raw
    source_parsed = None
    # Preserve the original resource bound before unwrapping/compact serialization.
    if len(raw.encode('utf-8')) <= strict.MAX_RAW_BYTES:
        fence = _FENCE.fullmatch(raw)
        if fence:
            parse_text = fence.group('body')
            normalizations.append({'op':'unwrap_json_fence','path':'$',
                                   'language':fence.group('language') or 'unlabelled',
                                   'body_character_span':list(fence.span('body'))})
        try:
            parsed = json.loads(parse_text,object_pairs_hook=strict._unique_object,
                                parse_constant=strict._invalid_constant)
            source_parsed = copy.deepcopy(parsed)
        except (ValueError,RecursionError):
            parsed = None
        changed = False
        if isinstance(parsed,dict) and isinstance(parsed.get('OBSERVED'),list):
            for index,entry in enumerate(parsed['OBSERVED']):
                # Missing only: null, wrong types, missing text/frame or extra
                # evidence fields are NOT repaired. Reference validity is still
                # checked by strict V3 below, including IDs beyond input count.
                if (isinstance(entry,dict) and set(entry)=={'frame','text'}
                        and isinstance(entry['frame'],int) and not isinstance(entry['frame'],bool)
                        and isinstance(entry['text'],list)
                        and all(isinstance(s,str) for s in entry['text'])):
                    entry['objects'] = []
                    changed = True
                    normalizations.append({'op':'default_missing_objects',
                                           'path':f'$.OBSERVED[{index}].objects',
                                           'meaning':'not supplied; not evidence that no objects are visible'})
        if changed:
            # This is a derived serialization; all source string values survive.
            parse_text = json.dumps(parsed,ensure_ascii=False,separators=(',',':'))
    result = strict.validate_visual_report(parse_text,supplied_frame_count,metadata)
    result.update(pipeline_version=PIPELINE_VERSION,raw_report=raw,
                  raw_sha256=hashlib.sha256(raw.encode('utf-8')).hexdigest(),
                  source_parsed_report=source_parsed,normalizations=normalizations,
                  normalized_report=parse_text,
                  normalized_sha256=hashlib.sha256(parse_text.encode('utf-8')).hexdigest())
    if any(n['op']=='default_missing_objects' for n in normalizations):
        result['requires_uncertainty'] = True
    return result


def render_validated_report(validation):
    """Keep the V3 envelope and flags; disclose compatibility changes compactly."""
    envelope = json.loads(strict.render_validated_report(validation))
    if validation.get('normalizations'):
        envelope['VALIDATOR']['normalizations'] = [
            {'op':n['op'],'path':n['path']} for n in validation['normalizations']]
        if any(n['op']=='default_missing_objects' for n in validation['normalizations']):
            envelope['VALIDATOR']['objects_default_meaning'] = 'not supplied, not verified absence'
    return json.dumps(envelope,ensure_ascii=False,separators=(',',':'))
