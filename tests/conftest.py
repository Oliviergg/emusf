"""Fixtures partagées pour les tests pytest."""

import pytest
from emusf import PgTestOrg
from emusf.config import DSN


@pytest.fixture()
def org():
    """PgTestOrg avec cleanup automatique."""
    o = PgTestOrg(DSN, schema="test")
    o.truncate_all()
    yield o
    o.truncate_all()
    o.conn.close()
