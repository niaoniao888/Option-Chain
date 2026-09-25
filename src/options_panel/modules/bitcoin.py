from __future__ import annotations

from dataclasses import dataclass

from options_panel.content.guide_store import GuideStore
from options_panel.runtime.snapshot import DashboardState


@dataclass
class BitcoinModule:
    state: DashboardState
    guide: GuideStore
