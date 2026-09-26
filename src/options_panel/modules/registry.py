from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from options_panel.config import Settings
from options_panel.content.guide_store import GuideStore
from options_panel.modules.bitcoin import BitcoinRuntime
from options_panel.runtime.market import MarketDescriptor, MarketRuntime
from options_panel.runtime.snapshot import DashboardState
from options_panel.us_equities.runtime import UsEquitiesRuntime
from options_panel.providers.registry import ProviderRegistry


@dataclass(frozen=True)
class RuntimeContext:
    settings: Settings
    compatibility: Mapping[str, Any]
    providers: ProviderRegistry


RuntimeFactory = Callable[[RuntimeContext], MarketRuntime]
RouteInstaller = Callable[[Any, Any, "MarketRegistration"], None]
ProviderSelector = Callable[[Settings], str]


@dataclass(frozen=True)
class StaticPageConfig:
    desktop_dir: str = "app"
    mobile_dir: str = "app"
    desktop_assets: tuple[str, ...] = ("app.js", "style.css")
    mobile_assets: tuple[str, ...] = ("app.js", "style.css")
    index_name: str = "index.html"


@dataclass(frozen=True)
class MarketRegistration:
    descriptor: MarketDescriptor
    runtime_factory: RuntimeFactory
    api_profile: str = "generic"
    static_page: StaticPageConfig = StaticPageConfig()
    provider_selector: ProviderSelector | None = None
    route_installer: RouteInstaller | None = None


class MarketRegistry:
    def __init__(self, registrations: Iterable[MarketRegistration] = ()):
        self._items: OrderedDict[str, MarketRegistration] = OrderedDict()
        for registration in registrations:
            self.register(registration)

    def register(self, registration: MarketRegistration, *, replace: bool = False) -> None:
        market_id = registration.descriptor.market_id
        if market_id in self._items and not replace:
            raise ValueError(f"market already registered: {market_id}")
        self._items[market_id] = registration

    def registrations(self) -> tuple[MarketRegistration, ...]:
        return tuple(self._items.values())

    def get(self, market_id: str) -> MarketRegistration | None:
        return self._items.get(market_id)

    def public_modules(self, base_path: str = "") -> list[dict[str, str]]:
        return [item.descriptor.public(base_path) for item in self._items.values()]


def _bitcoin_runtime(context: RuntimeContext) -> BitcoinRuntime:
    settings = context.settings
    state = context.compatibility.get("bitcoin_state")
    if not isinstance(state, DashboardState):
        state = DashboardState()
    provider = context.providers.create("bitcoin", settings.bitcoin_provider, settings)
    return BitcoinRuntime(
        state,
        GuideStore(settings.data_dir / "options-guide.json"),
        settings.runtime_dir,
        collector_enabled=settings.collector_enabled and settings.bitcoin_collector_enabled,
        provider_id=provider.provider_id, provider_name=provider.provider_name,
        provider=provider.adapter,
    )


def _us_runtime(context: RuntimeContext) -> UsEquitiesRuntime:
    settings = context.settings
    provider = context.providers.create("us-equities", settings.us_equities_provider, settings)
    return UsEquitiesRuntime(
        settings.us_data_dir,
        collector_enabled=settings.collector_enabled and settings.us_collector_enabled,
        provider_id=provider.provider_id, provider_name=provider.provider_name,
        adapter=provider.adapter,
    )


def default_registry() -> MarketRegistry:
    return MarketRegistry((
        MarketRegistration(
            BitcoinRuntime.descriptor, _bitcoin_runtime, api_profile="bitcoin",
            static_page=StaticPageConfig(
                desktop_dir="desktop", mobile_dir="mobile",
                desktop_assets=("app.js", "style.css"), mobile_assets=("mobile.js", "mobile.css"),
            ),
            provider_selector=lambda settings: settings.bitcoin_provider,
        ),
        MarketRegistration(
            UsEquitiesRuntime.descriptor, _us_runtime, api_profile="us-equities",
            static_page=StaticPageConfig(
                desktop_dir="us-equities", mobile_dir="us-equities",
                desktop_assets=("app.js", "style.css", "guide.js"),
                mobile_assets=("app.js", "style.css", "guide.js"),
            ),
            provider_selector=lambda settings: settings.us_equities_provider,
        ),
    ))


def public_modules(base_path: str = "") -> list[dict[str, str]]:
    """Compatibility helper retained for callers outside the app factory."""
    return default_registry().public_modules(base_path)
