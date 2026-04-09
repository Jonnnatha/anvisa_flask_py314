from __future__ import annotations

from typing import Any

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.config import REQUEST_TIMEOUT, SSL_VERIFY, USER_AGENT

if not SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_HEADERS = {
    'User-Agent': USER_AGENT,
    'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
}


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    retry = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({'GET', 'HEAD'}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session


def get(url: str, params: dict[str, Any] | None = None, timeout: int | None = None) -> requests.Response:
    session = _build_session()
    response = session.get(
        url,
        params=params,
        timeout=timeout or REQUEST_TIMEOUT,
        verify=SSL_VERIFY,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response
