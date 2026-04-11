from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import ALERTS_DATA_FILE, ALERTS_INDEX_FILE
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


def find_alerts_by_registration(registro: str) -> dict[str, Any]:
    normalized_registro = _normalize_registro(registro)
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
        'source': 'base local indexada de alertas Anvisa',
        'count': len(matched_alerts),
        'alerts': matched_alerts,
        'warning': sync_info.get('warning'),
        'sync': sync_info,
    }
