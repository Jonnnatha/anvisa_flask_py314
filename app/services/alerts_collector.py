from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from app.core.config import (
    ALERTS_DATA_FILE,
    ALERTS_DATA_TTL_HOURS,
    ALERTS_INDEX_FILE,
    ALERTS_MAX_PAGES,
    ALERTS_PAGE_URL,
    REQUEST_TIMEOUT,
    SSL_VERIFY,
    USER_AGENT,
)
from app.services.alerts_index import build_alerts_index, save_index
from app.services.alerts_parser import parse_alert_detail, parse_alert_list_item


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def _load_existing_alerts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return []

    if isinstance(data, dict):
        alerts = data.get('alerts')
        return alerts if isinstance(alerts, list) else []
    return data if isinstance(data, list) else []


def _save_alerts(path: Path, alerts: list[dict[str, Any]]) -> None:
    payload = {
        'updated_at': _iso_now(),
        'count': len(alerts),
        'alerts': alerts,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _is_fresh(path: Path, ttl_hours: int) -> bool:
    if not path.exists():
        return False

    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return False

    timestamp = _parse_dt((data or {}).get('updated_at')) if isinstance(data, dict) else None
    if not timestamp:
        return False

    return datetime.now(tz=timezone.utc) - timestamp < timedelta(hours=ttl_hours)


def _merge_alerts(existing: list[dict[str, Any]], discovered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged_map = {str(item.get('numero_alerta') or ''): item for item in existing}
    for item in discovered:
        merged_map[str(item.get('numero_alerta') or '')] = item

    def sort_key(record: tuple[str, dict[str, Any]]) -> int:
        number = record[0]
        return int(number) if number.isdigit() else -1

    return [item for _, item in sorted(merged_map.items(), key=sort_key, reverse=True)]


def collect_and_index_alerts(max_pages: int | None = None) -> dict[str, Any]:
    existing = _load_existing_alerts(ALERTS_DATA_FILE)
    existing_numbers = {str(item.get('numero_alerta') or '') for item in existing}
    latest_known = max(existing_numbers, key=lambda x: int(x) if x.isdigit() else -1) if existing_numbers else ''

    headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }

    max_page_limit = max_pages or ALERTS_MAX_PAGES
    discovered: list[dict[str, Any]] = []
    stop_scan = False

    with requests.Session() as session:
        session.headers.update(headers)

        for page_number in range(1, max_page_limit + 1):
            if stop_scan:
                break

            list_url = f'{ALERTS_PAGE_URL}?pagina={page_number}'
            response = session.get(list_url, timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            cards = soup.find_all('div', class_='row-fluid lista-noticias')

            if not cards:
                break

            for card in cards:
                item = parse_alert_list_item(card)
                if not item:
                    continue

                number = item['numero_alerta']
                if latest_known and number == latest_known:
                    stop_scan = True
                    break
                if number in existing_numbers:
                    continue

                detail_response = session.get(item['url'], timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY)
                detail_response.raise_for_status()
                detail = parse_alert_detail(detail_response.text, item['url'])
                if not detail:
                    continue

                alert = {
                    'numero_alerta': number,
                    'data': item['data'],
                    'url': item['url'],
                    'resumo': detail.get('resumo', ''),
                    'identificacao_produto_ou_caso': detail.get('identificacao_produto_ou_caso', ''),
                    'problema': detail.get('problema', ''),
                    'acao': detail.get('acao', ''),
                    'referencias': detail.get('referencias', ''),
                    'historico': detail.get('historico', ''),
                    'recomendacoes': detail.get('recomendacoes', ''),
                    'informacoes_complementares': detail.get('informacoes_complementares', ''),
                    'empresa': detail.get('empresa', ''),
                    'nome_comercial': detail.get('nome_comercial', ''),
                    'nome_tecnico': detail.get('nome_tecnico', ''),
                    'numero_registro_anvisa': detail.get('numero_registro_anvisa', ''),
                    'tipo_produto': detail.get('tipo_produto', ''),
                    'classe_risco': detail.get('classe_risco', ''),
                    'modelo_afetado': detail.get('modelo_afetado', ''),
                    'numeros_serie_afetados': detail.get('numeros_serie_afetados', ''),
                }
                discovered.append(alert)

    merged = _merge_alerts(existing, discovered)
    _save_alerts(ALERTS_DATA_FILE, merged)
    save_index(ALERTS_INDEX_FILE, build_alerts_index(merged))

    return {
        'updated_at': _iso_now(),
        'new_alerts': len(discovered),
        'total_alerts': len(merged),
        'status': 'updated',
    }


def ensure_alerts_dataset() -> dict[str, Any]:
    if _is_fresh(ALERTS_DATA_FILE, ALERTS_DATA_TTL_HOURS):
        return {
            'status': 'fresh_cache',
            'updated_at': _iso_now(),
            'new_alerts': 0,
            'total_alerts': len(_load_existing_alerts(ALERTS_DATA_FILE)),
        }

    try:
        return collect_and_index_alerts()
    except requests.RequestException as exc:
        total = len(_load_existing_alerts(ALERTS_DATA_FILE))
        warning = (
            'Não foi possível atualizar a coleta automática de alertas (possível bloqueio de origem da Anvisa). '
            f'Base local existente foi mantida. Detalhe: {exc}'
        )
        return {
            'status': 'collector_error',
            'warning': warning,
            'new_alerts': 0,
            'total_alerts': total,
            'updated_at': _iso_now(),
        }
