from __future__ import annotations

import json
import re
from typing import Any

import requests

from app.core.config import ALERTS_BRUNOROMA_BASE_URL, ALERTS_DATA_FILE, ALERTS_INDEX_FILE, REQUEST_TIMEOUT, SSL_VERIFY
from app.services.alerts_collector import ensure_alerts_dataset
from app.services.alerts_index import load_index


def _normalize_registro(value: str) -> str:
    return re.sub(r'\D', '', value or '')


def _load_alerts() -> list[dict[str, Any]]:
    if not ALERTS_DATA_FILE.exists():
        return []
    try:
        payload = json.loads(ALERTS_DATA_FILE.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return []

    if isinstance(payload, dict):
        alerts = payload.get('alerts')
        return alerts if isinstance(alerts, list) else []
    return payload if isinstance(payload, list) else []


def _clean(value: Any) -> str:
    text = str(value or '').strip()
    if not text or text in {'-', '--'}:
        return ''
    return text


def _normalize_alert_item(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        'numero_alerta': _clean(raw.get('numero_alerta') or raw.get('numero') or raw.get('alerta')),
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


def _fetch_remote_alerts(registro: str) -> list[dict[str, Any]]:
    endpoint = f"{ALERTS_BRUNOROMA_BASE_URL}/{registro}"
    try:
        response = requests.get(endpoint, timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return []
    return _parse_alerts_payload(payload)


def find_alerts_by_registration(registro: str) -> dict[str, Any]:
    normalized_registro = _normalize_registro(registro)
    remote_alerts = _fetch_remote_alerts(normalized_registro)
    if remote_alerts:
        return {
            'status': 'alerts_found',
            'count': len(remote_alerts),
            'alerts': remote_alerts,
            'warning': None,
            'sync': {'status': 'remote_lookup'},
        }

    sync_info = ensure_alerts_dataset()
    alerts = _load_alerts()
    index = load_index(ALERTS_INDEX_FILE)

    matched_numbers = (index.get('registro_anvisa') or {}).get(normalized_registro, [])
    matched_set = {str(number).strip() for number in matched_numbers if str(number).strip()}

    matched_alerts = [
        item for item in alerts if str(item.get('numero_alerta') or '').strip() in matched_set
    ]

    return {
        'status': 'alerts_found' if matched_alerts else 'no_alerts_found',
        'count': len(matched_alerts),
        'alerts': matched_alerts,
        'warning': sync_info.get('warning'),
        'sync': sync_info,
    }
