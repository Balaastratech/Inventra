"""
Test-wide safety net: config.email_enabled / vendor_email_enabled must
never be true by default in a test run, regardless of what a developer's
own submission/.env happens to have configured for local/demo use.

Without this, any test that runs the real graph reaches notify_* through
request_approval / finalize_blocked / finalize_no_action / finalize_needs_
information / execute_purchase, which would attempt a real Gmail send using
whatever credentials are sitting in .env -- exactly what happened once: a
full-suite run hit Gmail's "Daily user sending limit exceeded"
(SMTPDataError 550), which then cascaded into unrelated SQLite
PermissionErrors because the stuck SMTP call held a checkpoint connection
open past the next test's reset_business_state().

Tests that specifically want to exercise email (test_phase9_notifications.py,
test_phase3_email_approval.py, test_phase9_vendor_ordering.py) explicitly
flip it back on for just that test via their own fixture, which runs after
this one and wins for the duration of that test.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from submission.config import config


@pytest.fixture(autouse=True)
def _no_real_email_by_default(monkeypatch):
    safe_config = replace(config, email_enabled=False, vendor_email_enabled=False)

    import submission.graph.nodes as nodes_module
    import submission.notifications.email as email_module
    import submission.notifications.vendor_email as vendor_email_module

    monkeypatch.setattr(nodes_module, "config", safe_config)
    monkeypatch.setattr(email_module, "config", safe_config)
    monkeypatch.setattr(vendor_email_module, "config", safe_config)
    yield
