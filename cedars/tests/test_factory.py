"""
Pytests
"""


def test_config(app):
    with app.app_context():
        assert app.testing  


def test_index(client):
    response = client.get("/")
    assert response.status_code == 302
    assert b"auth/login" in response.data