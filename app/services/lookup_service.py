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
    manual_product_url: str


class LookupService:
    def __init__(
        self,
        product_service: ProductService | None = None,
        alert_service: AlertService | None = None,
    ) -> None:
        self.product_service = product_service or ProductService()
        self.alert_service = alert_service or AlertService()

    def search(self, registro: str) -> SearchResult:
        cleaned = "".join(ch for ch in str(registro) if ch.isdigit())

        product_result = self.product_service.lookup(cleaned)
        if not product_result.found:
            return SearchResult(
                registro=cleaned,
                found=False,
                product=None,
                alerts=[],
                product_error=product_result.error,
                alerts_error=None,
                automatic_alert_lookup_failed=False,
                manual_alert_url=f"{AlertService.MANUAL_BASE_URL}?registro={cleaned}",
                manual_product_url=product_result.manual_url,
            )

        alert_result = self.alert_service.lookup(cleaned)

        return SearchResult(
            registro=cleaned,
            found=True,
            product=product_result.product,
            alerts=alert_result.alerts,
            product_error=None,
            alerts_error=alert_result.error,
            automatic_alert_lookup_failed=alert_result.automatic_lookup_failed,
            manual_alert_url=alert_result.manual_url,
            manual_product_url=product_result.manual_url,
        )
