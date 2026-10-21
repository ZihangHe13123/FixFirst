"""Consumer/provider responsibility is evidence-based, not tied to a project name."""

from fixfirst.workspace import build_view
from test_dependency_advice import recorded_session


def consumer_session(tmp_path, *, caller="flask_sqlalchemy", version="2.2", owners=None):
    return recorded_session(tmp_path, f"Flask-SQLAlchemy=={version}\nFlask>=3\nSQLAlchemy>=2\n",
        [{"name": "Flask-SQLAlchemy", "version": version, "requires": ["Flask>=0.10", "SQLAlchemy>=0.8"]},
         {"name": "Flask", "version": "3.1.3", "requires": []},
         {"name": "SQLAlchemy", "version": "2.0.44", "requires": []}],
        f'File "/venv/lib/python3.12/site-packages/{caller}/__init__.py", line 14, in <module>\n'
        "    from flask import _app_ctx_stack\n"
        "ImportError: cannot import name '_app_ctx_stack' from 'flask'\n",
        {"flask": ["Flask"], "flask_sqlalchemy": ["Flask-SQLAlchemy"] if owners is None else owners,
         "sqlalchemy": ["SQLAlchemy"]})


def test_known_old_consumer_is_changed_instead_of_downgrading_provider(tmp_path):
    session = consumer_session(tmp_path)
    first = build_view(session)["steps"][0]
    action = next(a for a in session.actions if a.action_id == first["id"])
    assert action.check == "dependency_resolve"
    assert action.targets[0] == "flask-sqlalchemy"
    assert ">=3.1" in action.targets[1] and "<4" in action.targets[1]
    assert "flask_sqlalchemy/__init__.py:14" in action.explanation
    assert not any(a.check == "version_search" for a in session.actions)
    assert not any(a.command and any(word.startswith("Flask<") for word in a.command) for a in session.actions)


def test_another_consumer_does_not_authorize_flask_sqlalchemy_upgrade(tmp_path):
    session = consumer_session(tmp_path, caller="unrelated_extension")
    assert not any(a.targets and a.targets[0] == "flask-sqlalchemy" for a in session.actions)


def test_current_consumer_does_not_get_legacy_migration(tmp_path):
    session = consumer_session(tmp_path, version="3.1.1")
    assert not any("migrate-consumer" in a.action_id for a in session.actions)


def test_ambiguous_distribution_ownership_does_not_authorize_migration(tmp_path):
    session = consumer_session(tmp_path, owners=["Flask-SQLAlchemy", "unrelated-distribution"])
    assert not any("migrate-consumer" in a.action_id for a in session.actions)


def test_project_shadow_of_provider_is_not_assumed_to_be_the_installed_release(tmp_path):
    import json
    from fixfirst.evidence import project_index
    from fixfirst.models import Run
    from fixfirst.runner import environment_id
    from fixfirst.service import ingest

    session = consumer_session(tmp_path)
    # The helper records declarations only. Include the local module inventory
    # that a real project scan also supplies.
    project = {**project_index(session)[1], "local_modules": [{"name": "flask", "path": "flask.py"}]}
    ingest(session, [Run(tool="project", environment_id=environment_id(session.target_python),
                        exit_code=0, scope="declarations:project", stdout=json.dumps(project))])
    assert not any("migrate-consumer" in a.action_id for a in session.actions)
    assert next(i for i in session.issues if i.tool == "pytest_run").diagnosis == "local_module"


def test_relocated_import_preserves_other_names_and_local_alias():
    from fixfirst.migration_advice import relocated_import
    entry = {"module": "flask_sqlalchemy", "name": "Model", "replacement_import": "flask_sqlalchemy.model.Model"}
    assert relocated_import("from flask_sqlalchemy import SQLAlchemy, Model as Base", entry) == (
        "from flask_sqlalchemy import SQLAlchemy\nfrom flask_sqlalchemy.model import Model as Base")
    assert relocated_import("from own_models import Model", entry) is None
    assert relocated_import("from flask_sqlalchemy import *", entry) is None


def test_project_import_migration_supplies_the_exact_recorded_source_edit(tmp_path):
    session = recorded_session(tmp_path, "Flask-SQLAlchemy>=3.1\n",
        [{"name": "Flask-SQLAlchemy", "version": "3.1.1", "requires": []}],
        'File "app.py", line 9, in <module>\n'
        '    from flask_sqlalchemy import SQLAlchemy, Model as Base\n'
        "ImportError: cannot import name 'Model' from 'flask_sqlalchemy'\n",
        {"flask_sqlalchemy": ["Flask-SQLAlchemy"]})
    first = build_view(session)["steps"][0]
    assert "app.py:9: replace `from flask_sqlalchemy import SQLAlchemy, Model as Base`" in first["explanation"]
    assert "from flask_sqlalchemy.model import Model as Base" in first["explanation"]
