from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

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

ALERT_NUMBER_RE = re.compile(r'\b(\d{3,6})\b')
FIELD_MAP = {
    'resumo': 'resumo',
    'identificação do produto ou caso': 'identificacao_produto_ou_caso',
    'identificacao do produto ou caso': 'identificacao_produto_ou_caso',
    'problema': 'problema',
    'ação': 'acao',
    'acao': 'acao',
    'recomendações': 'recomendacoes',
    'recomendacoes': 'recomendacoes',
}
PRODUCT_KEYS = [
    ('nome comercial', 'nome_comercial'),
    ('nome técnico', 'nome_tecnico'),
    ('nome tecnico', 'nome_tecnico'),
    ('número de registro anvisa', 'numero_registro_anvisa'),
    ('numero de registro anvisa', 'numero_registro_anvisa'),
    ('tipo de produto', 'tipo_produto'),
    ('classe de risco', 'classe_risco'),
    ('modelo afetado', 'modelo_afetado'),
    ('números de série afetados', 'numeros_serie_afetados'),
    ('numeros de serie afetados', 'numeros_serie_afetados'),
]


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def _norm_heading(text: str) -> str:
    clean = re.sub(r'[:;.!@#$%^&*()_+=<>?/\\\-\d]+', '', text or '').strip().lower()
    return ' '.join(clean.split())


def _extract_alert_number(text: str) -> str:
    match = ALERT_NUMBER_RE.search(text or '')
    return match.group(1) if match else ''


def _extract_date(raw: str) -> str:
    match = re.search(r'(\d{2}/\d{2}/\d{4})', raw or '')
    return match.group(1) if match else ''


def _first_text(node: Any, selector: str) -> str:
    found = node.select_one(selector)
    return found.get_text(' ', strip=True) if found else ''


def _parse_product_identification_block(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    block = text or ''
    block_l = block.casefold()

    for idx, (key, target) in enumerate(PRODUCT_KEYS):
        pos = block_l.find(key)
        if pos < 0:
            continue

        start = pos + len(key)
        while start < len(block) and block[start] in ': -\t\n':
            start += 1

        end = len(block)
        for next_key, _ in PRODUCT_KEYS[idx + 1 :]:
            next_pos = block_l.find(next_key, start)
            if next_pos >= 0:
                end = min(end, next_pos)

        value = block[start:end].strip().strip('.')
        if value:
            result[target] = value

    return result


def _extract_company(parsed: dict[str, str]) -> str:
    for key in ('resumo', 'acao'):
        text = parsed.get(key, '')
        match = re.search(r'empresa\s+(.+?)(?:\s+-|\.|$)', text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ''


def _parse_alert_detail(url: str, session: requests.Session) -> dict[str, Any] | None:
    response = session.get(url, timeout=REQUEST_TIMEOUT, verify=SSL_VERIFY)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    container = soup.find('div', class_='bodyModel')
    if not container:
        return None

    parsed: dict[str, str] = {}
    current_key = ''

    for element in container.find_all(['h4', 'p', 'a']):
        if element.name == 'h4':
            heading = _norm_heading(element.get_text(' ', strip=True))
            current_key = FIELD_MAP.get(heading, heading.replace(' ', '_'))
            continue

        if not current_key:
            continue

        text = element.get_text(' ', strip=True)
        anchors = element.find_all('a', href=True)

        if anchors:
            refs = []
            for anchor in anchors:
                href = urljoin(ALERTS_PAGE_URL, anchor['href'])
                refs.append(f"{anchor.get_text(' ', strip=True)} => ({href})")
            text = ' '.join(refs)

        if not text:
            continue

        parsed[current_key] = f"{parsed[current_key]} {text}".strip() if parsed.get(current_key) else text

    ident = parsed.get('identificacao_produto_ou_caso', '')
    parsed.update(_parse_product_identification_block(ident))

    company = _extract_company(parsed)
    if company:
        parsed['empresa'] = company

    return parsed


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
                title = _first_text(card, 'p.titulo')
                number = _extract_alert_number(title)
                if not number:
                    continue

                if latest_known and number == latest_known:
                    stop_scan = True
                    break

                if number in existing_numbers:
                    continue

                date_text = _first_text(card, 'div.span3.data-hora')
                link_node = card.find('a', href=True)
                if not link_node:
                    continue

                detail_url = urljoin(ALERTS_PAGE_URL, link_node['href'])
                detail = _parse_alert_detail(detail_url, session)
                if not detail:
                    continue

                alert = {
                    'numero_alerta': number,
                    'data': _extract_date(date_text),
                    'url': detail_url,
                    'resumo': detail.get('resumo', ''),
                    'identificacao_produto_ou_caso': detail.get('identificacao_produto_ou_caso', ''),
                    'problema': detail.get('problema', ''),
                    'acao': detail.get('acao', ''),
                    'recomendacoes': detail.get('recomendacoes', ''),
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

    merged_map = {str(item.get('numero_alerta') or ''): item for item in existing}
    for item in discovered:
        merged_map[str(item.get('numero_alerta') or '')] = item

    merged = [item for _, item in sorted(merged_map.items(), key=lambda x: x[0], reverse=True)]

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
        return {
            'status': 'collector_error',
            'warning': f'Falha ao atualizar base local de alertas: {exc}',
            'new_alerts': 0,
            'total_alerts': len(_load_existing_alerts(ALERTS_DATA_FILE)),
            'updated_at': _iso_now(),
        }
