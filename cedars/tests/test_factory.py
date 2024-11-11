"""
Pytests
"""


def test_config(cedars_app):
    with cedars_app.app_context():
        assert cedars_app.testing is True
