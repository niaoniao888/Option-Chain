from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

from options_panel.config import Settings
from options_panel.providers.bitcoin_options import BinanceOptionsProvider
from options_panel.us_equities.alpaca_adapter import AlpacaAdapter, AlpacaHttp, probe_credentials
from options_panel.us_equities.network_diagnostics import SafeJsonlLog


@dataclass(frozen=True)
class ProviderBinding:
    market_id: str
    provider_id: str
    provider_name: str
    adapter: Any | None = None


ProviderFactory = Callable[[Settings], ProviderBinding]


class ProviderRegistry:
    def __init__(self):
        self._items: OrderedDict[tuple[str, str], ProviderFactory] = OrderedDict()

    def register(self, market_id: str, provider_id: str, factory: ProviderFactory,
                 *, replace: bool = False) -> None:
        key = market_id, provider_id
        if key in self._items and not replace:
            raise ValueError(f"provider already registered: {market_id}/{provider_id}")
        self._items[key] = factory

    def create(self, market_id: str, provider_id: str, settings: Settings) -> ProviderBinding:
        factory = self._items.get((market_id, provider_id))
        if factory is None:
            raise ValueError(f"unknown provider for {market_id}: {provider_id}")
        binding = factory(settings)
        if binding.market_id != market_id or binding.provider_id != provider_id:
            raise ValueError("provider factory returned mismatched identity")
        if binding.adapter is None:
            raise ValueError(f"provider adapter is required: {market_id}/{provider_id}")
        return binding


def _binance(_settings: Settings) -> ProviderBinding:
    return ProviderBinding("bitcoin", "binance", "Binance Options", adapter=BinanceOptionsProvider())


def _alpaca(settings: Settings) -> ProviderBinding:
    diagnostic_log = SafeJsonlLog(settings.us_data_dir.parent / "logs")
    client_factory = lambda key, secret: AlpacaHttp(key, secret, logger=diagnostic_log)
    adapter = AlpacaAdapter(
        client_factory=client_factory,
        probe=lambda key, secret: probe_credentials(key, secret, client_factory=client_factory),
    )
    return ProviderBinding("us-equities", "alpaca", "Alpaca IEX / Indicative", adapter=adapter)


def default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register("bitcoin", "binance", _binance)
    registry.register("us-equities", "alpaca", _alpaca)
    return registry
