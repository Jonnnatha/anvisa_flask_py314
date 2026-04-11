from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

REGISTRATION_RE = re.compile(r"\b\d{11}\b")


INDEX_KEYS = (
    'numero_alerta',
    'registro_anvisa',
    'empresa',
    'nome_comercial',
    'nome_tecnico',
    'modelo_afetado',
)


def _split_multi_value(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r'[;|,\n]+', text)
    return [part.strip() for part in parts if part and part.strip()]


def _normalize_key(value: str) -> str:
    return value.casefold().strip()


def _extract_registrations_from_text(value: str) -> list[str]:
    return list(dict.fromkeys(REGISTRATION_RE.findall(value or '')))


def _extract_registrations(alert: dict[str, Any]) -> list[str]:
    explicit = _split_multi_value(str(alert.get('numero_registro_anvisa') or ''))
    explicit_digits = [re.sub(r'\D', '', item) for item in explicit]
    explicit_digits = [item for item in explicit_digits if len(item) == 11]

    if explicit_digits:
        return list(dict.fromkeys(explicit_digits))

    text_pool = ' '.join(
        [
            str(alert.get('identificacao_produto_ou_caso') or ''),
            str(alert.get('resumo') or ''),
            str(alert.get('problema') or ''),
        ]
    )
    return _extract_registrations_from_text(text_pool)


def build_alerts_index(alerts: list[dict[str, Any]]) -> dict[str, dict[str, list[Any]]]:
    index: dict[str, defaultdict[str, list[Any]]] = {
        key: defaultdict(list) for key in INDEX_KEYS
    }

    for alert in alerts:
        alert_number = str(alert.get('numero_alerta') or '').strip()
        if alert_number:
            index['numero_alerta'][alert_number].append(alert_number)

        for reg in _extract_registrations(alert):
            index['registro_anvisa'][reg].append(alert_number)

        for key, field in (
            ('empresa', 'empresa'),
            ('nome_comercial', 'nome_comercial'),
            ('nome_tecnico', 'nome_tecnico'),
            ('modelo_afetado', 'modelo_afetado'),
        ):
            values = _split_multi_value(str(alert.get(field) or ''))
            for value in values:
                normalized = _normalize_key(value)
                if normalized:
                    index[key][normalized].append(alert_number)

    finalized: dict[str, dict[str, list[Any]]] = {}
    for key, bucket in index.items():
        finalized[key] = {
            term: list(dict.fromkeys(numbers))
            for term, numbers in bucket.items()
            if numbers
        }

    return finalized


def save_index(index_path: Path, index: dict[str, Any]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def load_index(index_path: Path) -> dict[str, Any]:
    if not index_path.exists():
        return {key: {} for key in INDEX_KEYS}

    try:
        data = json.loads(index_path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return {key: {} for key in INDEX_KEYS}

    for key in INDEX_KEYS:
        data.setdefault(key, {})
    return data
