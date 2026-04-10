from __future__ import annotations

import re
from typing import Any

import requests

from app.core.config import ANVISA_API_BASE_URL, ANVISA_API_TOKEN, REQUEST_TIMEOUT, SSL_VERIFY, USER_AGENT

PRODUCT_SEARCH_PATH = '/consulta/saude'


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
        'filter': {'numeroRegistro': _normalize_registration(registro)},
        'page': 1,
        'size': 10,
    }


def call_official_product_api(payload: dict[str, Any]) -> dict[str, Any]:
    if not ANVISA_API_TOKEN:
        raise ProductAuthenticationError(
            'Token da API da Anvisa não configurado. Defina ANVISA_API_TOKEN no ambiente.'
        )

    headers = {
        'Authorization': f'Bearer {ANVISA_API_TOKEN}',
        'User-Agent': USER_AGENT,
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }

    url = f"{ANVISA_API_BASE_URL.rstrip('/')}{PRODUCT_SEARCH_PATH}"

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
            verify=SSL_VERIFY,
        )
    except requests.RequestException as exc:
        raise ProductLookupError(f'Falha de rede ao consultar API oficial da Anvisa: {exc}') from exc

    if response.status_code in (401, 403):
        raise ProductAuthenticationError('Token inválido/expirado para API oficial da Anvisa.')
    if response.status_code == 429:
        raise ProductRateLimitError()
    if response.status_code >= 400:
        raise ProductLookupError(f'Erro HTTP {response.status_code} na API oficial da Anvisa.')

    try:
        body = response.json()
    except ValueError as exc:
        raise ProductLookupError('Resposta inválida (não JSON) na API oficial da Anvisa.') from exc

    if body is None or body == {}:
        raise ProductEmptyResponseError()

    return body


def _first_item(response_data: dict[str, Any]) -> dict[str, Any] | None:
    for key in ('content', 'items', 'data', 'result', 'results'):
        value = response_data.get(key)
        if isinstance(value, list) and value:
            if isinstance(value[0], dict):
                return value[0]
            return None

    # Alguns endpoints podem devolver diretamente um objeto do produto.
    if any(k in response_data for k in ('numeroRegistro', 'nomeProduto', 'processo')):
        return response_data
    return None


def normalize_product_response(response_data: dict[str, Any], registro: str) -> dict[str, Any] | None:
    item = _first_item(response_data)
    if not item:
        return None

    def pick(*keys: str) -> str:
        for key in keys:
            value = item.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ''

    return {
        'registro_anvisa': pick('numeroRegistro', 'registro', 'cadastro') or _normalize_registration(registro),
        'nome_produto': pick('nomeProduto', 'produto', 'nomeComercial'),
        'marca': pick('marca', 'nomeMarca'),
        'modelo': pick('modelo', 'nomeModelo'),
        'fabricante': pick('fabricante', 'razaoSocialFabricante'),
        'detentor_registro': pick('detentorRegistro', 'razaoSocialDetentorRegistro'),
        'pais_fabricacao': pick('paisFabricacao', 'nomePaisFabricacao'),
        'situacao': pick('situacao', 'situacaoRegistro'),
        'processo': pick('numeroProcesso', 'processo'),
        'classificacao_risco': pick('classeRisco', 'classificacaoRisco'),
    }


def find_product_by_registration(registro: str) -> dict[str, Any] | None:
    payload = build_product_payload(registro)
    data = call_official_product_api(payload)
    return normalize_product_response(data, registro)
