"""Optional local SQL integration; each test owns a new disposable database."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from remind.evals import operational_case, dataset


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("variable", ["REMIND_TEST_POSTGRES_URL", "REMIND_TEST_MYSQL_URL"])
async def test_local_sql_workflow_contract(variable, tmp_path):
    configured = os.environ.get(variable)
    if not configured:
        pytest.skip(f"Set {variable} for optional local database checks")
    original = make_url(configured)
    if original.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.skip("Integration checks are restricted to local databases")
    name = "remind_eval_" + uuid4().hex
    administration = create_engine(original, isolation_level="AUTOCOMMIT")
    with administration.connect() as connection:
        connection.execute(text(f"CREATE DATABASE {name}"))
    selector = original.set(database=name).render_as_string(hide_password=False)
    try:
        data = dataset()
        case = next(c for c in data["operational"] if c["id"] == "architecture.lifecycle")
        family = next(f for f in data["families"] if f["id"] == "architecture")
        assert (await operational_case(case, family, "python", selector, tmp_path))["passed"]
    finally:
        with administration.connect() as connection:
            connection.execute(text(f"DROP DATABASE {name}"))
        administration.dispose()
