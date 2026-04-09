from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass
class HttpResult:
    ok: bool
    status_code: int | None
    data: Any | None
    error: str | None = None


class HttpClient:
    """HTTP client with practical SSL/403 handling for unstable public sources."""

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json,text/plain,*/*",
            }
        )

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> HttpResult:
        try:
            response = self.session.get(url, params=params, timeout=self.timeout, verify=True)
            response.raise_for_status()
            return HttpResult(ok=True, status_code=response.status_code, data=response.json())
        except requests.exceptions.SSLError:
            # Fallback useful in local/dev where certificate chain may break.
            try:
                response = self.session.get(url, params=params, timeout=self.timeout, verify=False)
                response.raise_for_status()
                return HttpResult(ok=True, status_code=response.status_code, data=response.json())
            except Exception as exc:  # pragma: no cover - defensive fallback
                return HttpResult(ok=False, status_code=None, data=None, error=f"SSL fallback failed: {exc}")
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            return HttpResult(ok=False, status_code=status, data=None, error=f"HTTP error: {exc}")
        except Exception as exc:
            return HttpResult(ok=False, status_code=None, data=None, error=str(exc))
