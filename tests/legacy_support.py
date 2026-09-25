"""Test-only import facade preserving the original regression fixtures.

Production modules never import this helper. New tests should import the module
under test directly; keeping this facade avoids rewriting the old assertions.
"""
from __future__ import annotations

import http
import time
import urllib

from options_panel.config import APP_ID, MAX_BACKOFF
from options_panel.domain.calculations import *  # noqa: F403
from options_panel.logging import LOGGER, log_event
from options_panel.providers.binance import *  # noqa: F403
from options_panel.runtime.refresher import Refresher
from options_panel.runtime.snapshot import DashboardState
