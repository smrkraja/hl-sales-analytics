"""Small HTTP helper with retry/backoff shared by all fetchers."""
import time

import requests


def get_with_retry(url: str, params: dict | None = None, *, attempts: int = 4,
                   timeout: int = 60, stream: bool = False) -> requests.Response:
    """GET with exponential backoff on 429/5xx and connection errors."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            # Default requests User-Agent on purpose: FRED tarpits custom UAs.
            response = requests.get(url, params=params, timeout=timeout, stream=stream)
            if response.status_code == 429 or response.status_code >= 500:
                last_error = requests.HTTPError(f"{response.status_code} from {url}")
            else:
                response.raise_for_status()
                return response
        except (requests.ConnectionError, requests.Timeout) as error:
            last_error = error
        time.sleep(2 ** attempt)
    raise last_error or RuntimeError(f"Failed to fetch {url}")
