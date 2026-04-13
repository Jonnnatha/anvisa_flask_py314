from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

import requests

from app.core.config import ALERTS_BRUNOROMA_BASE_URL, ALERTS_REQUEST_TIMEOUT, SSL_VERIFY

LOGGER = logging.getLogger(__name__)
GOOGLE_SEARCH_URL = 'https://www.google.com/search'


def _normalize_registro(value: str) -> str:
    return re.sub(r'\D', '', value or '')


def _clean(value: Any) -> str:
    text = str(value or '').strip()
    if not text or text in {'-', '--'}:
        return ''
    return text


def _normalize_alert_item(raw: dict[str, Any]) -> dict[str, Any]:
    numero_alerta = _clean(raw.get('numero_alerta') or raw.get('numero') or raw.get('alerta'))
    return {
        'numero_alerta': numero_alerta,
        'link_consulta': _build_alert_lookup_link(numero_alerta),
        'url': _clean(raw.get('url') or raw.get('link') or raw.get('fonte_url')),
        'titulo': _clean(raw.get('titulo') or raw.get('assunto') or raw.get('descricao')),
        'data': _clean(raw.get('data') or raw.get('data_publicacao')),
        'resumo': _clean(raw.get('resumo')),
        'empresa': _clean(raw.get('empresa') or raw.get('fabricante')),
        'marca': _clean(raw.get('marca')),
        'modelo_afetado': _clean(raw.get('modelo_afetado') or raw.get('modelo')),
        'nome_comercial': _clean(raw.get('nome_comercial') or raw.get('produto')),
        'nome_tecnico': _clean(raw.get('nome_tecnico')),
    }


def _build_alert_lookup_link(numero_alerta: str) -> str:
    cleaned = _clean(numero_alerta)
    if not cleaned:
        return ''
    query = quote_plus(f'alerta anvisa {cleaned}')
    return f'{GOOGLE_SEARCH_URL}?q={query}'


def _parse_alerts_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ('alertas', 'alerts', 'items', 'resultados', 'data'):
            value = payload.get(key)
            if isinstance(value, list):
                payload = value
                break
        else:
            payload = [payload]

    if not isinstance(payload, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        row = _normalize_alert_item(item)
        if row.get('numero_alerta'):
            normalized.append(row)
    return normalized


def _parse_alert_numbers_from_text(payload: str) -> list[dict[str, Any]]:
    if not payload:
        return []
    numbers = re.findall(r'\b\d{3,6}\b', payload)
    unique_numbers: list[str] = []
    seen: set[str] = set()
    for number in numbers:
        key = number.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique_numbers.append(key)
    return [
        {
            'numero_alerta': number,
            'link_consulta': _build_alert_lookup_link(number),
        }
        for number in unique_numbers
    ]


def _fetch_remote_alerts(registro: str) -> list[dict[str, Any]]:
    endpoint = f"{ALERTS_BRUNOROMA_BASE_URL}/{registro}"
    try:
        response = requests.get(endpoint, timeout=ALERTS_REQUEST_TIMEOUT, verify=SSL_VERIFY)
        response.raise_for_status()
    except requests.RequestException as exc:
        LOGGER.warning('Falha ao consultar alertas remotos para registro %s: %s', registro, exc)
        return []

    try:
        payload = response.json()
        parsed = _parse_alerts_payload(payload)
        if parsed:
            return parsed
    except ValueError:
        parsed = []

    text_payload = response.text or ''
    if parsed:
        return parsed
    return _parse_alert_numbers_from_text(text_payload)


def find_alerts_by_registration(registro: str) -> dict[str, Any]:
    normalized_registro = _normalize_registro(registro)
    remote_alerts = _fetch_remote_alerts(normalized_registro)
    return {
        'status': 'alerts_found' if remote_alerts else 'no_alerts_found',
        'count': len(remote_alerts),
        'alerts': remote_alerts,
        'warning': None,
        'sync': {'status': 'remote_lookup'},
    }
