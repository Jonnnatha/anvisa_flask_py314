from __future__ import annotations

from typing import Any

from app.services.materials_service import find_related_materials


# Compatibilidade com versão anterior.
def find_related_public_signals(registro: str, product: dict[str, Any] | None = None) -> dict[str, Any]:
    return find_related_materials(registro, product=product)
