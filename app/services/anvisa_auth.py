from __future__ import annotations

import threading
import time
from typing import Any

import requests

from app.core.config import (
    ANVISA_AUTH_CLIENT_ID,
    ANVISA_AUTH_CLIENT_SECRET,
    ANVISA_AUTH_SCOPE,
    ANVISA_AUTH_TOKEN_URL,
    REQUEST_TIMEOUT,
    SSL_VERIFY,
    USER_AGENT,
)


class AnvisaAuthError(RuntimeError):
    def __init__(self, message: str, code: str = 'auth_error') -> None:
        super().__init__(message)
        self.code = code


class MissingAnvisaCredentialsError(AnvisaAuthError):
    def __init__(self) -> None:
        super().__init__('Credenciais da API da Anvisa ausentes. Configure client_id e client_secret.', 'missing_credentials')


class AnvisaTokenRequestError(AnvisaAuthError):
    def __init__(self, message: str = 'Falha ao obter token de acesso da API da Anvisa.') -> None:
        super().__init__(message, 'token_request_failed')


_token_cache: dict[str, Any] = {
    'access_token': None,
    'expires_at': 0.0,
}
_cache_lock = threading.Lock()


# Cache em memória com janela de segurança para evitar uso de token quase expirado.
def _token_is_valid() -> bool:
    token = _token_cache.get('access_token')
    expires_at = float(_token_cache.get('expires_at', 0.0) or 0.0)
    return bool(token) and time.time() < expires_at


# OAuth2 Client Credentials no endpoint oficial da Anvisa.
def _request_new_token() -> tuple[str, int]:
    if not ANVISA_AUTH_CLIENT_ID or not ANVISA_AUTH_CLIENT_SECRET:
        raise MissingAnvisaCredentialsError()

    payload = {
        'grant_type': 'client_credentials',
        'client_id': ANVISA_AUTH_CLIENT_ID,
        'client_secret': ANVISA_AUTH_CLIENT_SECRET,
        'scope': ANVISA_AUTH_SCOPE,
    }

    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
    }

    try:
        response = requests.post(
            ANVISA_AUTH_TOKEN_URL,
            data=payload,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            verify=SSL_VERIFY,
        )
    except requests.RequestException as exc:
        raise AnvisaTokenRequestError(f'Falha temporária ao autenticar na API da Anvisa: {exc}') from exc

    if response.status_code >= 500:
        raise AnvisaTokenRequestError('Serviço de autenticação da Anvisa indisponível temporariamente.')
    if response.status_code in (401, 403):
        raise AnvisaTokenRequestError('Credenciais inválidas para autenticação na API da Anvisa.')
    if response.status_code >= 400:
        raise AnvisaTokenRequestError(f'Erro HTTP {response.status_code} ao solicitar token na API da Anvisa.')

    try:
        body = response.json()
    except ValueError as exc:
        raise AnvisaTokenRequestError('Resposta inválida ao solicitar token da API da Anvisa.') from exc

    token = str(body.get('access_token', '')).strip()
    expires_in = int(body.get('expires_in', 0) or 0)

    if not token or expires_in <= 0:
        raise AnvisaTokenRequestError('Resposta de token incompleta: access_token/expires_in ausentes.')

    return token, expires_in


def invalidate_cached_token() -> None:
    with _cache_lock:
        _token_cache['access_token'] = None
        _token_cache['expires_at'] = 0.0


def get_access_token(force_refresh: bool = False) -> str:
    with _cache_lock:
        if not force_refresh and _token_is_valid():
            return str(_token_cache['access_token'])

        token, expires_in = _request_new_token()
        # Renova antes do prazo final para reduzir risco de 401 por expiração de borda.
        safety_margin = min(30, max(5, int(expires_in * 0.1)))
        _token_cache['access_token'] = token
        _token_cache['expires_at'] = time.time() + max(1, expires_in - safety_margin)
        return token
