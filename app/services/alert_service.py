from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.http_client import HttpClient


@dataclass
class AlertLookupResult:
    alerts: list[dict[str, str]]
    automatic_lookup_failed: bool
    error: str | None = None


class AlertService:
    """Lookup technovigilance alerts related to an ANVISA registration number."""

    API_CANDIDATES = [
        "https://consultas.anvisa.gov.br/api/tecnovigilancia/alertas",
        "https://consultas.anvisa.gov.br/api/tecnovigilancia/notificacoes",
        "https://dados.anvisa.gov.br/dados/TA_ALERTA_TECNOVIGILANCIA.json",
    ]

    MANUAL_URL = "https://consultas.anvisa.gov.br/#/tecnovigilancia/q/"

    def __init__(self, client: HttpClient | None = None) -> None:
        self.client = client or HttpClient()

    def lookup(self, registro: str) -> AlertLookupResult:
        registro = "".join(c for c in registro if c.isdigit())
        errors: list[str] = []

        for url in self.API_CANDIDATES:
            params_variants = [
                {"filter[registro]": registro, "count": 100, "page": 1},
                {"registro": registro, "count": 100, "page": 1},
            ]
            for params in params_variants:
                result = self.client.get_json(url, params=params)
                if not result.ok:
                    errors.append(f"{url} -> {result.error}")
                    continue

                parsed = self._extract_alerts(result.data, registro)
                if parsed is not None:
                    return AlertLookupResult(alerts=parsed, automatic_lookup_failed=False)

        return AlertLookupResult(
            alerts=[],
            automatic_lookup_failed=True,
            error=" | ".join(errors) if errors else "Falha desconhecida na consulta de alertas.",
        )

    def _extract_alerts(self, payload: Any, registro: str) -> list[dict[str, str]] | None:
        rows: list[dict[str, Any]] = []

        if isinstance(payload, dict):
            for key in ("content", "items", "results", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    rows.extend([r for r in value if isinstance(r, dict)])
            if not rows:
                if self._looks_like_alert(payload):
                    rows.append(payload)
        elif isinstance(payload, list):
            rows = [r for r in payload if isinstance(r, dict)]

        if not rows:
            return None

        matched: list[dict[str, str]] = []
        for row in rows:
            reg_values = [
                row.get("registro"),
                row.get("registroAnvisa"),
                row.get("numeroRegistro"),
                row.get("nr_registro_produto"),
            ]
            normalized = {"".join(ch for ch in str(v) if ch.isdigit()) for v in reg_values if v}
            if registro and registro not in normalized:
                continue

            matched.append(
                {
                    "titulo": str(row.get("titulo") or row.get("assunto") or row.get("descricao") or "Alerta sem título"),
                    "numero": str(row.get("numeroAlerta") or row.get("numero") or row.get("id") or "N/A"),
                    "data": self._format_date(row.get("dataPublicacao") or row.get("data") or row.get("dt_publicacao")),
                    "link": str(row.get("link") or row.get("url") or self.MANUAL_URL),
                }
            )

        return matched

    @staticmethod
    def _looks_like_alert(row: dict[str, Any]) -> bool:
        keys = {k.lower() for k in row.keys()}
        return any(k in keys for k in ("titulo", "assunto", "numeroalerta", "datapublicacao"))

    @staticmethod
    def _format_date(value: Any) -> str:
        if value is None:
            return "Não informada"
        text = str(value)
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
            try:
                return datetime.strptime(text[:19], fmt).strftime("%d/%m/%Y")
            except ValueError:
                continue
        return text
