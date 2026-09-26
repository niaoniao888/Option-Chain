from __future__ import annotations

from fastapi import FastAPI

from options_panel.app_factory import create_application
from options_panel.config import Settings
from options_panel.modules.registry import MarketRegistry
from options_panel.runtime.snapshot import DashboardState
from options_panel.providers.registry import ProviderRegistry


def create_app(settings: Settings | None = None, state: DashboardState | None = None,
               registry: MarketRegistry | None = None,
               provider_registry: ProviderRegistry | None = None) -> FastAPI:
    """Compatibility entry point; assembly and routes live in dedicated modules."""
    return create_application(settings or Settings.from_env(), state, registry, provider_registry)
