from __future__ import annotations

import os


class Settings:
    """Configurações da aplicação com defaults seguros para ambiente local."""

    REQUEST_TIMEOUT_SECONDS = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
    VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() == "true"
    ALLOW_INSECURE_SSL_FALLBACK = os.getenv("ALLOW_INSECURE_SSL_FALLBACK", "true").lower() == "true"


settings = Settings()
