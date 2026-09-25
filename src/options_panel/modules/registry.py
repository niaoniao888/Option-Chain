from __future__ import annotations

MODULES = ({
    "id": "bitcoin",
    "title": "比特币期权面板",
    "status": "available",
    "desktop_path": "/bitcoin/desktop/",
    "mobile_path": "/bitcoin/mobile/",
    "provider": "Binance Options",
},)


def public_modules(base_path: str = "") -> list[dict[str, str]]:
    return [{**item, "desktop_path": base_path + item["desktop_path"], "mobile_path": base_path + item["mobile_path"]} for item in MODULES]
