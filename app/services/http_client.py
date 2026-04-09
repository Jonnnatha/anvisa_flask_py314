from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import settings


@dataclass
class HttpResult:
    ok: bool
    status_code: int | None
    data: Any | None
    error: str | None = None
    url: str | None = None


class HttpClient:
    """Cliente HTTP com tratamento pragmático para SSL/403 em fontes públicas instáveis."""

    def __init__(
        self,
        timeout: int | None = None,
        verify_ssl: bool | None = None,
        allow_insecure_ssl_fallback: bool | None = None,
    ) -> None:
        self.timeout = timeout if timeout is not None else settings.REQUEST_TIMEOUT_SECONDS
        self.verify_ssl = settings.VERIFY_SSL if verify_ssl is None else verify_ssl
        self.allow_insecure_ssl_fallback = (
            settings.ALLOW_INSECURE_SSL_FALLBACK
            if allow_insecure_ssl_fallback is None
            else allow_insecure_ssl_fallback
        )
        import requests

        self._requests = requests
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
            }
        )

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> HttpResult:
        try:
            return self._request_json(url=url, params=params, verify=self.verify_ssl)
        except self._requests.exceptions.SSLError as exc:
            if not self.allow_insecure_ssl_fallback:
                return HttpResult(ok=False, status_code=None, data=None, error=f"SSL error: {exc}", url=url)
            try:
                return self._request_json(url=url, params=params, verify=False)
            except Exception as fallback_exc:  # pragma: no cover
                return HttpResult(
                    ok=False,
                    status_code=None,
                    data=None,
                    error=f"SSL fallback failed: {fallback_exc}",
                    url=url,
                )
        except self._requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            return HttpResult(ok=False, status_code=status, data=None, error=f"HTTP error: {exc}", url=url)
        except Exception as exc:
            return HttpResult(ok=False, status_code=None, data=None, error=str(exc), url=url)

    def _request_json(self, url: str, params: dict[str, Any] | None, verify: bool) -> HttpResult:
        response = self.session.get(url, params=params, timeout=self.timeout, verify=verify)
        response.raise_for_status()
        return HttpResult(ok=True, status_code=response.status_code, data=response.json(), url=response.url)
