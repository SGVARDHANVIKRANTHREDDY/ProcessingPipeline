"""Integration tests for pipeline endpoints."""
import pytest


@pytest.mark.asyncio
class TestPipelineCRUD:
    async def test_create_pipeline(self, client, auth_headers):
        resp = await client.post("/api/v1/pipelines", headers=auth_headers, json={
            "name": "Test Pipeline",
            "steps": [{"action": "drop_nulls", "params": {"columns": [], "method": "", "threshold": None, "order": ""}}],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Pipeline"
        assert len(data["steps"]) == 1

    async def test_list_pipelines(self, client, auth_headers):
        await client.post("/api/v1/pipelines", headers=auth_headers, json={"name": "P1", "steps": []})
        await client.post("/api/v1/pipelines", headers=auth_headers, json={"name": "P2", "steps": []})
        resp = await client.get("/api/v1/pipelines", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["total"] >= 2

    async def test_get_pipeline(self, client, auth_headers):
        create_resp = await client.post("/api/v1/pipelines", headers=auth_headers, json={"name": "GetMe", "steps": []})
        pid = create_resp.json()["id"]
        resp = await client.get(f"/api/v1/pipelines/{pid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "GetMe"

    async def test_update_pipeline(self, client, auth_headers):
        create_resp = await client.post("/api/v1/pipelines", headers=auth_headers, json={"name": "Old", "steps": []})
        pid = create_resp.json()["id"]
        resp = await client.patch(f"/api/v1/pipelines/{pid}", headers=auth_headers, json={"name": "New"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "New"

    async def test_delete_pipeline(self, client, auth_headers):
        create_resp = await client.post("/api/v1/pipelines", headers=auth_headers, json={"name": "Delete", "steps": []})
        pid = create_resp.json()["id"]
        resp = await client.delete(f"/api/v1/pipelines/{pid}", headers=auth_headers)
        assert resp.status_code == 204
        get_resp = await client.get(f"/api/v1/pipelines/{pid}", headers=auth_headers)
        assert get_resp.status_code == 404

    async def test_other_user_cannot_access(self, client):
        # Register second user
        reg = await client.post("/api/v1/auth/register", json={"email": "other@test.com", "password": "OtherPass1"})
        other_token = reg.json()["access_token"]
        other_headers = {"Authorization": f"Bearer {other_token}"}

        # First user creates pipeline
        first_reg = await client.post("/api/v1/auth/register", json={"email": "first_u@test.com", "password": "FirstPass1"})
        first_headers = {"Authorization": f"Bearer {first_reg.json()['access_token']}"}
        create_resp = await client.post("/api/v1/pipelines", headers=first_headers, json={"name": "Private", "steps": []})
        pid = create_resp.json()["id"]

        # Second user cannot access
        resp = await client.get(f"/api/v1/pipelines/{pid}", headers=other_headers)
        assert resp.status_code == 404


@pytest.mark.asyncio
class TestTranslate:
    async def test_translate_valid_prompt(self, client, auth_headers):
        from unittest.mock import patch
        mock_response = {
            "steps": [{"action": "drop_nulls", "params": {"columns": [], "method": "", "threshold": None, "order": ""}}]
        }
        with patch("app.services.pipeline_service.translate_to_steps", return_value=mock_response):
            resp = await client.post("/api/v1/pipelines/translate", headers=auth_headers,
                                      json={"prompt": "remove missing values"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["steps"]) == 1
        assert data["steps"][0]["action"] == "drop_nulls"

    async def test_translate_unknown_action_rejected(self, client, auth_headers):
        from unittest.mock import patch
        mock_response = {
            "steps": [{"action": "evil_action", "params": {}}]
        }
        with patch("app.services.pipeline_service.translate_to_steps", return_value=mock_response):
            resp = await client.post("/api/v1/pipelines/translate", headers=auth_headers,
                                      json={"prompt": "do something evil"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["steps"]) == 0
        assert len(data["rejected"]) == 1

    async def test_translate_unauthenticated(self, client):
        resp = await client.post("/api/v1/pipelines/translate", json={"prompt": "remove nulls"})
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestValidationErrors:
    async def test_create_pipeline_invalid_action(self, client, auth_headers):
        resp = await client.post("/api/v1/pipelines", headers=auth_headers, json={
            "name": "Bad",
            "steps": [{"action": "hack_db", "params": {}}],
        })
        assert resp.status_code == 422   # Pydantic rejects it before DB

    async def test_create_pipeline_empty_name(self, client, auth_headers):
        resp = await client.post("/api/v1/pipelines", headers=auth_headers, json={"name": "", "steps": []})
        assert resp.status_code == 422
