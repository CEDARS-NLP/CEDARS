import pytest
from app import db

def test_register(client, app):
    assert client.get("/auth/register").status_code == 200
    response = client.post(
        "/auth/register", data={"username": "a", "password": "a"}
    )
    assert response.headers["Location"] == "/auth/login"

    with app.app_context():
        assert (
            db.get_project_users() is not None
        )


@pytest.mark.parametrize(('username', 'password', 'message'), (
    ('', '', b'Username and password are required.'),
    ('a', '', b'Username and password are required.'),
    # ('test', 'test', b'Username already exists.'),
))
def test_register_validate_input(client, username, password, message):
    response = client.post(
        '/auth/register',
        data={'username': username, 'password': password}
    )

    assert message in response.data