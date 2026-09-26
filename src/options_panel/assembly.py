from __future__ import annotations

from dataclasses import dataclass, replace

from options_panel.config import Settings
from options_panel.modules.registry import MarketRegistry, RuntimeContext, default_registry
from options_panel.runtime.lifecycle import RuntimeLifecycle, RuntimeRecord
from options_panel.runtime.market import SnapshotResponseCache
from options_panel.runtime.snapshot import DashboardState
from options_panel.providers.registry import ProviderRegistry, default_provider_registry
from options_panel.logging import log_event
import logging


@dataclass
class Platform:
    settings: Settings
    registry: MarketRegistry
    records: dict[str, RuntimeRecord]
    lifecycle: RuntimeLifecycle
    snapshot_cache: SnapshotResponseCache
    bitcoin_state: DashboardState

    def runtime(self, market_id: str):
        record = self.records.get(market_id)
        return record.runtime if record else None

    def public_modules(self) -> list[dict[str, str]]:
        result = []
        for registration in self.registry.registrations():
            record = self.records[registration.descriptor.market_id]
            descriptor = record.descriptor or registration.descriptor
            result.append(descriptor.public(self.settings.base_path))
        return result


def assemble_platform(settings: Settings, state: DashboardState | None = None,
                      registry: MarketRegistry | None = None,
                      provider_registry: ProviderRegistry | None = None) -> Platform:
    dashboard = state or DashboardState()
    selected = registry or default_registry()
    providers = provider_registry or default_provider_registry()
    context = RuntimeContext(settings=settings, compatibility={"bitcoin_state": dashboard}, providers=providers)
    records: dict[str, RuntimeRecord] = {}
    for registration in selected.registrations():
        market_id = registration.descriptor.market_id
        try:
            runtime = registration.runtime_factory(context)
            records[market_id] = RuntimeRecord(
                market_id=market_id, descriptor=runtime.descriptor, runtime=runtime,
            )
        except Exception as exc:
            provider_id = registration.descriptor.provider_id
            selector_error = None
            if registration.provider_selector:
                try:
                    provider_id = registration.provider_selector(settings)
                except Exception as selector_exc:
                    selector_error = type(selector_exc).__name__
            unavailable = replace(
                registration.descriptor, provider_id=provider_id, provider_name=provider_id,
                status="unavailable",
            )
            records[market_id] = RuntimeRecord(
                market_id=market_id, descriptor=unavailable,
                initialization_error=type(exc).__name__,
            )
            log_event(
                logging.WARNING,
                "market_runtime_initialization_failed",
                market=market_id,
                provider=provider_id,
                exception_type=type(exc).__name__,
                provider_selector_exception_type=selector_error,
            )
    lifecycle = RuntimeLifecycle(records)
    return Platform(settings, selected, records, lifecycle, SnapshotResponseCache(), dashboard)
