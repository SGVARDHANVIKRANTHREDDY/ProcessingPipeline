"""Security tests for auth hardening — lockout, brute force protection."""
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
class TestAccountLockout:
    async def test_lockout_after_max_failed_attempts(self, client):
        """Account must lock after MAX_LOGIN_ATTEMPTS failed attempts."""
        # Register user
        await client.post("/api/v1/auth/register", json={"email": "lockout@test.com", "password": "LockOut123"})

        # Fail 5 times
        for i in range(5):
            resp = await client.post("/api/v1/auth/login", json={"email": "lockout@test.com", "password": "WrongPass1"})
            if i < 4:
                assert resp.status_code == 401
            else:
                # 5th attempt may already trigger lockout
                assert resp.status_code in (401, 429)

        # Next attempt should be blocked
        resp = await client.post("/api/v1/auth/login", json={"email": "lockout@test.com", "password": "LockOut123"})
        assert resp.status_code == 429
        assert "locked" in resp.json()["detail"].lower()

    async def test_wrong_password_does_not_reveal_user_existence(self, client):
        """Non-existent user and wrong password must return identical errors."""
        resp_nonexistent = await client.post("/api/v1/auth/login",
                                              json={"email": "nobody@doesnotexist.com", "password": "Pass123"})
        resp_wrong_pass  = await client.post("/api/v1/auth/login",
                                              json={"email": "admin@test.com", "password": "WrongPass999"})
        # Both should return 401 with same message
        assert resp_nonexistent.status_code == 401
        assert resp_wrong_pass.status_code == 401
        # Same detail message (no user enumeration)
        assert resp_nonexistent.json()["detail"] == resp_wrong_pass.json()["detail"]

    async def test_expired_token_rejected(self, client):
        import jwt, time
        from app.core.config import get_settings
        s = get_settings()
        # Create an expired token
        payload = {"sub": "1", "type": "access", "exp": int(time.time()) - 3600}
        expired_token = jwt.encode(payload, s.SECRET_KEY, algorithm=s.ALGORITHM)
        resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    async def test_tampered_token_rejected(self, client):
        """A JWT with wrong signature must be rejected."""
        resp = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.FAKESIGNATURE"})
        assert resp.status_code == 401

    async def test_refresh_token_cannot_access_api(self, client):
        """Refresh token must not work as access token."""
        reg = await client.post("/api/v1/auth/register", json={"email": "refresh_test@test.com", "password": "RefTest123"})
        refresh_token = reg.json()["refresh_token"]
        resp = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})
        assert resp.status_code == 401


@pytest.mark.asyncio
class TestPasswordStrength:
    async def test_rejects_password_without_uppercase(self, client):
        resp = await client.post("/api/v1/auth/register",
                                  json={"email": "pw@test.com", "password": "nouppercase1"})
        assert resp.status_code == 422

    async def test_rejects_password_without_digit(self, client):
        resp = await client.post("/api/v1/auth/register",
                                  json={"email": "pw@test.com", "password": "NoDigitHere"})
        assert resp.status_code == 422

    async def test_rejects_short_password(self, client):
        resp = await client.post("/api/v1/auth/register",
                                  json={"email": "pw@test.com", "password": "Sh0rt"})
        assert resp.status_code == 422

    async def test_accepts_strong_password(self, client):
        resp = await client.post("/api/v1/auth/register",
                                  json={"email": "strong_pw@test.com", "password": "StrongPass123"})
        assert resp.status_code == 201
