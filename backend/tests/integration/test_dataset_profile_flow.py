import pytest
from httpx import AsyncClient
import io
from app.models import Dataset
from unittest.mock import patch, MagicMock

@pytest.fixture
def sample_csv():
    # Provide a simple CSV file
    csv_content = b"a,b,c\n1,2,A\n4,5,B\n7,8,A\n10,11,C\n"
    return {"file": ("test.csv", io.BytesIO(csv_content), "text/csv")}

@pytest.mark.asyncio
async def test_dataset_profile_flow(client: AsyncClient, token_headers: dict, db_session, sample_csv):
    # 1. Upload dataset
    upload_resp = await client.post("/api/v1/datasets/upload", files=sample_csv, headers=token_headers)
    assert upload_resp.status_code == 202
    dataset_id = upload_resp.json()["id"]

    # 2. Trigger profiling
    with patch("app.api.v1.endpoints.datasets.run_profiling_job") as mock_run:
        from app.services.profiler import run_profiling_job
        profile_resp = await client.post(f"/api/v1/datasets/{dataset_id}/profile", headers=token_headers)
        
        assert profile_resp.status_code == 202
        assert profile_resp.json()["status"] == "queued"
        
        # Directly call run_profiling_job to wait for it (avoid async task skipping in test context)
        # However, due to S3 mock limits in conftest, we will mock S3Client just in case or use fixture
        
        # In a fully integrated environment, we wait for DB updates:
        # We will directly run profile so DB is updated
        db = db_session
        from app.services.storage import S3Client
        
        async def mock_download(*args, **kwargs):
            return b"a,b,c\n1,2,A\n4,5,B\n7,8,A\n10,11,C\n"

        with patch.object(S3Client, "download_file", mock_download):
            from app.services.profiler import profile_dataset
            s3_client = S3Client()
            await profile_dataset(dataset_id, db, s3_client)

    # 3. Retrieve profile
    get_resp = await client.get(f"/api/v1/datasets/{dataset_id}/profile", headers=token_headers)
    
    assert get_resp.status_code == 200
    res_json = get_resp.json()
    assert res_json["dataset_id"] == dataset_id
    assert "summary" in res_json
    assert res_json["summary"]["health_score"] == 100
    assert len(res_json["columns"]) == 3
