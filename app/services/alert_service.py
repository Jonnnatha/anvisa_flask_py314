from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus

from app.services.http_client import HttpClient


@dataclass
class AlertLookupResult:
    alerts: list[dict[str, str]]
    automatic_lookup_failed: bool
    manual_url: str
    error: str | None = None


class AlertService:
    """Consulta alertas de tecnovigilância com fallback amigável."""

    API_CANDIDATES = (
        "https://consultas.anvisa.gov.br/api/tecnovigilancia/alertas",
        "https://consultas.anvisa.gov.br/api/tecnovigilancia/notificacoes",
        "https://dados.anvisa.gov.br/dados/TA_ALERTA_TECNOVIGILANCIA.json",
    )
    MANUAL_BASE_URL = "https://consultas.anvisa.gov.br/#/tecnovigilancia/q/"

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def lookup(self, registro: str) -> AlertLookupResult:
        registro = self._sanitize(registro)
        manual_url = self._manual_url(registro)

        errors: list[str] = []
        had_success_response = False
        query_variants = (
            {"filter[registro]": registro, "count": 100, "page": 1},
            {"registro": registro, "count": 100, "page": 1},
        )

        for base_url in self.API_CANDIDATES:
            for params in query_variants:
                result = self.client.get_json(base_url, params=params)
                if not result.ok:
                    errors.append(f"{base_url}: {result.error}")
                    continue

                had_success_response = True
                alerts = self._extract_alerts(result.data, registro)
                if alerts is None:
                    continue
                return AlertLookupResult(
                    alerts=alerts,
                    automatic_lookup_failed=False,
                    manual_url=manual_url,
                )

        if had_success_response:
            return AlertLookupResult(
                alerts=[],
                automatic_lookup_failed=False,
                manual_url=manual_url,
            )

        return AlertLookupResult(
            alerts=[],
            automatic_lookup_failed=True,
            manual_url=manual_url,
            error=" | ".join(errors) if errors else "Falha desconhecida ao consultar alertas.",
        )

    @staticmethod
    def _sanitize(registro: str) -> str:
        return "".join(ch for ch in str(registro) if ch.isdigit())

    def _manual_url(self, registro: str) -> str:
        return f"{self.MANUAL_BASE_URL}?registro={quote_plus(registro)}"

    def _extract_alerts(self, payload: Any, registro: str) -> list[dict[str, str]] | None:
        rows = self._collect_rows(payload)
        if rows is None:
            return None

        output: list[dict[str, str]] = []
        for row in rows:
            if not self._match_registro(row, registro):
                continue
            output.append(
                {
                    "titulo": str(row.get("titulo") or row.get("assunto") or row.get("descricao") or "Alerta sem título"),
                    "numero": str(row.get("numeroAlerta") or row.get("numero") or row.get("id") or "N/A"),
                    "data": self._format_date(row.get("dataPublicacao") or row.get("data") or row.get("dt_publicacao")),
                    "link": str(row.get("link") or row.get("url") or self._manual_url(registro)),
                }
            )
        return output

    @staticmethod
    def _collect_rows(payload: Any) -> list[dict[str, Any]] | None:
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]

        if isinstance(payload, dict):
            rows: list[dict[str, Any]] = []
            for key in ("content", "items", "results", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    rows.extend([row for row in value if isinstance(row, dict)])
            if rows:
                return rows
            if AlertService._looks_like_alert(payload):
                return [payload]
            return []

        return None

    @staticmethod
    def _match_registro(row: dict[str, Any], registro: str) -> bool:
        reg_keys = ("registro", "registroAnvisa", "numeroRegistro", "nr_registro_produto")
        values = [row.get(key) for key in reg_keys if row.get(key) is not None]
        if not values:
            # Algumas bases de alerta não possuem registro explícito em todos os itens.
            return True
        normalized = {"".join(ch for ch in str(v) if ch.isdigit()) for v in values}
        return registro in normalized

    @staticmethod
    def _looks_like_alert(data: dict[str, Any]) -> bool:
        keys = {str(k).lower() for k in data.keys()}
        return bool(keys.intersection({"titulo", "assunto", "numeroalerta", "datapublicacao"}))

    @staticmethod
    def _format_date(value: Any) -> str:
        if not value:
            return "Não informada"
        text = str(value)
        formats = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y")
        for fmt in formats:
            try:
                return datetime.strptime(text[:19], fmt).strftime("%d/%m/%Y")
            except ValueError:
                continue
        return text
