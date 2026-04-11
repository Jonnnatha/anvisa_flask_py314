from __future__ import annotations

import re
from typing import Any


def _clean_text(value: Any) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    if text in {'-', '--', 'N/A', 'n/a'}:
        return ''
    return text


def _sanitize_model_tokens(raw: str) -> list[str]:
    tokens = []
    for piece in re.split(r'[;,|\n\r]+', raw or ''):
        candidate = _clean_text(piece)
        if not candidate:
            continue
        if len(candidate) < 2:
            continue
        tokens.append(candidate)
    return tokens


def _pick_from_dict(source: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = source.get(key)
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ''


def enrich_product_data(
    official_data: dict[str, Any],
    alerts: list[dict[str, Any]] | None = None,
    indexed_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Monta camada de enriquecimento sem sobrescrever dados oficiais.

    Regras:
    - prioriza campos oficiais já existentes;
    - usa alertas locais como reforço quando oficial está ausente;
    - só retorna campos com evidência mínima;
    - não usa placeholders.
    """

    alerts = alerts or []
    indexed_documents = indexed_documents or []

    company = official_data.get('empresa') if isinstance(official_data.get('empresa'), dict) else {}

    official_brand = _pick_from_dict(official_data, 'marca', 'nomeMarca')
    official_model = _pick_from_dict(official_data, 'modelo', 'nomeModelo')
    official_manufacturer = _pick_from_dict(official_data, 'fabricante', 'fabricanteLegal')
    official_nome_tecnico = _pick_from_dict(official_data, 'nomeTecnico')
    official_nome_comercial = _pick_from_dict(official_data, 'nomeProduto', 'nomeComercial')
    official_company = _pick_from_dict(company, 'razaoSocial')
    official_tipo_produto = _pick_from_dict(official_data, 'tipoProduto')
    official_classe_risco = _pick_from_dict(official_data, 'classeRisco')

    alert_companies = [_clean_text(item.get('empresa')) for item in alerts if _clean_text(item.get('empresa'))]
    alert_commercial = [_clean_text(item.get('nome_comercial')) for item in alerts if _clean_text(item.get('nome_comercial'))]
    alert_technical = [_clean_text(item.get('nome_tecnico')) for item in alerts if _clean_text(item.get('nome_tecnico'))]
    alert_models_raw = [_clean_text(item.get('modelo_afetado')) for item in alerts if _clean_text(item.get('modelo_afetado'))]
    alert_tipo_produto = [_clean_text(item.get('tipo_produto')) for item in alerts if _clean_text(item.get('tipo_produto'))]
    alert_classe_risco = [_clean_text(item.get('classe_risco')) for item in alerts if _clean_text(item.get('classe_risco'))]

    document_models: list[str] = []
    document_manufacturers: list[str] = []
    for doc in indexed_documents:
        if not isinstance(doc, dict):
            continue
        model = _clean_text(doc.get('modelo') or doc.get('model'))
        manufacturer = _clean_text(doc.get('fabricante') or doc.get('manufacturer'))
        if model:
            document_models.append(model)
        if manufacturer:
            document_manufacturers.append(manufacturer)

    derived_model_candidates: list[str] = []
    for raw in alert_models_raw + document_models:
        derived_model_candidates.extend(_sanitize_model_tokens(raw))

    unique_models: list[str] = []
    seen_models: set[str] = set()
    for model in derived_model_candidates:
        key = model.casefold()
        if key in seen_models:
            continue
        seen_models.add(key)
        unique_models.append(model)

    enriched: dict[str, Any] = {}

    if not official_brand:
        # Marca só entra por evidência explícita em alerta/documento.
        # Evita inferir marca a partir de empresa para não gerar falso positivo.
        pass

    if not official_model and unique_models:
        enriched['modelos_relacionados'] = unique_models[:8]

    if not official_manufacturer:
        for candidate in [official_company, *alert_companies, *document_manufacturers]:
            if candidate:
                enriched['fabricante_sugerido'] = candidate
                break

    if not official_nome_tecnico:
        for candidate in alert_technical:
            if candidate:
                enriched['nome_tecnico_sugerido'] = candidate
                break

    if not official_nome_comercial:
        for candidate in alert_commercial:
            if candidate:
                enriched['nome_comercial_sugerido'] = candidate
                break

    if not official_tipo_produto:
        for candidate in alert_tipo_produto:
            if candidate:
                enriched['tipo_produto_sugerido'] = candidate
                break

    if not official_classe_risco:
        for candidate in alert_classe_risco:
            if candidate:
                enriched['classe_risco_sugerida'] = candidate
                break

    return {
        'official_data': official_data,
        'enriched_data': enriched,
    }
