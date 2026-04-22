from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote_plus

from app.core.config import ALERTS_DATA_FILE, ALERTS_INDEX_FILE
from app.services.alerts_collector import ensure_alerts_dataset
from app.services.alerts_index import load_index

LOGGER = logging.getLogger(__name__)
GOOGLE_SEARCH_URL = 'https://www.google.com/search'


def _normalize_registro(value: str) -> str:
    return re.sub(r'\D', '', value or '')


def _clean(value: Any) -> str:
    text = str(value or '').strip()
    if not text or text in {'-', '--'}:
        return ''
    return text


def _build_alert_lookup_link(numero_alerta: str) -> str:
    cleaned = _clean(numero_alerta)
    if not cleaned:
        return ''
    query = quote_plus(f'alerta anvisa {cleaned}')
    return f'{GOOGLE_SEARCH_URL}?q={query}'


def _load_alerts_map() -> dict[str, dict[str, Any]]:
    if not ALERTS_DATA_FILE.exists():
        return {}

    try:
        payload = json.loads(ALERTS_DATA_FILE.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        LOGGER.warning('Falha ao carregar base local de alertas: %s', ALERTS_DATA_FILE)
        return {}

    if isinstance(payload, dict):
        rows = payload.get('alerts') if isinstance(payload.get('alerts'), list) else []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        number = _clean(row.get('numero_alerta'))
        if number:
            result[number] = row
    return result


def _normalize_alert_item(raw: dict[str, Any]) -> dict[str, Any]:
    numero_alerta = _clean(raw.get('numero_alerta') or raw.get('numero') or raw.get('alerta'))
    return {
        'numero_alerta': numero_alerta,
        'link_consulta': _build_alert_lookup_link(numero_alerta),
        'url': _clean(raw.get('url') or raw.get('link') or raw.get('fonte_url')),
        'titulo': _clean(raw.get('titulo') or raw.get('assunto') or raw.get('descricao')),
        'data': _clean(raw.get('data') or raw.get('data_publicacao')),
        'resumo': _clean(raw.get('resumo')),
        'identificacao_produto_ou_caso': _clean(raw.get('identificacao_produto_ou_caso')),
        'problema': _clean(raw.get('problema')),
        'acao': _clean(raw.get('acao')),
        'recomendacoes': _clean(raw.get('recomendacoes')),
        'empresa': _clean(raw.get('empresa') or raw.get('fabricante')),
        'nome_comercial': _clean(raw.get('nome_comercial') or raw.get('produto')),
        'nome_tecnico': _clean(raw.get('nome_tecnico')),
        'numero_registro_anvisa': _clean(raw.get('numero_registro_anvisa')),
        'modelo_afetado': _clean(raw.get('modelo_afetado') or raw.get('modelo')),
    }


def find_alerts_by_registration(registro: str) -> dict[str, Any]:
    normalized_registro = _normalize_registro(registro)
    sync = ensure_alerts_dataset()

    index = load_index(ALERTS_INDEX_FILE)
    alert_numbers = index.get('registro_anvisa', {}).get(normalized_registro, [])
    if not alert_numbers:
        return {
            'status': 'no_alerts_found',
            'count': 0,
            'alerts': [],
            'warning': sync.get('warning'),
            'sync': sync,
        }

    alerts_map = _load_alerts_map()
    alerts: list[dict[str, Any]] = []
    for number in alert_numbers:
        item = alerts_map.get(str(number))
        if item:
            alerts.append(_normalize_alert_item(item))

    alerts.sort(key=lambda item: int(item['numero_alerta']) if item.get('numero_alerta', '').isdigit() else -1, reverse=True)

    return {
        'status': 'alerts_found' if alerts else 'no_alerts_found',
        'count': len(alerts),
        'alerts': alerts,
        'warning': sync.get('warning'),
        'sync': sync,
    }
