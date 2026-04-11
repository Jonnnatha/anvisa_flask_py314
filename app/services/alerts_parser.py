from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.core.config import ALERTS_PAGE_URL

ALERT_NUMBER_RE = re.compile(r'\b(\d{3,6})\b')
DATE_RE = re.compile(r'(\d{2}/\d{2}/\d{4})')

FIELD_MAP = {
    'resumo': 'resumo',
    'identificação do produto ou caso': 'identificacao_produto_ou_caso',
    'identificacao do produto ou caso': 'identificacao_produto_ou_caso',
    'problema': 'problema',
    'ação': 'acao',
    'acao': 'acao',
    'referências': 'referencias',
    'referencias': 'referencias',
    'histórico': 'historico',
    'historico': 'historico',
    'recomendações': 'recomendacoes',
    'recomendacoes': 'recomendacoes',
    'informações complementares': 'informacoes_complementares',
    'informacoes complementares': 'informacoes_complementares',
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


def _norm_heading(text: str) -> str:
    normalized = re.sub(r'[:;.!@#$%^&*()_+=<>?/\\\-\d]+', ' ', text or '').strip().lower()
    return ' '.join(normalized.split())


def _normalize_text(value: Any) -> str:
    text = str(value or '').strip()
    if text in {'-', '--', 'N/A', 'n/a'}:
        return ''
    return text


def parse_alert_list_item(card: Any) -> dict[str, str] | None:
    title = _normalize_text(card.select_one('p.titulo').get_text(' ', strip=True) if card.select_one('p.titulo') else '')
    number_match = ALERT_NUMBER_RE.search(title)
    if not number_match:
        return None

    date_text = _normalize_text(
        card.select_one('div.span3.data-hora').get_text(' ', strip=True)
        if card.select_one('div.span3.data-hora')
        else ''
    )
    date_match = DATE_RE.search(date_text)

    link_node = card.find('a', href=True)
    if not link_node:
        return None

    return {
        'numero_alerta': number_match.group(1),
        'data': date_match.group(1) if date_match else '',
        'url': urljoin(ALERTS_PAGE_URL, link_node['href']),
    }


def _parse_product_identification_block(text: str) -> dict[str, str]:
    block = text or ''
    block_l = block.casefold()
    result: dict[str, str] = {}

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

        value = _normalize_text(block[start:end].strip().strip('.'))
        if value:
            result[target] = value

    return result


def _extract_company(parsed: dict[str, str]) -> str:
    for key in ('resumo', 'acao', 'informacoes_complementares'):
        match = re.search(
            r'empresa\s+(.+?)(?:\s+-|\.|$)',
            parsed.get(key, ''),
            flags=re.IGNORECASE,
        )
        if match:
            return _normalize_text(match.group(1))
    return ''


def parse_alert_detail(html: str, detail_url: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, 'html.parser')
    container = soup.find('div', class_='bodyModel')
    if not container:
        return None

    parsed: dict[str, str] = {}
    current_key = ''

    for element in container.find_all(['h4', 'p', 'a', 'li']):
        if element.name == 'h4':
            heading = _norm_heading(element.get_text(' ', strip=True))
            current_key = FIELD_MAP.get(heading, heading.replace(' ', '_'))
            continue

        if not current_key:
            continue

        links = element.find_all('a', href=True)
        if links:
            values = [
                f"{_normalize_text(link.get_text(' ', strip=True))} ({urljoin(ALERTS_PAGE_URL, link['href'])})"
                for link in links
                if _normalize_text(link.get_text(' ', strip=True))
            ]
            text = ' | '.join(values)
        else:
            text = _normalize_text(element.get_text(' ', strip=True))

        if not text:
            continue

        parsed[current_key] = f"{parsed[current_key]} {text}".strip() if parsed.get(current_key) else text

    parsed['url'] = detail_url
    parsed.update(_parse_product_identification_block(parsed.get('identificacao_produto_ou_caso', '')))

    if not parsed.get('empresa'):
        company = _extract_company(parsed)
        if company:
            parsed['empresa'] = company

    return parsed
