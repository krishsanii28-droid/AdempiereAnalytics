"""Match a question to one of the approved intents.

Primary: sentence-transformers/all-MiniLM-L6-v2. Every example phrasing is embedded once; a
question is matched to the intent of its nearest example by cosine similarity. MiniLM is an
embedding model: it produces a vector, never text or SQL.

Fallback: if the packages or the model are unavailable, a keyword matcher is used and the answer
says so.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from ..config import ROOT, get_settings
from .intents import INTENTS
from .params import normalise

log = logging.getLogger("insightai.assistant")
MODEL_DIR = ROOT / "models"


@dataclass(frozen=True)
class Match:
    intent_id: str | None          # None when nothing is close enough
    score: float
    matcher: str                   # "minilm" or "keyword"
    ranked: list[tuple[str, float]]  # best score per intent, highest first
    fallback_reason: str | None = None


class _Embedder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = None
        self._examples = None        # tensor [n_examples, dim], unit length
        self._owners: list[str] = []
        self.failure: str | None = None
        self._tried = False

    def _load(self, model_dir: Path) -> None:
        self._tried = True
        os.environ.setdefault("HF_HOME", str(model_dir))
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            self.failure = f"sentence-transformers is not installed ({exc.name})"
            return
        name = get_settings().assistant_model
        last_error = "unknown error"
        for local_only in (True, False):     # local cache first, so no network is needed once downloaded
            try:
                model = SentenceTransformer(name, device="cpu", cache_folder=str(model_dir / "hub"), local_files_only=local_only)
                texts, owners = [], []
                for intent in INTENTS:
                    for example in intent.examples:
                        texts.append(normalise(example))
                        owners.append(intent.id)
                self._examples = model.encode(texts, convert_to_tensor=True, normalize_embeddings=True, show_progress_bar=False)
                self._model, self._owners = model, owners
                return
            except Exception as exc:  # noqa: BLE001 - any failure means "use keywords"
                last_error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
        self.failure = f"model {name} could not be loaded ({last_error})"
        log.warning("assistant falls back to keyword matching: %s", self.failure)

    def scores(self, text: str) -> dict[str, float] | None:
        with self._lock:
            if not self._tried:
                self._load(MODEL_DIR)
            if self._model is None:
                return None
            query = self._model.encode([normalise(text)], convert_to_tensor=True, normalize_embeddings=True, show_progress_bar=False)
            similarities = (self._examples @ query[0]).tolist()
        best: dict[str, float] = {}
        for owner, similarity in zip(self._owners, similarities):
            best[owner] = max(best.get(owner, -1.0), float(similarity))
        return best


_embedder = _Embedder()


def keyword_scores(text: str) -> dict[str, float]:
    """1.0 or more when one of an intent's keyword sets is wholly present; larger sets score higher
    so a more specific intent wins over a general one. Below 1.0 means only part of a set matched."""
    words = set(normalise(text).split())
    words |= {w[:-1] for w in words if w.endswith("s") and len(w) > 3}     # crude plural folding
    scores = {}
    for intent in INTENTS:
        best = 0.0
        for group in intent.keywords:
            hit = len(group & words) / len(group)
            best = max(best, 1.0 + 0.1 * len(group) if hit == 1.0 else hit * 0.9)
        scores[intent.id] = best
    return scores


def match(text: str, *, eligible: set[str] | None = None, force_keywords: bool = False) -> Match:
    """`eligible` limits the choice to intents whose required names were actually found in the question."""
    settings = get_settings()
    scores = None if force_keywords else _embedder.scores(text)
    if scores is not None:
        matcher, threshold, reason = "minilm", settings.assistant_threshold, None
    else:
        scores, matcher, threshold = keyword_scores(text), "keyword", 1.0
        reason = "keyword matching forced" if force_keywords else _embedder.failure
    if eligible is not None:
        scores = {k: v for k, v in scores.items() if k in eligible}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_id, top_score = ranked[0]
    declined = top_score < threshold or top_id == "out_of_scope"
    return Match(None if declined else top_id, top_score, matcher, ranked, reason)


def warm_up() -> None:
    """Load the model in the background at start-up so the first question is not slow."""
    threading.Thread(target=lambda: _embedder.scores("warm up"), name="insightai-assistant-warmup", daemon=True).start()
