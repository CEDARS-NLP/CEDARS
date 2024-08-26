import pytest
from bs4 import BeautifulSoup


def get_flash_message(response):
    soup = BeautifulSoup(response.data, 'html.parser')
    flash_message = soup.find('div', {'class': 'alert'})
    return flash_message.text.strip() if flash_message else None


def test_register(cedars_app, db, client):

    assert client.get("/auth/register").status_code == 200

    client.post(
        "/auth/register", data={"username": "a",
                                "password": "AAbb20**"}
    )
    db.get_user("a") is not None


@pytest.mark.parametrize(('username', 'password', 'confirm_password', 'message'), (
    ('', '', '', 'Username and password are required.'),
    # ('a', '', b'Username and password are required.'),
    # ('test', 'test', b'Username already exists.'),
))
def test_register_validate_input(cedars_app, client, username, password, confirm_password, message):
    response = client.post(
        '/auth/register',
        data={'username': username,
              'password': password,
              'confirm_password': confirm_password,
              'isadmin': False}
    )
    assert message == get_flash_message(response)
