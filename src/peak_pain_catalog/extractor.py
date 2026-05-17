"""Single-LLM feature extraction.

Per Section 5 Q3 of the v3 spec, each LLM in the 3-LLM consensus pipeline runs
this single-pass extractor against a CaseRecord's descriptive text. The
extractor prompt:

    1. Names the case (ticker, sector, era).
    2. Provides the row text as evidence.
    3. Lists exactly which features to extract (universal core + sector
       extension subset for the case's sector).
    4. Demands forced-JSON output: per feature, {value, verbatim_quote}.
    5. States the "no quote → most-conservative default" fallback rule.

Model selection (Section 5 Q3 + cost model in catalog v0.1):
    - Primary extractor: claude-sonnet-4-6 (cheap, accurate enough for the
      structural-feature task; verbatim quoting forces grounding).
    - Tie-breaker / Opus mix: claude-opus-4-7 used for the 3rd LLM in the
      consensus pipeline (see consensus.py) — improves recall on edge cases.

Reference: docs/superpowers/specs/2026-04-29-empirical-foundation-design-v3.md
           Section 5 Q3 (3-LLM iterative-consensus + verbatim quote requirement)
           + Section 4.4 (universal-core schema).
"""

from __future__ import annotations

import dataclasses
import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.peak_pain_catalog.feature_typing import (
    CATEGORICAL_DOMAINS,
    FEATURE_TYPES,
    ORDINAL_ORDERS,
    UNIVERSAL_CORE,
)
from src.peak_pain_catalog.parser import CaseRecord


# ---------------------------------------------------------------------------
# Conservative defaults — used when LLM emits no verbatim quote (Section 5 Q3
# fallback rule). Keyed by feature name; picks the most-conservative value
# from the feature's domain.
# ---------------------------------------------------------------------------

CONSERVATIVE_DEFAULTS: dict[str, str] = {
    # Universal core (worst-case = "no signal we'd want to retrieve on")
    "founder_insider_stake_direction": "departed",
    "founder_in_place": "departed",
    "cash_runway": "distressed",
    "margin_trajectory": "deteriorating",
    "revenue_trajectory": "declining",
    "industry_tailwind": "structural-decline",
    # Common sector extensions
    "customer_engagement": "collapsed",
    "engagement_decoupling_from_price": "no",
    "moat_state": "leapfrogged",
    "cycle_state": "structural-decline",
    "leverage_level": "distressed",
    "credit_quality": "severely-impaired",
    "regulatory_standing": "hostile",
    "pipeline_depth": "concentrated",
    "trial_status_at_trough": "negative",
    "TAM_state": "closed",
    "backlog_quality": "aspirational",
    "litigation_state": "open-ended",
    "CEO_change_quality": "founder-entrenched",
    "net_debt_at_trough": "distressed",
    "hedge_book": "unhedged",
    "reserve_quality": "marginal",
    "cost_curve": "high",
    "property_tier": "C",
    "debt_maturity_wall": "immediate",
    "asset_class_tailwind": "structural-decline",
    "capital_ratio": "inadequate",
    "uninsured_deposit_pct": ">66%",
    "dilution_at_trough": "extreme",
    "asset_quality": "impaired",
    "redemption_rate": "extreme",
    "vehicle_margin": "catastrophic-negative",
    "production_trajectory": "declining",
    "counterparty_exposure": "large",
}


# Sector-extension feature lists (from catalog v0.1 Layer 2 table).
SECTOR_EXTENSIONS: dict[str, list[str]] = {
    "tech_saas": [
        "customer_engagement",
        "engagement_decoupling_from_price",
        "NDR_trend",
    ],
    "semis_hardware": ["moat_state", "cycle_state", "customer_concentration"],
    "consumer_discretionary": [
        "repeat_purchase_trajectory",
        "brand_equity_state",
        "distribution_channel_integrity",
    ],
    "consumer_brands": [
        "brand_equity_state",
        "leverage_level",
        "leadership_replacement_quality",
    ],
    "fintech": [
        "take_rate_trajectory",
        "credit_quality",
        "regulatory_standing",
    ],
    "healthcare_biotech": [
        "pipeline_depth",
        "trial_status_at_trough",
        "TAM_state",
    ],
    "industrial": ["backlog_quality", "litigation_state", "CEO_change_quality"],
    "energy": ["net_debt_at_trough", "hedge_book", "reserve_quality", "cost_curve"],
    "comms_media": [
        "content_IP_moat_state",
        "subscriber_DAU_trajectory",
        "leverage_multiple",
    ],
    "international_em": [
        "regulatory_overhang_state",
        "geopolitical_state",
        "capital_controls_FX_exposure",
    ],
    "ev_autos": ["production_trajectory", "vehicle_margin", "capital_structure"],
    "reits": [
        "property_tier",
        "debt_maturity_wall",
        "asset_class_tailwind",
        "tenant_credit_concentration",
    ],
    "recent_ipo_spac": [
        "redemption_rate",
        "lockup_behavior",
        "deck_vs_actual_revenue_gap",
    ],
    "crypto_adjacent": ["counterparty_exposure", "cost_curve", "regulatory_standing"],
    "financials_banks": [
        "capital_ratio",
        "uninsured_deposit_pct",
        "dilution_at_trough",
        "asset_quality",
    ],
    # Pre-2008 era cases use universal-core only (intentional per Section 4.4):
    # era cases are heterogeneous across sectors, so we extract only the seven
    # universal-core features and rely on era_category in persistence for
    # cohort-aware retrieval rather than per-era sector hints.
    "dot_com": [],
    "gfc_nonfin": [],
    "recession_1989_92": [],
    "stagflation_1973_82": [],
}


@dataclass(frozen=True)
class ExtractedFeature:
    """One LLM-extracted feature value with provenance.

    Attributes:
        feature_name:    e.g. "cash_runway".
        value:           The extracted categorical/ordinal value.
        verbatim_quote:  Verbatim source quote that grounds the value, or
                         empty string if the LLM produced none (in which case
                         `defaulted` is True and value is the conservative
                         default).
        defaulted:       True if value was assigned by no-quote fallback
                         (Section 5 Q3 rule).
    """

    feature_name: str
    value: str
    verbatim_quote: str = ""
    defaulted: bool = False


@dataclass(frozen=True)
class ExtractionResult:
    """Output of one LLM call across all features for one case.

    Attributes:
        case_id:           Case under extraction.
        model_id:          The Anthropic model id used for this call.
        universal_core:    Mapping feature → ExtractedFeature for the 6 core
                           features.
        sector_extensions: Same shape, scoped to the case's sector.
        raw_response:      Raw LLM text (stored for audit chain).
    """

    case_id: str
    model_id: str
    universal_core: dict[str, ExtractedFeature] = field(default_factory=dict)
    sector_extensions: dict[str, ExtractedFeature] = field(default_factory=dict)
    raw_response: str = ""

    def all_features(self) -> dict[str, ExtractedFeature]:
        """Flat view: all features (core + extensions) keyed by feature_name."""
        merged: dict[str, ExtractedFeature] = {}
        merged.update(self.universal_core)
        merged.update(self.sector_extensions)
        return merged


class AnthropicClient(Protocol):
    """Minimal Anthropic SDK client surface used by the extractor.

    Production: an `anthropic.Anthropic()` instance. Tests: a stub returning
    canned responses (see tests/test_peak_pain_catalog.py).
    """

    def messages_create(  # noqa: D401 — protocol shape
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, Any]],
    ) -> Any: ...


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_feature_spec(case: CaseRecord) -> list[str]:
    """Pick which features to extract for `case` (universal-core + extensions)."""
    feats = list(UNIVERSAL_CORE)
    feats.extend(SECTOR_EXTENSIONS.get(case.sector, []))
    return feats


def _build_system_prompt() -> str:
    """System prompt — locks the extractor's behavior contract."""
    return (
        "You are a forensic feature extractor for a peak-pain archetype "
        "catalog. For each requested feature, you return:\n"
        "  - value: a string from the declared domain\n"
        "  - verbatim_quote: a short verbatim quote from the EVIDENCE that "
        "grounds the value\n\n"
        "Rules:\n"
        "1. Output ONLY a single JSON object — no prose, no markdown fences.\n"
        "2. If you cannot find a verbatim quote in the EVIDENCE that supports "
        "a value, set verbatim_quote to empty string AND value to the "
        "conservative default supplied per feature.\n"
        "3. Never invent values. Use only what the evidence supports.\n"
        "4. Ordinal values must come from the declared ordering. Categorical "
        "values must come from the declared domain.\n"
    )


def _format_feature_descriptor(feature: str) -> str:
    """Format the per-feature line in the user prompt."""
    parts = [f"  - {feature}:"]
    if feature in ORDINAL_ORDERS:
        parts.append(
            f"    type=ordinal; allowed={ORDINAL_ORDERS[feature]}; "
            f"conservative_default={CONSERVATIVE_DEFAULTS.get(feature, '')!r}"
        )
    elif feature in CATEGORICAL_DOMAINS:
        parts.append(
            f"    type=categorical; allowed={CATEGORICAL_DOMAINS[feature]}; "
            f"conservative_default={CONSERVATIVE_DEFAULTS.get(feature, '')!r}"
        )
    else:
        parts.append("    type=freeform")
    return "\n".join(parts)


def _build_user_prompt(case: CaseRecord, feature_spec: list[str]) -> str:
    feature_block = "\n".join(_format_feature_descriptor(f) for f in feature_spec)
    return (
        f"CASE: {case.case_id} (ticker={case.ticker}, sector={case.sector}, "
        f"era={case.era_category}, outcome={case.outcome})\n\n"
        f"EVIDENCE:\n{case.descriptive_text}\n\n"
        f"FEATURES TO EXTRACT (each as JSON object with keys "
        f'"value" and "verbatim_quote"):\n{feature_block}\n\n'
        "Return JSON of shape:\n"
        "{\n"
        '  "<feature_name>": {"value": "...", "verbatim_quote": "..."},\n'
        "  ...\n"
        "}\n"
    )


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def extract_features(
    case: CaseRecord,
    *,
    client: AnthropicClient,
    model: str = "claude-sonnet-4-6",
    max_tokens: int = 1500,
    surfaced_disagreement: dict[str, list[str]] | None = None,
) -> ExtractionResult:
    """Run a single LLM extraction pass for `case`.

    Args:
        case:    The CaseRecord to extract features from.
        client:  Anthropic SDK client (or test stub) that exposes
                 `messages_create(...)`.
        model:   Anthropic model id. Default `claude-sonnet-4-6`. The 3rd LLM
                 in the consensus pipeline typically uses `claude-opus-4-7`.
        max_tokens: Cap on response tokens.
        surfaced_disagreement: Optional dict mapping feature_name →
                 [conflicting values from prior iteration]. Used by
                 consensus.py iterations 2..5 to prompt the LLM with the
                 specific disagreement to break.

    Returns:
        ExtractionResult containing universal_core + sector_extensions
        feature dicts, plus raw response text for audit.
    """
    feature_spec = _build_feature_spec(case)
    system = _build_system_prompt()
    user = _build_user_prompt(case, feature_spec)
    if surfaced_disagreement:
        diss = "\n".join(
            f"  - {feat}: prior LLMs disagreed → values were {vals!r}. "
            "Re-examine the evidence and pick the value most strongly grounded."
            for feat, vals in surfaced_disagreement.items()
        )
        user += f"\n\nPRIOR DISAGREEMENT (resolve in this pass):\n{diss}\n"

    response = client.messages_create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    raw_text = _coerce_response_text(response)
    parsed = _parse_response_json(raw_text)

    core: dict[str, ExtractedFeature] = {}
    ext: dict[str, ExtractedFeature] = {}
    sector_features = set(SECTOR_EXTENSIONS.get(case.sector, []))
    for feat in feature_spec:
        ef = _build_extracted_feature(feat, parsed.get(feat))
        if feat in UNIVERSAL_CORE:
            core[feat] = ef
        elif feat in sector_features:
            ext[feat] = ef
    return ExtractionResult(
        case_id=case.case_id,
        model_id=model,
        universal_core=core,
        sector_extensions=ext,
        raw_response=raw_text,
    )


# ---------------------------------------------------------------------------
# Response coercion + JSON parsing
# ---------------------------------------------------------------------------


def _coerce_response_text(response: Any) -> str:
    """Pull the text payload off an Anthropic SDK Message (or test-stub dict)."""
    # Real SDK: response.content is list of ContentBlock; text-block has .text
    content = getattr(response, "content", None)
    if content is not None:
        parts = []
        for block in content:
            t = getattr(block, "text", None)
            if t is None and isinstance(block, dict):
                t = block.get("text")
            if t:
                parts.append(t)
        if parts:
            return "".join(parts)
    if isinstance(response, dict):
        # Test stub: {"content": [{"text": "..."}]} or {"text": "..."}
        if "content" in response:
            for block in response["content"]:
                if isinstance(block, dict) and "text" in block:
                    return block["text"]
        if "text" in response:
            return response["text"]
    if isinstance(response, str):
        return response
    return ""


def _parse_response_json(text: str) -> dict[str, Any]:
    """Tolerant JSON parser robust to ```json fences and prose wrappers.

    Implementation note: the prior fence-strip path used
    ``s.split("```", 2)[-1]`` which for a fully-fenced response like
    ``"```json\\n{...}\\n```"`` returns the EMPTY trailing element after the
    closing fence. That silently emptied the payload and forced every
    feature to its CONSERVATIVE_DEFAULTS value. Critical bug fixed
    2026-04-30 — see git blame for context.

    Robust strategy: locate the outermost {...} substring with
    ``find("{")`` / ``rfind("}")`` and parse it directly. Works whether the
    response is fenced, partially-fenced, or wrapped in prose.
    """
    if not text:
        return {}
    s = text.strip()
    # Outermost {...} block — robust to fences/prose wrappers.
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(s[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            return {}
    return {}


def _build_extracted_feature(
    feature_name: str, payload: Any
) -> ExtractedFeature:
    """Materialize ExtractedFeature from raw LLM payload, applying default rule."""
    default = CONSERVATIVE_DEFAULTS.get(feature_name, "")
    if not isinstance(payload, dict):
        return ExtractedFeature(
            feature_name=feature_name,
            value=default,
            verbatim_quote="",
            defaulted=True,
        )
    quote = str(payload.get("verbatim_quote") or "").strip()
    raw_value = payload.get("value")
    value = str(raw_value).strip() if raw_value is not None else ""
    if not quote or not value:
        return ExtractedFeature(
            feature_name=feature_name,
            value=default,
            verbatim_quote="",
            defaulted=True,
        )
    return ExtractedFeature(
        feature_name=feature_name,
        value=value,
        verbatim_quote=quote,
        defaulted=False,
    )


# ---------------------------------------------------------------------------
# JSON-friendly export (for persistence + audit)
# ---------------------------------------------------------------------------


def extraction_to_dict(result: ExtractionResult) -> dict[str, Any]:
    """Serialize an ExtractionResult to a plain dict (for HMAC + JSONB)."""
    return {
        "case_id": result.case_id,
        "model_id": result.model_id,
        "universal_core": {
            k: dataclasses.asdict(v) for k, v in result.universal_core.items()
        },
        "sector_extensions": {
            k: dataclasses.asdict(v) for k, v in result.sector_extensions.items()
        },
    }


def get_anthropic_client_from_env() -> AnthropicClient:
    """Construct a real `anthropic.Anthropic` client adapter using ANTHROPIC_API_KEY.

    Raises ImportError if `anthropic` is not installed in the environment.
    Tests use a stub client and never call this.
    """
    try:
        from anthropic import Anthropic  # type: ignore[import-not-found]
    except ImportError as e:  # pragma: no cover — import path
        raise ImportError(
            "anthropic SDK not installed; `pip install anthropic` or use a test stub"
        ) from e
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment")
    real = Anthropic(api_key=api_key)

    class _Adapter:
        def messages_create(self, **kwargs: Any) -> Any:
            return real.messages.create(**kwargs)

    return _Adapter()
