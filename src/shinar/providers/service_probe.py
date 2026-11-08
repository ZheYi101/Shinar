"""Read only OpenAI-compatible model metadata; never generate billable content."""

import httpx

from shinar.infrastructure.ai_configuration import AIConnection


async def probe_models(connection: AIConnection, *, transport=None) -> list[str]:
    try:
        async with httpx.AsyncClient(
            timeout=15, follow_redirects=False, transport=transport,
        ) as client:
            async with client.stream(
                "GET", connection.base_url + "/models",
                headers={"Authorization": "Bearer " + connection.api_key},
            ) as response:
                if response.status_code != 200:
                    raise ValueError({401: "ai_api_auth_failed", 403: "ai_api_auth_failed",
                                      404: "ai_api_models_unsupported", 405: "ai_api_models_unsupported",
                                      429: "ai_api_rate_limited"}.get(response.status_code, "ai_api_connection_failed"))
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 2 * 1024**2:
                        raise ValueError("ai_api_models_invalid")
                import json
                value = json.loads(body)
                rows = value.get("data") if isinstance(value, dict) else None
                if not isinstance(rows, list):
                    raise ValueError("ai_api_models_invalid")
                return sorted({r["id"] for r in rows if isinstance(r, dict)
                               and isinstance(r.get("id"), str) and 0 < len(r["id"]) <= 256
                               and r["id"].strip() == r["id"]
                               and not any(ord(c) < 32 for c in r["id"])})[:2000]
    except (httpx.HTTPError, OSError):
        raise ValueError("ai_api_connection_failed") from None
    except (TypeError, UnicodeError):
        raise ValueError("ai_api_models_invalid") from None
