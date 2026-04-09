from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

from app.services.http_client import HttpClient


@dataclass
class ProductLookupResult:
    found: bool
    product: dict[str, Any] | None
    source_url: str | None
    manual_url: str
    error: str | None = None


class ProductService:
    """Consulta produto/equipamento por registro ANVISA com múltiplas estratégias."""

    API_CANDIDATES = (
        "https://consultas.anvisa.gov.br/api/produtos-saude/produtos",
        "https://consultas.anvisa.gov.br/api/produtos-saude/consulta",
    )
    MANUAL_BASE_URL = "https://consultas.anvisa.gov.br/#/saude/q/"

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def lookup(self, registro: str) -> ProductLookupResult:
        registro = self._sanitize(registro)
        manual_url = self._manual_url(registro)
        errors: list[str] = []

        query_variants = (
            {"filter[numeroRegistro]": registro, "count": 1, "page": 1},
            {"numeroRegistro": registro, "count": 1, "page": 1},
        )

        for base_url in self.API_CANDIDATES:
            for params in query_variants:
                result = self.client.get_json(base_url, params=params)
                if not result.ok:
                    errors.append(f"{base_url}: {result.error}")
                    continue

                parsed = self._extract_product(result.data, registro)
                if parsed:
                    return ProductLookupResult(
                        found=True,
                        product=self._normalize(parsed, registro),
                        source_url=result.url or base_url,
                        manual_url=manual_url,
                    )

        return ProductLookupResult(
            found=False,
            product=None,
            source_url=None,
            manual_url=manual_url,
            error=" | ".join(errors) if errors else "Registro não encontrado.",
        )

    @staticmethod
    def _sanitize(registro: str) -> str:
        return "".join(ch for ch in str(registro) if ch.isdigit())

    def _manual_url(self, registro: str) -> str:
        return f"{self.MANUAL_BASE_URL}?registro={quote_plus(registro)}"

    @staticmethod
    def _extract_product(payload: Any, registro: str) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []

        if isinstance(payload, dict):
            if ProductService._registro_matches(payload, registro):
                return payload
            for key in ("content", "items", "results", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    candidates.extend([item for item in value if isinstance(item, dict)])
                elif isinstance(value, dict):
                    candidates.append(value)
        elif isinstance(payload, list):
            candidates.extend([item for item in payload if isinstance(item, dict)])

        for item in candidates:
            if ProductService._registro_matches(item, registro):
                return item

        return None

    @staticmethod
    def _registro_matches(data: dict[str, Any], registro: str) -> bool:
        values = (
            data.get("numeroRegistro"),
            data.get("registro"),
            data.get("registro_anvisa"),
            data.get("registroAnvisa"),
        )
        normalized = {"".join(ch for ch in str(v) if ch.isdigit()) for v in values if v is not None}
        return registro in normalized

    @staticmethod
    def _normalize(data: dict[str, Any], registro: str) -> dict[str, str]:
        return {
            "registro": registro,
            "nome_produto": str(data.get("nomeProduto") or data.get("produto") or data.get("nome") or "Não informado"),
            "marca": str(data.get("marca") or "Não informado"),
            "modelo": str(data.get("modelo") or data.get("nomeModelo") or "Não informado"),
            "fabricante": str(data.get("fabricante") or data.get("nomeFabricante") or "Não informado"),
            "detentor": str(data.get("detentorRegistro") or data.get("razaoSocial") or "Não informado"),
            "pais_fabricacao": str(data.get("paisFabricacao") or data.get("nomePaisFabricacao") or "Não informado"),
            "situacao": str(data.get("situacaoRegistro") or data.get("situacao") or "Não informado"),
        }
