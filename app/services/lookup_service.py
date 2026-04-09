from __future__ import annotations

from dataclasses import dataclass

from app.services.alert_service import AlertService
from app.services.product_service import ProductService


@dataclass
class SearchResult:
    registro: str
    found: bool
    product: dict | None
    alerts: list[dict]
    product_error: str | None
    alerts_error: str | None
    automatic_alert_lookup_failed: bool
    manual_alert_url: str


class LookupService:
    def __init__(self, product_service: ProductService | None = None, alert_service: AlertService | None = None) -> None:
        self.product_service = product_service or ProductService()
        self.alert_service = alert_service or AlertService()

    def search(self, registro: str) -> SearchResult:
        cleaned = "".join(c for c in registro if c.isdigit())

        product_result = self.product_service.lookup(cleaned)

        alerts: list[dict] = []
        alerts_error = None
        automatic_alert_lookup_failed = False

        if product_result.found:
            alert_result = self.alert_service.lookup(cleaned)
            alerts = alert_result.alerts
            alerts_error = alert_result.error
            automatic_alert_lookup_failed = alert_result.automatic_lookup_failed

        return SearchResult(
            registro=cleaned,
            found=product_result.found,
            product=product_result.product,
            alerts=alerts,
            product_error=product_result.error,
            alerts_error=alerts_error,
            automatic_alert_lookup_failed=automatic_alert_lookup_failed,
            manual_alert_url=AlertService.MANUAL_URL,
        )
