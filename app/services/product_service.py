from __future__ import annotations

import re
from typing import Any

import requests

from app.core.config import ANVISA_PRODUCT_API_URL, REQUEST_TIMEOUT, SSL_VERIFY, USER_AGENT
from app.services.anvisa_auth import (
    AnvisaAuthError,
    MissingAnvisaCredentialsError,
    get_access_token,
    invalidate_cached_token,
)


class ProductLookupError(RuntimeError):
    def __init__(self, message: str, code: str = 'product_lookup_error') -> None:
        super().__init__(message)
        self.code = code


class ProductAuthenticationError(ProductLookupError):
    def __init__(self, message: str = 'Falha de autenticação na API oficial da Anvisa.') -> None:
        super().__init__(message, code='auth_error')


class ProductRateLimitError(ProductLookupError):
    def __init__(self, message: str = 'Limite de requisições excedido na API oficial da Anvisa.') -> None:
        super().__init__(message, code='rate_limit')


class ProductEmptyResponseError(ProductLookupError):
    def __init__(self, message: str = 'A API oficial da Anvisa retornou resposta vazia.') -> None:
        super().__init__(message, code='empty_response')


def _normalize_registration(value: str | None) -> str:
    return re.sub(r'\D', '', value or '')


def build_product_payload(registro: str) -> dict[str, Any]:
    return {
        'count': 10,
        'page': 1,
        'order': 'ASC',
        'sorting': {'nomeProduto': 'ASC'},
        'filter': {'numeroRegistro': _normalize_registration(registro)},
    }


def _extract_items(response_data: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ('content', 'items', 'data', 'result', 'results'):
        value = response_data.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
    return []


def _request_products(payload: dict[str, Any], token: str) -> dict[str, Any]:
    headers = {
        'Authorization': f'Bearer {token}',
        'User-Agent': USER_AGENT,
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }

    try:
        response = requests.post(
            ANVISA_PRODUCT_API_URL,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
            verify=SSL_VERIFY,
        )
    except requests.RequestException as exc:
        raise ProductLookupError(f'Falha temporária ao consultar API oficial da Anvisa: {exc}') from exc

    if response.status_code == 429:
        raise ProductRateLimitError()
    if response.status_code >= 500:
        raise ProductLookupError('Falha temporária na API oficial da Anvisa.')

    return {'status_code': response.status_code, 'response': response}


def call_official_product_api(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        token = get_access_token()
    except MissingAnvisaCredentialsError as exc:
        raise ProductAuthenticationError(str(exc)) from exc
    except AnvisaAuthError as exc:
        raise ProductAuthenticationError(str(exc)) from exc

    result = _request_products(payload, token)
    status_code = int(result['status_code'])
    response = result['response']

    if status_code in (401, 403):
        invalidate_cached_token()
        try:
            token = get_access_token(force_refresh=True)
        except AnvisaAuthError as exc:
            raise ProductAuthenticationError(str(exc)) from exc
        result = _request_products(payload, token)
        status_code = int(result['status_code'])
        response = result['response']

    if status_code in (401, 403):
        raise ProductAuthenticationError('Token inválido ou expirado para API oficial da Anvisa.')
    if status_code >= 400:
        raise ProductLookupError(f'Erro HTTP {status_code} na API oficial da Anvisa.')

    try:
        body = response.json()
    except ValueError as exc:
        raise ProductLookupError('Resposta inválida (não JSON) na API oficial da Anvisa.') from exc

    if body is None or body == {}:
        raise ProductEmptyResponseError()

    return body


def _get_nested(item: dict[str, Any], key: str) -> Any:
    value = item.get(key)
    if isinstance(value, dict):
        return value
    return {}


def normalize_product_response(response_data: dict[str, Any], registro: str) -> dict[str, Any] | None:
    items = _extract_items(response_data)
    if not items:
        return None

    normalized_registro = _normalize_registration(registro)
    selected = None
    for item in items:
        candidate = _normalize_registration(str(item.get('numeroRegistro') or ''))
        if candidate == normalized_registro:
            selected = item
            break

    item = selected or items[0]
    empresa = _get_nested(item, 'empresa')
    nome_tecnico = item.get('nomeTecnico')

    return {
        'numeroRegistro': str(item.get('numeroRegistro') or normalized_registro),
        'nomeProduto': str(item.get('nomeProduto') or '').strip(),
        'numeroProcesso': str(item.get('numeroProcesso') or '').strip(),
        'situacaoNotificacaoRegistro': str(item.get('situacaoNotificacaoRegistro') or '').strip(),
        'nomeTecnico': str(nome_tecnico or '').strip(),
        'empresa': {
            'razaoSocial': str(empresa.get('razaoSocial') or '').strip(),
            'cnpj': str(empresa.get('cnpj') or '').strip(),
        },
    }


def find_product_by_registration(registro: str) -> dict[str, Any] | None:
    payload = build_product_payload(registro)
    data = call_official_product_api(payload)
    return normalize_product_response(data, registro)
