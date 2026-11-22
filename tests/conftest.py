import os
os.environ.setdefault("DD_HTTP_MODE", "replay")
os.environ.setdefault("MAIL_PROVIDER", "mailpit")
import pytest
from datadesigner.core.context import make_context
from datadesigner.core.stores import Stores
NOW = "2026-11-22T16:30:00+05:30"


@pytest.fixture
def ctx():
    return make_context(run_id="t", mode="replay", frozen_now=NOW, stores=Stores(":memory:"), sleep=lambda s: None)
