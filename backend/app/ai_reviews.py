import json
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.ai_credentials import GEMINI_PROVIDER, AiCredentialStore, readable_gemini_error
from app.config import Settings
from app.crypto import TokenCrypto
from app.learning import LearningStore
from app.store import TokenStore
from app.timezone import now_utc


ReviewDecision = Literal["ENTER", "WAIT", "IGNORE"]


@dataclass(frozen=True)
class GeminiReviewResult:
    status: str
    decision: str
    confidence: float
    summary: str
    support_price: float | None
    resistance_price: float | None
    entry_low: float | None
    entry_high: float | None
    stop_loss: float | None
    target_1: float | None
    target_2: float | None
    trailing_stop_loss: float | None
    risk_reward: float | None
    wait_until: str
    invalidation: str
    sources: list[dict[str, Any]]
    raw_response: dict[str, Any]


def failure_status_for_error(error: str) -> str:
    return "quota_limited" if "HTTP 429" in error else "failed"


def ensure_columns(conn, table_name: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {name} {definition}")


class AiReviewStore:
    def __init__(self, token_store: TokenStore) -> None:
        self.token_store = token_store
        self._init_db()

    def _connect(self):
        return self.token_store._connect()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_signal_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_signal_hit_id INTEGER NOT NULL,
                    decision_snapshot_id INTEGER,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    grounding_enabled INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0,
                    summary TEXT NOT NULL DEFAULT '',
                    support_price REAL,
                    resistance_price REAL,
                    entry_low REAL,
                    entry_high REAL,
                    stop_loss REAL,
                    target_1 REAL,
                    target_2 REAL,
                    trailing_stop_loss REAL,
                    risk_reward REAL,
                    wait_until TEXT NOT NULL DEFAULT '',
                    invalidation TEXT NOT NULL DEFAULT '',
                    sources_json TEXT NOT NULL DEFAULT '[]',
                    context_json TEXT NOT NULL,
                    raw_response_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ai_signal_reviews_hit
                ON ai_signal_reviews(source_signal_hit_id, id DESC)
                """
            )
            ensure_columns(
                conn,
                "ai_signal_reviews",
                {
                    "decision_snapshot_id": "INTEGER",
                    "grounding_enabled": "INTEGER NOT NULL DEFAULT 0",
                    "trailing_stop_loss": "REAL",
                    "wait_until": "TEXT NOT NULL DEFAULT ''",
                    "sources_json": "TEXT NOT NULL DEFAULT '[]'",
                    "raw_response_json": "TEXT NOT NULL DEFAULT '{}'",
                },
            )

    def signal_hit(self, hit_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM drishti_signal_hits WHERE id = ?", (hit_id,)).fetchone()
        return dict(row) if row else None

    def candles_until_trigger(self, instrument_id: int, trigger_date: str, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT trading_date, open, high, low, close, volume
                FROM daily_candles
                WHERE instrument_id = ? AND trading_date <= ?
                ORDER BY trading_date DESC
                LIMIT ?
                """,
                (instrument_id, trigger_date, min(max(limit, 20), 120)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def latest_for_hit(self, hit_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM ai_signal_reviews
                WHERE source_signal_hit_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (hit_id,),
            ).fetchone()
        return ai_review_row_to_dict(row) if row else None

    def insert_review(
        self,
        hit_id: int,
        provider: str,
        model: str,
        context: dict[str, Any],
        result: GeminiReviewResult,
        decision_snapshot_id: int | None = None,
        error: str = "",
    ) -> dict[str, Any]:
        timestamp = now_utc().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO ai_signal_reviews (
                    source_signal_hit_id, decision_snapshot_id, provider, model, grounding_enabled, status, decision, confidence,
                    summary, support_price, resistance_price, entry_low, entry_high,
                    stop_loss, target_1, target_2, trailing_stop_loss, risk_reward,
                    wait_until, invalidation, sources_json, context_json, raw_response_json,
                    error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    hit_id,
                    decision_snapshot_id,
                    provider,
                    model,
                    1 if context.get("ai_mode", {}).get("grounding_enabled") else 0,
                    result.status,
                    result.decision,
                    result.confidence,
                    result.summary,
                    result.support_price,
                    result.resistance_price,
                    result.entry_low,
                    result.entry_high,
                    result.stop_loss,
                    result.target_1,
                    result.target_2,
                    result.trailing_stop_loss,
                    result.risk_reward,
                    result.wait_until,
                    result.invalidation,
                    json.dumps(result.sources, sort_keys=True),
                    json.dumps(context, sort_keys=True),
                    json.dumps(result.raw_response, sort_keys=True),
                    error,
                    timestamp,
                    timestamp,
                ),
            )
            row = conn.execute("SELECT * FROM ai_signal_reviews WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return ai_review_row_to_dict(row)


class GeminiSignalReviewClient:
    def __init__(self, base_url: str, model: str, grounding_enabled: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.grounding_enabled = grounding_enabled

    async def review(self, api_key: str, prompt: str) -> dict[str, Any]:
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        if self.grounding_enabled:
            payload["tools"] = [{"google_search": {}}]
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{self.base_url}/v1beta/models/{self.model}:generateContent",
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            return response.json()


class AiSignalReviewService:
    def __init__(
        self,
        settings: Settings,
        token_store: TokenStore,
        store: AiReviewStore | None = None,
        credential_store: AiCredentialStore | None = None,
        gemini_client: GeminiSignalReviewClient | None = None,
    ) -> None:
        self.settings = settings
        self.token_store = token_store
        self.store = store or AiReviewStore(token_store)
        self.credential_store = credential_store or AiCredentialStore(token_store)
        self.learning_store = LearningStore(token_store)
        self.gemini_client = gemini_client or GeminiSignalReviewClient(
            settings.gemini_api_base_url,
            settings.gemini_model,
            settings.gemini_grounding_enabled,
        )

    def latest_review_for_hit(self, hit_id: int) -> dict[str, Any] | None:
        return self.store.latest_for_hit(hit_id)

    async def review_drishti_hit(self, hit_id: int) -> dict[str, Any]:
        hit = self.store.signal_hit(hit_id)
        if not hit:
            raise ValueError("Drishti signal hit was not found.")

        candles = self.store.candles_until_trigger(
            int(hit["instrument_id"]),
            hit["trigger_date"],
            self.settings.ai_review_candle_limit,
        )
        if len(candles) < 20:
            raise ValueError("Not enough cached candles to create an AI review.")

        credential = self.credential_store.get(GEMINI_PROVIDER)
        if credential is None:
            raise ValueError("Gemini API key is missing.")
        api_key = TokenCrypto(self.settings.app_secret_key).decrypt(credential.encrypted_api_key)

        context = build_review_context(hit, candles)
        context["ai_mode"] = {
            "provider": GEMINI_PROVIDER,
            "model": self.settings.gemini_model,
            "grounding_enabled": self.settings.gemini_grounding_enabled,
            "mode_label": "cached-data-only" if not self.settings.gemini_grounding_enabled else "cached-data-plus-search",
        }
        snapshot = self.learning_store.ensure_snapshot_for_hit(hit_id, context=context)
        prompt = build_review_prompt(context)
        try:
            raw_response = await self.gemini_client.review(api_key, prompt)
            result = normalize_gemini_review(raw_response)
        except Exception as exc:
            error = readable_gemini_error(exc)
            result = GeminiReviewResult(
                status=failure_status_for_error(error),
                decision="IGNORE",
                confidence=0,
                summary=(
                    "Gemini quota/rate limit was reached. Treat this signal as not reviewed."
                    if "HTTP 429" in error
                    else "Gemini review failed. Treat this signal as not reviewed."
                ),
                support_price=None,
                resistance_price=None,
                entry_low=None,
                entry_high=None,
                stop_loss=None,
                target_1=None,
                target_2=None,
                trailing_stop_loss=None,
                risk_reward=None,
                wait_until="AI review did not complete; do not act on this alert.",
                invalidation=(
                    "Gemini quota/rate limit stopped the review before a valid decision."
                    if "HTTP 429" in error
                    else "AI review failed before producing a valid decision."
                ),
                sources=[],
                raw_response={},
            )
            return self.store.insert_review(
                hit_id=hit_id,
                provider=GEMINI_PROVIDER,
                model=self.settings.gemini_model,
                context=context,
                result=result,
                decision_snapshot_id=snapshot.get("id"),
                error=error,
            )

        result = enforce_review_safety(result, hit)
        return self.store.insert_review(
            hit_id=hit_id,
            provider=GEMINI_PROVIDER,
            model=self.settings.gemini_model,
            context=context,
            result=result,
            decision_snapshot_id=snapshot.get("id"),
        )


def build_review_context(hit: dict[str, Any], candles: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [float(candle["close"]) for candle in candles]
    highs = [float(candle["high"]) for candle in candles]
    lows = [float(candle["low"]) for candle in candles]
    volumes = [float(candle["volume"]) for candle in candles]
    trigger_close = float(hit["trigger_close"])
    trigger_low = float(hit["trigger_low"])
    anchor_low = float(hit["anchor_low"])
    avg_volume_20 = sum(volumes[-20:]) / min(len(volumes), 20)
    low_45 = min(lows[-45:]) if len(lows) >= 45 else min(lows)
    high_45 = max(highs[-45:]) if len(highs) >= 45 else max(highs)
    return {
        "review_mode": "alert_time_only_no_future_candles",
        "signal": {
            "hit_id": hit["id"],
            "signal_id": hit["signal_id"],
            "symbol": hit["symbol"],
            "company_name": hit["company_name"],
            "industry": hit["industry"],
            "isin": hit["isin"],
            "security_id": hit["security_id"],
            "anchor_date": hit["anchor_date"],
            "trigger_date": hit["trigger_date"],
            "anchor_low": anchor_low,
            "anchor_high": float(hit["anchor_high"]),
            "anchor_close": float(hit["anchor_close"]),
            "trigger_low": trigger_low,
            "trigger_close": trigger_close,
            "volume_ratio_1d": float(hit["volume_ratio_1d"]),
            "volume_vs_sma": float(hit["volume_vs_sma"]),
        },
        "computed_features": {
            "candle_count": len(candles),
            "latest_close": closes[-1],
            "low_45": low_45,
            "high_45": high_45,
            "move_from_45d_low_percent": ((trigger_close - low_45) / low_45) * 100 if low_45 > 0 else 0,
            "distance_to_45d_high_percent": ((high_45 - trigger_close) / high_45) * 100 if high_45 > 0 else 0,
            "avg_volume_20": avg_volume_20,
            "trigger_volume_vs_20d_avg": float(hit["trigger_volume"]) / avg_volume_20 if avg_volume_20 > 0 else 0,
        },
        "recent_candles": [
            {
                "date": candle["trading_date"],
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": float(candle["volume"]),
            }
            for candle in candles[-30:]
        ],
    }


def build_review_prompt(context: dict[str, Any]) -> str:
    return (
        "You are reviewing a demo-only swing trading early-warning alert for NSE equities. "
        "Drishti only provides the early warning; your job is detailed research and trade-quality triage. "
        "Use the supplied EOD signal data. If ai_mode.grounding_enabled is false, do not claim live news, "
        "live prices, or external research; the review is cached-data only. If grounding is enabled, use current "
        "public information only when it materially changes risk. This is not a live order instruction. Decide whether this alert is "
        "ENTER, WAIT, or IGNORE for demo-trade tracking.\n\n"
        "Return strict JSON only with this shape:\n"
        "{"
        '"decision":"ENTER|WAIT|IGNORE",'
        '"confidence":0-100,'
        '"summary":"one short paragraph",'
        '"support_price":number|null,'
        '"resistance_price":number|null,'
        '"entry_low":number|null,'
        '"entry_high":number|null,'
        '"stop_loss":number|null,'
        '"target_1":number|null,'
        '"target_2":number|null,'
        '"trailing_stop_loss":number|null,'
        '"risk_reward":number|null,'
        '"wait_until":"if WAIT, exact condition/price/date to wait for; otherwise empty string",'
        '"invalidation":"short condition that invalidates the idea"'
        "}\n\n"
        "Decision rules: ENTER only if a long setup has clear entry, stop_loss, target_1, trailing_stop_loss, "
        "and risk_reward >= 2. WAIT only if the setup is promising but needs confirmation; wait_until must say exactly "
        "what to wait for, such as a close above resistance, pullback near support, or volume confirmation. "
        "IGNORE if the signal is noise, risk/reward is weak, trend/context is bad, or trade math is not possible.\n\n"
        f"Context JSON:\n{json.dumps(context, sort_keys=True)}"
    )


def normalize_gemini_review(raw_response: dict[str, Any]) -> GeminiReviewResult:
    text = extract_gemini_text(raw_response)
    payload = parse_json_object(text)
    decision = str(payload.get("decision", "IGNORE")).upper()
    if decision not in {"ENTER", "WAIT", "IGNORE"}:
        decision = "IGNORE"
    return GeminiReviewResult(
        status="completed",
        decision=decision,
        confidence=clamp_float(payload.get("confidence"), 0, 100),
        summary=str(payload.get("summary") or "").strip()[:1000],
        support_price=optional_float(payload.get("support_price")),
        resistance_price=optional_float(payload.get("resistance_price")),
        entry_low=optional_float(payload.get("entry_low")),
        entry_high=optional_float(payload.get("entry_high")),
        stop_loss=optional_float(payload.get("stop_loss")),
        target_1=optional_float(payload.get("target_1")),
        target_2=optional_float(payload.get("target_2")),
        trailing_stop_loss=optional_float(payload.get("trailing_stop_loss")),
        risk_reward=optional_float(payload.get("risk_reward")),
        wait_until=str(payload.get("wait_until") or "").strip()[:500],
        invalidation=str(payload.get("invalidation") or "").strip()[:500],
        sources=extract_grounding_sources(raw_response),
        raw_response=raw_response,
    )


def enforce_review_safety(result: GeminiReviewResult, hit: dict[str, Any]) -> GeminiReviewResult:
    if result.decision != "ENTER":
        if result.decision == "WAIT" and not result.wait_until:
            return GeminiReviewResult(
                status=result.status,
                decision="IGNORE",
                confidence=min(result.confidence, 50),
                summary=result.summary or f"{hit['symbol']} had no actionable wait condition.",
                support_price=result.support_price,
                resistance_price=result.resistance_price,
                entry_low=result.entry_low,
                entry_high=result.entry_high,
                stop_loss=result.stop_loss,
                target_1=result.target_1,
                target_2=result.target_2,
                trailing_stop_loss=result.trailing_stop_loss,
                risk_reward=result.risk_reward,
                wait_until="",
                invalidation="WAIT decision was downgraded because no wait condition was returned.",
                sources=result.sources,
                raw_response=result.raw_response,
            )
        return result
    entry_low = result.entry_low
    entry_high = result.entry_high
    stop_loss = result.stop_loss
    target_1 = result.target_1
    trailing_stop_loss = result.trailing_stop_loss
    risk_reward = result.risk_reward
    valid = (
        entry_low is not None
        and entry_high is not None
        and stop_loss is not None
        and target_1 is not None
        and trailing_stop_loss is not None
        and risk_reward is not None
        and entry_low > 0
        and entry_high >= entry_low
        and stop_loss < entry_low
        and target_1 > entry_high
        and trailing_stop_loss < entry_high
        and risk_reward >= 2
    )
    if valid:
        return result
    return GeminiReviewResult(
        status=result.status,
        decision="WAIT",
        confidence=min(result.confidence, 50),
        summary=(
            result.summary
            or f"{hit['symbol']} was not promoted to ENTER because the returned trade math was invalid."
        ),
        support_price=result.support_price,
        resistance_price=result.resistance_price,
        entry_low=result.entry_low,
        entry_high=result.entry_high,
        stop_loss=result.stop_loss,
        target_1=result.target_1,
        target_2=result.target_2,
        trailing_stop_loss=result.trailing_stop_loss,
        risk_reward=result.risk_reward,
        wait_until="Wait for a fresh valid setup with entry, stop, trailing stop, target, and risk/reward >= 2.",
        invalidation="AI trade math failed validation, so the decision was downgraded to WAIT.",
        sources=result.sources,
        raw_response=result.raw_response,
    )


def extract_gemini_text(raw_response: dict[str, Any]) -> str:
    candidates = raw_response.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini response did not include candidates.")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(str(part.get("text", "")) for part in parts).strip()
    if not text:
        raise ValueError("Gemini response did not include text.")
    return text


def parse_json_object(text: str) -> dict[str, Any]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.lower().startswith("json"):
            clean = clean[4:].strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Gemini response was not valid JSON.")
    payload = json.loads(clean[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Gemini response JSON must be an object.")
    return payload


def optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clamp_float(value: Any, minimum: float, maximum: float) -> float:
    numeric = optional_float(value)
    if numeric is None:
        return minimum
    return min(max(numeric, minimum), maximum)


def extract_grounding_sources(raw_response: dict[str, Any]) -> list[dict[str, str]]:
    candidates = raw_response.get("candidates") or []
    if not candidates:
        return []
    chunks = candidates[0].get("groundingMetadata", {}).get("groundingChunks", []) or []
    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for chunk in chunks:
        web = chunk.get("web") or {}
        uri = str(web.get("uri") or "").strip()
        title = str(web.get("title") or "").strip()
        if not uri or uri in seen:
            continue
        seen.add(uri)
        sources.append({"title": title, "uri": uri})
    return sources[:8]


def ai_review_row_to_dict(row) -> dict[str, Any]:
    sources = json.loads(row["sources_json"] or "[]") if "sources_json" in row.keys() else []
    return {
        "id": row["id"],
        "source_signal_hit_id": row["source_signal_hit_id"],
        "decision_snapshot_id": row["decision_snapshot_id"] if "decision_snapshot_id" in row.keys() else None,
        "provider": row["provider"],
        "model": row["model"],
        "grounding_enabled": bool(row["grounding_enabled"]) if "grounding_enabled" in row.keys() else False,
        "status": row["status"],
        "decision": row["decision"],
        "confidence": row["confidence"],
        "summary": row["summary"],
        "support_price": row["support_price"],
        "resistance_price": row["resistance_price"],
        "entry_low": row["entry_low"],
        "entry_high": row["entry_high"],
        "stop_loss": row["stop_loss"],
        "target_1": row["target_1"],
        "target_2": row["target_2"],
        "trailing_stop_loss": row["trailing_stop_loss"] if "trailing_stop_loss" in row.keys() else None,
        "risk_reward": row["risk_reward"],
        "wait_until": row["wait_until"] if "wait_until" in row.keys() else "",
        "invalidation": row["invalidation"],
        "sources": sources,
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
