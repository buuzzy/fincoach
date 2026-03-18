"""QVeris API client — search, execute, and automatic key rotation.

Key rotation strategy
---------------------
A ``KeyPool`` holds an ordered list of API keys.  On every request it uses the
current active key.  When a response signals quota exhaustion (HTTP 429, 402, or
a JSON body containing ``"quota"`` / ``"rate_limit"`` / ``"exhausted"``) the
pool marks that key as exhausted and promotes the next available key.  If all
keys are exhausted a ``KeyPoolExhaustedError`` is raised.

Usage
-----
    pool = KeyPool(["sk-aaa", "sk-bbb", "sk-ccc"])

    # low-level helpers used by ai_agent.py
    tool_id, search_id = await pool.search("A股历史K线 600519.SH")
    result = await pool.execute(tool_id, search_id, {...})
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Exceptions ────────────────────────────────────────────────────────────────


class KeyPoolExhaustedError(RuntimeError):
    """Raised when every API key in the pool has been exhausted."""


# ── Search-result cache (process-lifetime) ────────────────────────────────────

_search_cache: dict[str, tuple[str, str]] = {}


def clear_search_cache() -> None:
    """Clear the in-memory search cache (useful in tests)."""
    _search_cache.clear()


# ── Low-level helpers (single-key, no rotation) ───────────────────────────────


def _is_quota_error(response: httpx.Response) -> bool:
    """Return True if the response indicates the key is quota-exhausted."""
    if response.status_code in (402, 429):
        return True
    # Some providers return 200 with an error body
    try:
        body = response.json()
        msg = str(body).lower()
        return any(kw in msg for kw in ("quota", "rate_limit", "exhausted", "insufficient"))
    except Exception:
        return False


async def _search_once(
    query: str,
    api_key: str,
    base_url: str,
) -> tuple[str, str]:
    """Single-key search; raises httpx.HTTPStatusError on non-2xx.

    QVeris search response shape:
      {
        "query": "...",
        "search_id": "uuid",          ← top-level
        "total": 82,
        "results": [
          {"tool_id": "ths_ifind.history_quotation.v1", ...},
          ...
        ]
      }
    Returns (first_tool_id, search_id).
    """
    url = f"{base_url}/search"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, json={"query": query}, headers=headers)
        response.raise_for_status()
        data: dict[str, Any] = response.json()

    search_id: str = data.get("search_id", "")
    results: list[dict[str, Any]] = data.get("results", [])

    if not search_id or not results:
        raise ValueError(f"[QVeris] Unexpected search response (no search_id or results): {data}")

    # Return the tool_id of the first result; caller can override if needed
    tool_id: str = results[0].get("tool_id", "")
    if not tool_id:
        raise ValueError(f"[QVeris] First search result has no tool_id: {results[0]}")

    return tool_id, search_id


async def _execute_once(
    tool_id: str,
    search_id: str,
    params: dict[str, Any],
    api_key: str,
    base_url: str,
) -> dict[str, Any]:
    """Single-key execute; raises httpx.HTTPStatusError on non-2xx.

    QVeris execute request body:
      {
        "search_id": "...",
        "parameters": {...}      ← MUST be "parameters", not "params"
      }
    """
    url = f"{base_url}/tools/execute"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"search_id": search_id, "parameters": params}
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            url, json=payload, headers=headers, params={"tool_id": tool_id}
        )
        response.raise_for_status()
        return response.json()


# ── KeyPool ───────────────────────────────────────────────────────────────────


class KeyPool:
    """Ordered pool of QVeris API keys with automatic quota-rotation.

    When the active key is exhausted the pool silently promotes the next one.
    All keys exhausted → raises ``KeyPoolExhaustedError``.
    """

    def __init__(self, keys: list[str], base_url: str = "https://qveris.ai/api/v1") -> None:
        if not keys:
            raise ValueError("KeyPool requires at least one API key.")
        self._keys = list(keys)
        self._exhausted: set[int] = set()
        self._current_idx: int = 0
        self.base_url = base_url
        logger.info("[KeyPool] Initialised with %d key(s).", len(self._keys))

    # ── Public state ──────────────────────────────────────────────────────────

    @property
    def active_key(self) -> str:
        return self._keys[self._current_idx]

    @property
    def available_count(self) -> int:
        return len(self._keys) - len(self._exhausted)

    # ── Internal rotation ─────────────────────────────────────────────────────

    def _mark_exhausted(self, idx: int) -> None:
        self._exhausted.add(idx)
        logger.warning(
            "[KeyPool] Key #%d exhausted (%d/%d remaining).",
            idx + 1,
            self.available_count - 1,  # -1 because we haven't rotated yet
            len(self._keys),
        )

    def _rotate(self) -> None:
        """Promote to the next non-exhausted key, or raise if none left."""
        for i in range(len(self._keys)):
            idx = (self._current_idx + 1 + i) % len(self._keys)
            if idx not in self._exhausted:
                self._current_idx = idx
                logger.info("[KeyPool] Rotated to key #%d.", idx + 1)
                return
        raise KeyPoolExhaustedError(
            f"All {len(self._keys)} QVeris API key(s) are exhausted."
        )

    # ── Search with retry-on-quota ────────────────────────────────────────────

    async def search(self, query: str, preferred_tool_id: str | None = None) -> tuple[str, str]:
        """Search with automatic key rotation on quota errors.

        Results are cached per (base_url, query) to avoid redundant requests.

        Args:
            query: Natural-language search query.
            preferred_tool_id: If given, look for this tool_id in results and
                return it; fall back to the first result if not found.
        """
        cache_key = f"{self.base_url}|{query}"
        if cache_key in _search_cache:
            cached = _search_cache[cache_key]
            # If caller wants a specific tool, check if cached tool matches
            if preferred_tool_id is None or cached[0] == preferred_tool_id:
                logger.debug("[KeyPool] cache hit for query=%r", query)
                return cached

        attempts = len(self._keys)
        for _ in range(attempts):
            key_idx = self._current_idx
            key = self.active_key
            try:
                first_tool_id, search_id = await _search_once(query, key, self.base_url)

                # If caller wants a specific tool_id, do another raw search to get full results
                if preferred_tool_id and preferred_tool_id != first_tool_id:
                    # Re-fetch full results to find preferred tool
                    url = f"{self.base_url}/search"
                    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
                    import httpx as _httpx
                    async with _httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.post(url, json={"query": query}, headers=headers)
                        response.raise_for_status()
                        data = response.json()
                    search_id = data.get("search_id", search_id)
                    results = data.get("results", [])
                    matched = next((r["tool_id"] for r in results if r.get("tool_id") == preferred_tool_id), None)
                    result_tool_id = matched or first_tool_id
                else:
                    result_tool_id = first_tool_id

                result = (result_tool_id, search_id)
                logger.info("[KeyPool] search ok key=#%d query=%r tool=%s", key_idx + 1, query, result_tool_id)
                _search_cache[cache_key] = result
                return result
            except httpx.HTTPStatusError as exc:
                if _is_quota_error(exc.response):
                    self._mark_exhausted(key_idx)
                    self._rotate()
                    continue
                raise
            except Exception:
                raise

        raise KeyPoolExhaustedError("All keys failed during search.")

    # ── Execute with retry-on-quota ───────────────────────────────────────────

    async def execute(
        self, tool_id: str, search_id: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a tool with automatic key rotation on quota errors."""
        attempts = len(self._keys)
        for _ in range(attempts):
            key_idx = self._current_idx
            key = self.active_key
            try:
                result = await _execute_once(tool_id, search_id, params, key, self.base_url)
                logger.info(
                    "[KeyPool] execute ok key=#%d tool_id=%s", key_idx + 1, tool_id
                )
                return result
            except httpx.HTTPStatusError as exc:
                if _is_quota_error(exc.response):
                    self._mark_exhausted(key_idx)
                    self._rotate()
                    continue
                raise
            except Exception:
                raise

        raise KeyPoolExhaustedError("All keys failed during execute.")


# ── Global singleton (initialised from settings in main.py) ───────────────────

_global_pool: KeyPool | None = None


def init_key_pool(keys: list[str], base_url: str = "https://qveris.ai/api/v1") -> KeyPool:
    """Initialise (or replace) the process-wide KeyPool."""
    global _global_pool
    _global_pool = KeyPool(keys, base_url)
    return _global_pool


def get_key_pool() -> KeyPool:
    """Return the global KeyPool; raises RuntimeError if not initialised."""
    if _global_pool is None:
        raise RuntimeError(
            "QVeris KeyPool has not been initialised. "
            "Call init_key_pool() during app startup."
        )
    return _global_pool


# ── Convenience wrappers (used by ai_agent.py) ────────────────────────────────


async def qveris_search(
    query: str,
    api_key: str | None = None,
    base_url: str = "https://qveris.ai/api/v1",
) -> tuple[str, str]:
    """Search via the global pool (api_key / base_url params kept for compat)."""
    return await get_key_pool().search(query)


async def qveris_execute(
    tool_id: str,
    search_id: str,
    params: dict[str, Any],
    api_key: str | None = None,
    base_url: str = "https://qveris.ai/api/v1",
) -> dict[str, Any]:
    """Execute via the global pool (api_key / base_url params kept for compat)."""
    return await get_key_pool().execute(tool_id, search_id, params)
