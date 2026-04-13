from __future__ import annotations

import re
from typing import Any


def _clean_text(value: Any) -> str:
    text = str(value or '').strip()
    if not text or text in {'-', '--', 'N/A', 'n/a'}:
        return ''
    return text


def _pick_from_dict(source: dict[str, Any], *keys: str) -> str:
    for key in keys:
        cleaned = _clean_text(source.get(key))
        if cleaned:
            return cleaned
    return ''


def _normalize_key(value: str) -> str:
    return re.sub(r'\s+', ' ', value.casefold()).strip()


def _unique(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned:
            continue
        key = _normalize_key(cleaned)
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _extract_models(alerts: list[dict[str, Any]]) -> list[str]:
    chunks: list[str] = []
    for item in alerts:
        raw = _clean_text(item.get('modelo_afetado'))
        if raw:
            chunks.extend(re.split(r'[;,|\n]+', raw))

    candidates = [token.strip() for token in chunks if token.strip()]
    strong = [token for token in candidates if len(token) >= 3 and re.search(r'[a-zA-Z]|\d', token)]
    return _unique(strong)[:8]


def _extract_models_from_documents(indexed_documents: list[dict[str, Any]]) -> list[str]:
    chunks: list[str] = []
    for item in indexed_documents:
        if not isinstance(item, dict):
            continue
        text = ' '.join(
            str(item.get(key) or '')
            for key in ('modelo', 'model', 'titulo', 'resumo')
        )
        for match in re.findall(r'(?:modelo|model)\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9\-/\.]{1,24})', text, flags=re.I):
            chunks.append(match.strip())

    return _unique(chunks)[:8]


def _extract_brands_from_documents(indexed_documents: list[dict[str, Any]]) -> list[str]:
    chunks: list[str] = []
    for item in indexed_documents:
        if not isinstance(item, dict):
            continue
        text = ' '.join(str(item.get(key) or '') for key in ('titulo', 'resumo'))
        for match in re.findall(r'(?:marca|brand)\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9 .&-]{1,40})', text, flags=re.I):
            chunks.append(match.strip())
    return _unique(chunks)[:6]


def build_consolidated_product_data(official_data: dict[str, Any], enriched_data: dict[str, Any]) -> dict[str, Any]:
    ordered_fields = [
        ('numero_registro', 'Número do registro'),
        ('nome_produto', 'Nome do produto'),
        ('marca', 'Marca'),
        ('modelo', 'Modelo'),
        ('fabricante', 'Fabricante / Empresa'),
        ('nome_comercial', 'Nome comercial'),
        ('nome_tecnico', 'Nome técnico'),
        ('classe_risco', 'Classe de risco'),
        ('tipo_produto', 'Tipo de produto'),
        ('cnpj', 'CNPJ'),
        ('numero_processo', 'Número do processo'),
        ('situacao_registro', 'Situação do registro'),
        ('modelos_relacionados', 'Modelos relacionados'),
    ]

    final_data: dict[str, Any] = {}
    for key, _ in ordered_fields:
        value = enriched_data.get(key)
        if isinstance(value, list) and value:
            final_data[key] = value
        elif _clean_text(value):
            final_data[key] = value

    return {
        'fields_order': [key for key, _ in ordered_fields if key in final_data],
        'labels': {key: label for key, label in ordered_fields if key in final_data},
        'data': final_data,
        'official_data': official_data,
    }


def enrich_product_data(
    official_data: dict[str, Any],
    alerts: list[dict[str, Any]] | None = None,
    indexed_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    alerts = alerts or []
    indexed_documents = indexed_documents or []

    company = official_data.get('empresa') if isinstance(official_data.get('empresa'), dict) else {}

    official_company = _pick_from_dict(company, 'razaoSocial')
    official_brand = _pick_from_dict(official_data, 'marca', 'nomeMarca')
    official_model = _pick_from_dict(official_data, 'modelo', 'nomeModelo')
    official_manufacturer = _pick_from_dict(official_data, 'fabricante', 'fabricanteLegal')
    official_nome_tecnico = _pick_from_dict(official_data, 'nomeTecnico')
    official_nome_comercial = _pick_from_dict(official_data, 'nomeProduto', 'nomeComercial')
    official_tipo_produto = _pick_from_dict(official_data, 'tipoProduto')
    official_classe_risco = _pick_from_dict(official_data, 'classeRisco')

    alert_brands = _unique([item.get('marca') for item in alerts])
    alert_models = _extract_models(alerts)
    alert_companies = _unique([item.get('empresa') for item in alerts])
    alert_nome_comercial = _unique([item.get('nome_comercial') for item in alerts])
    alert_nome_tecnico = _unique([item.get('nome_tecnico') for item in alerts])
    alert_tipo = _unique([item.get('tipo_produto') for item in alerts])
    alert_risco = _unique([item.get('classe_risco') for item in alerts])

    doc_models = _unique([
        *[doc.get('modelo') or doc.get('model') for doc in indexed_documents if isinstance(doc, dict)],
        *_extract_models_from_documents(indexed_documents),
    ])
    doc_brands = _extract_brands_from_documents(indexed_documents)
    doc_manufacturers = _unique([
        doc.get('fabricante') or doc.get('manufacturer') for doc in indexed_documents if isinstance(doc, dict)
    ])

    brand = official_brand or (alert_brands[0] if alert_brands else '') or (doc_brands[0] if doc_brands else '')
    model = official_model or (alert_models[0] if alert_models else '') or (doc_models[0] if doc_models else '')

    manufacturer = official_manufacturer
    if not manufacturer:
        manufacturer_candidates = _unique([official_company, *alert_companies, *doc_manufacturers])
        manufacturer = manufacturer_candidates[0] if manufacturer_candidates else ''

    nome_comercial = official_nome_comercial or (alert_nome_comercial[0] if alert_nome_comercial else '')
    if _normalize_key(nome_comercial) == _normalize_key(_pick_from_dict(official_data, 'nomeProduto')):
        nome_comercial = ''
    nome_tecnico = official_nome_tecnico or (alert_nome_tecnico[0] if alert_nome_tecnico else '')
    tipo_produto = official_tipo_produto or (alert_tipo[0] if alert_tipo else '')
    classe_risco = official_classe_risco or (alert_risco[0] if alert_risco else '')

    base = {
        'numero_registro': _pick_from_dict(official_data, 'numeroRegistro'),
        'nome_produto': _pick_from_dict(official_data, 'nomeProduto'),
        'marca': brand,
        'modelo': model,
        'fabricante': manufacturer,
        'nome_comercial': nome_comercial,
        'nome_tecnico': nome_tecnico,
        'classe_risco': classe_risco,
        'tipo_produto': tipo_produto,
        'cnpj': _pick_from_dict(company, 'cnpj'),
        'numero_processo': _pick_from_dict(official_data, 'numeroProcesso'),
        'situacao_registro': _pick_from_dict(official_data, 'situacaoNotificacaoRegistro'),
    }

    if not model:
        related_models = _unique([*alert_models, *doc_models])
        if related_models:
            base['modelos_relacionados'] = related_models

    consolidated = build_consolidated_product_data(official_data, base)

    return {
        'official_data': official_data,
        'enriched_data': base,
        'consolidated_product_data': consolidated,
    }
