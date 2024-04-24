import pytest
from app import db
from bs4 import BeautifulSoup

def test_register(client):
    assert client.get("/auth/register").status_code == 200
    response = client.post(
        "/auth/register", data={"username": "a", "password": "a"}
    )
    # assert response.headers["Location"] == "/auth/login"

    # with app.app_context():
    #     assert (
    #         db.get_project_users() is not None
    #     )


def get_flash_message(response):
    soup = BeautifulSoup(response.data, 'html.parser')
    flash_message = soup.find('div', {'class': 'alert'})
    return flash_message.text.strip() if flash_message else None


@pytest.mark.parametrize(('username', 'password', 'confirm_password', 'message'), (
    ('', '', '', 'Username and password are required.'),
    # ('a', '', b'Username and password are required.'),
    # ('test', 'test', b'Username already exists.'),
))
def test_register_validate_input(client, username, password, confirm_password, message):
    response = client.post(
        '/auth/register',
        data={'username': username, 'password': password, 'confirm_password': confirm_password  }
    )
    assert message == get_flash_message(response)