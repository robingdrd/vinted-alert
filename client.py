"""HTTP client for the Vinted public catalog API.

All requests are serialized. A minimum delay of 0.7s is enforced between
successive calls. Sessions are warmed up via GET / to collect the cookies the
catalog endpoint requires. On 401/403/419 the User-Agent is rotated and the
session is refreshed. 5xx and network errors trigger an exponential retry.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) "
    "Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) "
    "Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]

BASE_URL = "https://www.vinted.fr"
SEARCH_ENDPOINT = f"{BASE_URL}/api/v2/catalog/items"
MIN_REQUEST_INTERVAL_S = 0.7
RETRY_DELAYS_S = [0.5, 2.0, 8.0]
DEFAULT_TIMEOUT_S = 15


class VintedAPIError(Exception):
    """Raised by `search()` when the Vinted API can't be reached after retries."""


class VintedClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.user_agent = random.choice(USER_AGENTS)
        self._last_request_at: float = 0.0
        self._session_ready: bool = False

    def _api_headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Referer": f"{BASE_URL}/",
            "Origin": BASE_URL,
            "X-Requested-With": "XMLHttpRequest",
        }

    def _html_headers(self) -> dict:
        return {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }

    def _warm_up(self) -> None:
        logger.info("Initialisation de la session Vinted (GET /)")
        self.session.cookies.clear()
        self._respect_rate_limit()
        start = time.time()
        response = self.session.get(
            BASE_URL,
            headers=self._html_headers(),
            timeout=DEFAULT_TIMEOUT_S,
        )
        latency = time.time() - start
        self._last_request_at = time.time()
        logger.info(
            "GET %s status=%d latency=%.2fs cookies=%d",
            BASE_URL,
            response.status_code,
            latency,
            len(self.session.cookies),
        )
        response.raise_for_status()
        if not self.session.cookies:
            raise RuntimeError("Aucun cookie reçu de Vinted, session non utilisable")
        self._session_ready = True

    def _respect_rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_at
        if elapsed < MIN_REQUEST_INTERVAL_S:
            time.sleep(MIN_REQUEST_INTERVAL_S - elapsed)

    def _rotate_user_agent(self) -> None:
        candidates = [ua for ua in USER_AGENTS if ua != self.user_agent]
        self.user_agent = random.choice(candidates)
        logger.info("Rotation User-Agent effectuée")

    def search(
        self,
        query: str,
        price_max: Optional[float] = None,
        sizes: Optional[list[int]] = None,
        catalog_ids: Optional[list[int]] = None,
        per_page: int = 96,
        order: str = "newest_first",
        page: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "search_text": query,
            "per_page": per_page,
            "order": order,
        }
        if price_max is not None:
            params["price_to"] = price_max
        if sizes:
            params["size_ids"] = ",".join(str(s) for s in sizes)
        if catalog_ids:
            params["catalog_ids"] = ",".join(str(c) for c in catalog_ids)
        if page is not None:
            params["page"] = page

        payload = self._get_json(SEARCH_ENDPOINT, params)
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise RuntimeError("Réponse Vinted inattendue : 'items' n'est pas une liste")
        return items

    def _get_json(self, url: str, params: Optional[dict] = None) -> dict[str, Any]:
        if not self._session_ready:
            self._warm_up()

        last_error: Optional[Exception] = None
        for attempt in range(len(RETRY_DELAYS_S) + 1):
            self._respect_rate_limit()
            start = time.time()
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=self._api_headers(),
                    timeout=DEFAULT_TIMEOUT_S,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                latency = time.time() - start
                self._last_request_at = time.time()
                logger.warning("Erreur réseau sur %s (%.2fs) : %s", url, latency, exc)
                last_error = exc
                self._maybe_sleep_before_retry(attempt)
                continue

            latency = time.time() - start
            self._last_request_at = time.time()
            logger.info(
                "GET %s status=%d latency=%.2fs",
                response.url,
                response.status_code,
                latency,
            )

            if response.status_code == 404:
                raise VintedAPIError(f"404 sur {url}")

            if response.status_code in (401, 403, 419):
                logger.warning(
                    "Session expirée (status=%d), rotation UA + warm-up",
                    response.status_code,
                )
                self._rotate_user_agent()
                self._session_ready = False
                try:
                    self._warm_up()
                except Exception as exc:
                    last_error = exc
                    logger.warning("Warm-up échoué : %s", exc)
                else:
                    last_error = requests.HTTPError(f"Status {response.status_code}")
                self._maybe_sleep_before_retry(attempt)
                continue

            if response.status_code >= 500:
                last_error = requests.HTTPError(f"Status {response.status_code}")
                self._maybe_sleep_before_retry(attempt)
                continue

            response.raise_for_status()
            return response.json()

        raise VintedAPIError(
            f"Échec après {len(RETRY_DELAYS_S) + 1} tentatives sur {url}"
        ) from last_error

    def _maybe_sleep_before_retry(self, attempt: int) -> None:
        if attempt >= len(RETRY_DELAYS_S):
            return
        delay = RETRY_DELAYS_S[attempt]
        logger.info(
            "Retry dans %.1fs (tentative %d/%d)",
            delay,
            attempt + 2,
            len(RETRY_DELAYS_S) + 1,
        )
        time.sleep(delay)
