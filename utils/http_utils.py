import time
import threading
from typing import Optional
from curl_cffi import requests as curl_requests
from curl_cffi.requests.exceptions import HTTPError


class RateLimiter:
    def __init__(self, max_requests: int, period_seconds: float):
        self._min_interval = period_seconds / max_requests
        self._last_request = 0.0
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()


class HttpClient:
    """HTTP client that impersonates Chrome to bypass Cloudflare.

    IMPORTANT: Do NOT override the User-Agent header when using impersonation.
    curl_cffi sets the correct UA based on the impersonation target.
    """

    DEFAULT_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    def __init__(
        self,
        impersonate: str = "chrome124",
        timeout: int = 30,
        max_retries: int = 8,
    ):
        self._impersonate = impersonate
        self._timeout = timeout
        self._max_retries = max_retries
        self._session: Optional[curl_requests.Session] = None

    @property
    def session(self) -> curl_requests.Session:
        if self._session is None:
            self._session = curl_requests.Session(impersonate=self._impersonate)
        return self._session

    def _make_headers(self, extra: Optional[dict] = None) -> dict:
        headers = dict(self.DEFAULT_HEADERS)
        if extra:
            headers.update(extra)
        return headers

    def get(self, url: str, headers: Optional[dict] = None) -> str:
        all_headers = self._make_headers(headers)
        last_exc = None

        for attempt in range(self._max_retries):
            try:
                resp = self.session.get(
                    url,
                    headers=all_headers,
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                text = resp.text

                if "Cloudflare to restrict access" in text or \
                   "503 Service Temporarily Unavailable" in text:
                    print(f"  [retry] Cloudflare block detected, waiting 15s...")
                    time.sleep(15)
                    continue

                return text

            except HTTPError as e:
                last_exc = e
                if attempt < self._max_retries - 1:
                    wait = 3 if e.status_code == 429 else 2 ** attempt
                    print(f"  [retry] HTTP {e.status_code} ({url.split('/')[-1]}), waiting {wait}s...")
                    time.sleep(wait)
            except Exception as e:
                last_exc = e
                if attempt < self._max_retries - 1:
                    wait = 2 ** attempt
                    print(f"  [retry] {e}, waiting {wait}s...")
                    time.sleep(wait)

        raise last_exc or RuntimeError(f"Failed to fetch {url}")

    def get_bytes(self, url: str, headers: Optional[dict] = None) -> bytes:
        all_headers = self._make_headers(headers)

        for attempt in range(self._max_retries):
            try:
                resp = self.session.get(
                    url,
                    headers=all_headers,
                    timeout=self._timeout,
                )
                resp.raise_for_status()
                return resp.content
            except Exception as e:
                if attempt < self._max_retries - 1:
                    wait = 2 ** attempt
                    time.sleep(wait)

        raise RuntimeError(f"Failed to fetch {url}")

    def get_js(self, url: str) -> str:
        headers = self._make_headers({
            "Accept": "*/*",
            "Referer": "https://www.linovelib.com/",
        })
        return self.get(url, headers=headers)


_http: Optional[HttpClient] = None


def get_http() -> HttpClient:
    global _http
    if _http is None:
        _http = HttpClient()
    return _http
