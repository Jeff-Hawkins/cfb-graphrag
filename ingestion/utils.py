"""Shared helpers for CFBD API ingestion: session setup, rate limiting, retry logic."""

import time
import logging
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)

CFBD_BASE_URL = "https://api.collegefootballdata.com"
_DEFAULT_RATE_LIMIT_DELAY = 0.25  # seconds between requests (free tier: ~10 req/s)


def build_session(api_key: str) -> requests.Session:
    """Create a requests.Session pre-configured with the CFBD bearer token.

    Args:
        api_key: CFBD API key from https://collegefootballdata.com/key.

    Returns:
        A requests.Session with Authorization header set.
    """
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }
    )
    return session


@retry(
    retry=retry_if_exception_type(requests.HTTPError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
def get_json(
    session: requests.Session,
    endpoint: str,
    params: dict[str, Any] | None = None,
    rate_limit_delay: float = _DEFAULT_RATE_LIMIT_DELAY,
) -> Any:
    """Make a GET request to a CFBD endpoint and return parsed JSON.

    Retries up to 3 times on HTTP errors with exponential back-off.
    Applies a small delay after each request to respect the free-tier rate limit.

    Args:
        session: A requests.Session with Authorization header already set.
        endpoint: Path relative to CFBD_BASE_URL (e.g. ``"/teams"``).
        params: Optional query parameters dict.
        rate_limit_delay: Seconds to sleep after the request (default 0.25).

    Returns:
        Parsed JSON response (list or dict).

    Raises:
        requests.HTTPError: If the server returns a 4xx/5xx after all retries.
    """
    url = f"{CFBD_BASE_URL}{endpoint}"
    logger.debug("GET %s params=%s", url, params)
    response = session.get(url, params=params, timeout=30)
    response.raise_for_status()
    time.sleep(rate_limit_delay)
    return response.json()
