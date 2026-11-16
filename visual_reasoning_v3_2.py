"""V3.2 reuses all V3.1 input gates; adds one narrow output review hint.

No evidence repair, score changes, context inference or fraud classification.
Lexical checks are review hints, not a semantic safety guarantee.
"""
import re
from visual_reasoning_v3_1 import validate_visual_report, render_validated_report
from visual_reasoning_v3_1 import consistency_flags as prior_flags

PIPELINE_VERSION = 'local-agent-visual-v3.2-claim-truth-context'


def consistency_flags(quotes, interpretation, context):
    flags = prior_flags(quotes, interpretation, context)
    # Require an explicit causal safety assertion, not merely uncertainty about
    # truth. A warning quoting these words is not itself a promotional claim.
    if quotes and context == 'promotion' and re.search(
        r'\b(?:safe|harmless|low[- ]risk) (?:because|since) '
        r'(?:the (?:claims?|profits?|accuracy) (?:is|are) unverified|'
        r'there is no (?:proof|verification))\b', interpretation, re.I):
        flags.append({'code':'possible_verification_safety_confusion',
                      'message':'Explicit safety conclusion from missing verification alone; review claim presence, truth and context separately. Score unchanged.'})
    return flags
