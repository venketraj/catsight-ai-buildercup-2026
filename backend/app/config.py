"""Runtime configuration — read from the environment, never hardcoded.

`.env.example` states the rule this module exists to keep: **nothing in the
codebase may hardcode a project ID, bucket, service account or URL.** Every
environment-specific value arrives here, so swapping projects is a one-file
edit and a code search for a stray project id has exactly one legitimate hit.

Deliberately not pydantic-settings: one dependency fewer, and the coercion
rules here are three lines. The schemas that matter are the agent contracts.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Sequence

__all__ = ["Settings", "settings", "load_settings"]

#: Gemini 3.x is not served from us-central1, where Cloud Run, Firestore and
#: GCS live. Defaulting to the data region would fail on the first model call.
DEFAULT_LOCATION = "global"

#: Local Vite dev server. Always allowed so a developer does not have to set
#: ALLOWED_ORIGINS to run the frontend.
LOCAL_ORIGIN = "http://localhost:5173"

#: Where recorded real runs live (FR-JUDGE-2). A module constant so the test
#: suite can point it elsewhere: a test's fake run must never be saved where
#: it could be played back as a real one.
DEFAULT_REPLAY_DIR = "data/replays"


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _integer(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw)
    except ValueError:
        return default


def _origins(raw: str | None) -> tuple[str, ...]:
    """Parse ALLOWED_ORIGINS (C-10).

    The browser calls Cloud Run directly, so the Hosting origins must be
    listed explicitly - there is no same-origin fallback to rely on. The local
    dev origin is always included so an empty variable still works locally;
    a wildcard is never used, because the API is not public.
    """
    listed = [part.strip() for part in (raw or "").split(",") if part.strip()]
    if LOCAL_ORIGIN not in listed:
        listed.append(LOCAL_ORIGIN)
    # Ordered and de-duplicated, so the header is stable across restarts.
    return tuple(dict.fromkeys(listed))


@dataclass(frozen=True)
class Settings:
    """Everything the API needs to know about where it is running."""

    project: str | None = None
    location: str = DEFAULT_LOCATION
    firestore_database: str = "(default)"
    gcs_bucket: str | None = None

    model_main: str = "gemini-3.5-flash-lite"
    model_reason: str = "gemini-3.8-flash"
    embed_model: str = "gemini-embedding-001"
    embed_dim: int = 768

    allowed_origins: tuple[str, ...] = (LOCAL_ORIGIN,)

    #: FR-GUARD. A cap and a per-IP limit, both visible in config per NFR-9.
    daily_analysis_cap: int = 300
    rate_limit_per_hour: int = 20
    max_query_chars: int = 300
    #: Google Cloud Model Armor template that screens follow-up questions and
    #: answers (catsight_agent.guardrails). None = the local filter only.
    model_armor_template: str | None = None
    #: Model Armor is regional; the template lives in this location.
    model_armor_location: str = "us-central1"

    #: REQUIREMENTS_V2 §7 feature switches, so behaviour can change during
    #: judging without a redeploy.
    courtroom_enabled: bool = True
    verifier_max_retries: int = 1
    #: Seconds one live model call may take before it fails. A failed call
    #: degrades safely (an unchecked quote is withheld, a side is dropped).
    model_call_timeout_s: int = 40
    #: Seconds a Courtroom request may take; past it the visitor is told the
    #: model is slow and can try again, well inside Cloud Run's 300 s limit.
    courtroom_deadline_s: int = 120
    cached_replay_only: bool = False
    #: Send ADK spans to Cloud Trace (app/logs.py). Off locally and in tests.
    enable_cloud_trace: bool = False
    replay_fixture_dir: str = "data/replays"

    build_label: str = "dev"
    #: Where the local data lives when Firestore is not in use.
    data_dir: str = "data"
    #: `local` reads JSON under data_dir; `firestore` reads the seeded
    #: collections. The code path is the same; only the source changes.
    data_backend: str = "local"

    _warnings: tuple[str, ...] = field(default=(), repr=False)

    @property
    def configured(self) -> bool:
        """Whether a model call could succeed. False locally without a project.

        The API still starts without one - `/healthz` must answer so a
        deployment can be diagnosed, and saying "up but unconfigured" is more
        useful than refusing to boot.
        """
        return bool(self.project)

    @property
    def warnings(self) -> tuple[str, ...]:
        return self._warnings


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """Build Settings from the environment (or an explicit mapping, for tests)."""
    if env is not None:
        previous = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        try:
            return load_settings()
        finally:
            os.environ.clear()
            os.environ.update(previous)

    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or None
    notes: list[str] = []
    if not project:
        notes.append(
            "GOOGLE_CLOUD_PROJECT is unset: model calls will fail. "
            "Copy backend/.env.example to backend/.env."
        )

    bucket = os.environ.get("GCS_BUCKET") or None
    if bucket and "<" in bucket:
        notes.append(f"GCS_BUCKET still holds a placeholder ({bucket}).")
        bucket = None

    origins = _origins(os.environ.get("ALLOWED_ORIGINS"))
    placeholder_origins = [origin for origin in origins if "<" in origin]
    if placeholder_origins:
        notes.append(
            "ALLOWED_ORIGINS still holds a placeholder: "
            + ", ".join(placeholder_origins)
        )
        origins = tuple(o for o in origins if "<" not in o)

    # MODEL_DEV is opt-in only, and never silently replaces MODEL_MAIN: a
    # prompt tuned against a model production does not use will drift. When it
    # is set, say so loudly rather than quietly serving a different model.
    model_main = os.environ.get("MODEL_MAIN") or "gemini-3.5-flash-lite"
    model_dev = os.environ.get("MODEL_DEV")
    if model_dev:
        notes.append(
            f"MODEL_DEV={model_dev} is set. This is a development model and "
            "must never be used for a measured run."
        )

    data_backend = (os.environ.get("DATA_BACKEND") or "local").strip().lower()
    if data_backend not in ("local", "firestore"):
        notes.append(f"DATA_BACKEND={data_backend!r} is not local or firestore; using local.")
        data_backend = "local"
    if data_backend == "firestore" and not project:
        notes.append("DATA_BACKEND=firestore needs GOOGLE_CLOUD_PROJECT; using local.")
        data_backend = "local"

    return Settings(
        project=project,
        location=os.environ.get("GOOGLE_CLOUD_LOCATION") or DEFAULT_LOCATION,
        firestore_database=os.environ.get("FIRESTORE_DATABASE") or "(default)",
        gcs_bucket=bucket,
        model_main=model_main,
        model_reason=os.environ.get("MODEL_REASON") or "gemini-3.8-flash",
        embed_model=os.environ.get("EMBED_MODEL") or "gemini-embedding-001",
        embed_dim=_integer("EMBED_DIM", 768),
        allowed_origins=origins,
        daily_analysis_cap=_integer("DAILY_ANALYSIS_CAP", 300),
        rate_limit_per_hour=_integer("RATE_LIMIT_PER_HOUR", 20),
        max_query_chars=_integer("MAX_QUERY_CHARS", 300),
        model_armor_template=(os.environ.get("MODEL_ARMOR_TEMPLATE") or "").strip() or None,
        model_armor_location=os.environ.get("MODEL_ARMOR_LOCATION") or "us-central1",
        courtroom_enabled=_flag("COURTROOM_ENABLED", True),
        verifier_max_retries=_integer("VERIFIER_MAX_RETRIES", 1),
        model_call_timeout_s=_integer("MODEL_CALL_TIMEOUT_S", 40),
        courtroom_deadline_s=_integer("COURTROOM_DEADLINE_S", 120),
        cached_replay_only=_flag("CACHED_REPLAY_ONLY", False),
        enable_cloud_trace=_flag("ENABLE_CLOUD_TRACE", False),
        replay_fixture_dir=os.environ.get("REPLAY_FIXTURE_DIR") or DEFAULT_REPLAY_DIR,
        build_label=os.environ.get("BUILD_LABEL") or "dev",
        data_dir=os.environ.get("DATA_DIR") or "data",
        data_backend=data_backend,
        _warnings=tuple(notes),
    )


#: Module-level settings, loaded once at import.
settings = load_settings()
