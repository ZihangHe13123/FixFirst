"""What iterating a result of a statement that returns no rows does in SQLAlchemy 1.3, 1.4 and 2.0.

A minimal in-memory SQLite check (Claude, 2026-09-30) for Codex's question about the records
development case: does 1.4's legacy result give an empty iterator for CREATE TABLE while 2.0 raises?
It also checks the returns_rows guard and two counterexamples that fail in every version (fetching
from a result that was closed explicitly, and fetchall on a statement that returns no rows).
Run it with each interpreter to compare; it prints one JSON object.

  VENV/bin/python experiments/core_diagnosis/round5_sqlalchemy_history.py [--records]

With --records (records installed in VENV, e.g. records==0.5.3 from PyPI) it also runs records'
own Database.query on a CREATE TABLE and an INSERT without consuming them, and a SELECT with all().
"""

import json
import os
import sys
import warnings

os.environ.setdefault("SQLALCHEMY_WARN_20", "1")  # 1.4 then reports planned 2.0 changes

import sqlalchemy  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402


def attempt(action):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            outcome = {"ok": True, "value": repr(action())[:80]}
        except Exception as error:  # the point is to record what each version raises
            outcome = {"ok": False, "error": f"{type(error).__module__}.{type(error).__name__}: "
                                             f"{str(error).splitlines()[0][:140]}"}
    notes = sorted({f"{type(w.message).__name__}: {str(w.message).splitlines()[0][:140]}" for w in caught})
    if notes:
        outcome["warnings"] = notes
    return outcome


def check(future: bool) -> dict:
    engine = create_engine("sqlite://", **({"future": True} if future else {}))
    found = {}
    with engine.connect() as connection:
        def ddl(name):
            return connection.execute(text(f"CREATE TABLE {name} (x INTEGER)"))

        result = ddl("t1")
        found["result_class"] = type(result).__name__
        found["returns_rows"] = attempt(lambda: result.returns_rows)
        found["iterate_ddl"] = attempt(lambda: list(result))
        second = ddl("t2")
        found["keys_ddl"] = attempt(lambda: list(second.keys()))
        # Creating an iterator or a generator over the result, without consuming it, is all that
        # records' Connection.query does for a statement unless fetchall=True.
        created = ddl("t5")
        found["iter_created_ddl"] = attempt(lambda: type(iter(created)).__name__)
        lazy = ddl("t6")
        found["records_like_generator_created"] = attempt(
            lambda: type((dict(zip(lazy.keys(), row)) for row in lazy)).__name__)
        third = ddl("t3")
        found["guarded_by_returns_rows"] = attempt(lambda: list(third) if third.returns_rows else [])
        # Counterexamples: these fail whatever the version.
        fourth = ddl("t4")
        found["fetchall_ddl"] = attempt(lambda: fourth.fetchall())
        closed = connection.execute(text("SELECT 1"))
        closed.close()
        found["iterate_closed_select"] = attempt(lambda: list(closed))
    return found


def check_records() -> dict:
    import records

    database = records.Database("sqlite://")
    return {
        "records_file": records.__file__.rsplit("site-packages/", 1)[-1],
        "query_create_table_not_consumed": attempt(lambda: type(database.query("CREATE TABLE t (x INTEGER)")).__name__),
        "query_insert_not_consumed": attempt(lambda: type(database.query("INSERT INTO t VALUES (1)")).__name__),
        "query_select_all": attempt(lambda: len(database.query("SELECT x FROM t").all())),
    }


def main() -> None:
    record = {"python": sys.version.split()[0], "sqlalchemy": sqlalchemy.__version__,
              "legacy": check(future=False)}
    if "--records" in sys.argv[1:]:
        record["records"] = check_records()
    if sqlalchemy.__version__.startswith("1.4"):
        record["future"] = check(future=True)
    print(json.dumps(record, indent=1))


if __name__ == "__main__":
    main()
