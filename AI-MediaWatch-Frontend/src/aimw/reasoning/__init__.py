"""Reasoning layer -- two LLM briefs + deterministic referee. Phase 10.

Public surface
--------------
``referee.run(pkg, briefs=None)``  -> RefereeResult
``briefs.prosecutor(pkg)``          -> BriefShape    (async, requires Groq)
``briefs.defense(pkg)``             -> BriefShape    (async, requires Groq)
``stub.ReasoningStub``              -> deterministic offline replacement
``client.GroqClient``               -> token-budgeted HTTP client
``client.TokenBudgetExhausted``     -> raised when daily cap is close
"""
