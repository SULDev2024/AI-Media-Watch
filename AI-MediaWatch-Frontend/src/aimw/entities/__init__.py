"""Entity extraction engine (Phase 7).

Converts raw speech (Transcript) and OCR (OcrResult) artifacts into
structured ExtractedEntities and untyped RawSpan lists. Phase 8 promotes
RawSpan objects to EvidencePiece with full signal tagging.

Public surface:
    extractor.extract() / extractor.extract_async()
    models.RawSpan
    normalize.normalize() / normalize.is_normalized()
    patterns.extract_wallets() / extract_phones() / extract_handles() / …
    fuzzy.load_watchlist() / recover_handles() / recover_wallets()
    spacy_ner.recall_net() / reset_spacy()
    vlm.qwen.get_qwen() / reset_qwen()
    cli.register()
"""
