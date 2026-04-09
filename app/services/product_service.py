from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.http_client import HttpClient


@dataclass
class ProductLookupResult:
    found: bool
    product: dict[str, Any] | None
    source_url: str | None
    error: str | None = None


class ProductService:
    """Lookup product/equipment data by ANVISA registration number."""

    API_CANDIDATES = [
        "https://consultas.anvisa.gov.br/api/produtos-saude/produtos",
        "https://consultas.anvisa.gov.br/api/produtos-saude/consulta",
    ]

    MANUAL_URL = "https://consultas.anvisa.gov.br/#/saude/q/"

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def lookup(self, registro: str) -> ProductLookupResult:
        registro = self._sanitize_registro(registro)

        params_list = [
            {"filter[numeroRegistro]": registro, "count": 1, "page": 1},
            {"numeroRegistro": registro, "count": 1, "page": 1},
        ]

        errors: list[str] = []
        for url in self.API_CANDIDATES:
            for params in params_list:
                response = self.client.get_json(url, params=params)
                if not response.ok:
                    errors.append(f"{url} -> {response.error}")
                    continue

                product = self._extract_product(response.data, registro)
                if product:
                    normalized = self._normalize_product(product, registro)
                    return ProductLookupResult(found=True, product=normalized, source_url=url)

        return ProductLookupResult(
            found=False,
            product=None,
            source_url=None,
            error=" | ".join(errors) if errors else "Registro não encontrado.",
        )

    @staticmethod
    def _sanitize_registro(registro: str) -> str:
        return "".join(c for c in registro if c.isdigit())

    @staticmethod
    def _extract_product(payload: Any, registro: str) -> dict[str, Any] | None:
        if isinstance(payload, dict):
            for key in ("content", "items", "results", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    for row in value:
                        if ProductService._match_registro(row, registro):
                            return row
                elif isinstance(value, dict) and ProductService._match_registro(value, registro):
                    return value
            if ProductService._match_registro(payload, registro):
                return payload
        elif isinstance(payload, list):
            for row in payload:
                if ProductService._match_registro(row, registro):
                    return row
        return None

    @staticmethod
    def _match_registro(row: Any, registro: str) -> bool:
        if not isinstance(row, dict):
            return False
        candidates = [
            row.get("numeroRegistro"),
            row.get("registro"),
            row.get("registro_anvisa"),
        ]
        normalized_candidates = {"".join(ch for ch in str(c) if ch.isdigit()) for c in candidates if c}
        return registro in normalized_candidates

    @staticmethod
    def _normalize_product(row: dict[str, Any], registro: str) -> dict[str, Any]:
        return {
            "registro": registro,
            "nome_produto": row.get("nomeProduto") or row.get("produto") or row.get("nome") or "Não informado",
            "marca": row.get("marca") or "Não informado",
            "modelo": row.get("modelo") or row.get("nomeModelo") or "Não informado",
            "fabricante": row.get("fabricante") or row.get("nomeFabricante") or "Não informado",
            "detentor": row.get("detentorRegistro") or row.get("razaoSocial") or "Não informado",
            "pais_fabricacao": row.get("paisFabricacao") or row.get("nomePaisFabricacao") or "Não informado",
            "situacao": row.get("situacaoRegistro") or row.get("situacao") or "Não informado",
        }
