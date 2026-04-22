from __future__ import annotations

import json
import logging
import re
from datetime import datetime
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


def _parse_date_br(value: str) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], '%d/%m/%Y')
    except ValueError:
        return None


def _normalize_text_filter(value: str) -> str:
    return _clean(value).casefold()


def search_alerts(
    *,
    fabricante: str = '',
    registro: str = '',
    nome_comercial: str = '',
    nome_tecnico: str = '',
    data_inicio: str = '',
    data_fim: str = '',
) -> dict[str, Any]:
    sync = ensure_alerts_dataset()
    alerts = [_normalize_alert_item(item) for item in _load_alerts_map().values()]

    fabricante_q = _normalize_text_filter(fabricante)
    registro_q = _normalize_registro(registro)
    nome_comercial_q = _normalize_text_filter(nome_comercial)
    nome_tecnico_q = _normalize_text_filter(nome_tecnico)
    inicio = _parse_date_br(data_inicio)
    fim = _parse_date_br(data_fim)

    filtered: list[dict[str, Any]] = []
    for alert in alerts:
        if fabricante_q and fabricante_q not in _normalize_text_filter(alert.get('empresa', '')):
            continue
        if registro_q and registro_q not in _normalize_registro(alert.get('numero_registro_anvisa', '')):
            continue
        if nome_comercial_q and nome_comercial_q not in _normalize_text_filter(alert.get('nome_comercial', '')):
            continue
        if nome_tecnico_q and nome_tecnico_q not in _normalize_text_filter(alert.get('nome_tecnico', '')):
            continue

        alert_date = _parse_date_br(str(alert.get('data', '')))
        if inicio and (not alert_date or alert_date < inicio):
            continue
        if fim and (not alert_date or alert_date > fim):
            continue

        filtered.append(alert)

    filtered.sort(key=lambda item: int(item['numero_alerta']) if item.get('numero_alerta', '').isdigit() else -1, reverse=True)
    return {
        'status': 'ok',
        'count': len(filtered),
        'alerts': filtered,
        'sync': sync,
    }


def summarize_alerts(
    *,
    periodo: str = 'diario',
    referencia: str = '',
    registros_base: list[str] | None = None,
) -> dict[str, Any]:
    normalized_period = (periodo or 'diario').strip().lower()
    if normalized_period not in {'diario', 'mensal'}:
        raise ValueError("periodo deve ser 'diario' ou 'mensal'.")

    if referencia:
        try:
            ref = datetime.strptime(referencia, '%Y-%m-%d')
        except ValueError as exc:
            raise ValueError('referencia deve estar no formato YYYY-MM-DD.') from exc
    else:
        ref = datetime.now()

    sync = ensure_alerts_dataset()
    alerts = [_normalize_alert_item(item) for item in _load_alerts_map().values()]

    selected: list[dict[str, Any]] = []
    for alert in alerts:
        dt = _parse_date_br(str(alert.get('data', '')))
        if not dt:
            continue
        if normalized_period == 'diario' and dt.date() == ref.date():
            selected.append(alert)
        if normalized_period == 'mensal' and dt.year == ref.year and dt.month == ref.month:
            selected.append(alert)

    selected.sort(key=lambda item: int(item['numero_alerta']) if item.get('numero_alerta', '').isdigit() else -1, reverse=True)

    registros_set = {_normalize_registro(item) for item in (registros_base or []) if _normalize_registro(item)}
    matched: list[dict[str, Any]] = []
    if registros_set:
        for alert in selected:
            registro_alerta = _normalize_registro(alert.get('numero_registro_anvisa', ''))
            if registro_alerta and registro_alerta in registros_set:
                matched.append(alert)

    return {
        'status': 'ok',
        'periodo': normalized_period,
        'referencia': ref.strftime('%Y-%m-%d'),
        'total_alertas_periodo': len(selected),
        'total_alertas_com_registro_da_base': len(matched),
        'alertas': selected,
        'alertas_registros_base': matched,
        'sync': sync,
    }
