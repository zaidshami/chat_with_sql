import pytest
from django.urls import reverse

@pytest.mark.django_db
def test_chat_page(client):
    resp = client.get("/chat/")
    assert resp.status_code == 200
