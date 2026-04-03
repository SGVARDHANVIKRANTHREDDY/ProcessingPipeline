import os
import re
path = "app/services/admin_service.py"
c = open(path, "r", encoding="utf-8").read()

c = c.replace(
"async def list_dlq(self, admin_id: int, page: int, replayed: bool, suppressed: bool, request_for_audit: Any = None) -> Dict[str, Any]:",
"async def list_dlq(self, admin_id: int, offset: int, limit: int, replayed: bool, suppressed: bool, request_for_audit: Any = None):"
)
c = c.replace(
"        offset = (page - 1) * 20",
""
)
c = c.replace(
"        items = await admin_repo.list_dlq(self.db, replayed, suppressed, offset, 20)",
"        items = await admin_repo.list_dlq(self.db, replayed, suppressed, offset, limit)"
)
c = c.replace(
"        total = await admin_repo.count_dlq(self.db, replayed, suppressed)",
"        total = await admin_repo.count_dlq(self.db, replayed, suppressed)"
)

# Replace the return dict with return items, total
return_dlq = """        return {
            "items": [{"id": e.id, "task_name": e.task_name, "queue": e.queue, "error": e.error[:200],
                       "retry_count": e.retry_count, "replay_count": e.replay_count, "suppressed": e.suppressed,
                       "created_at": e.created_at.isoformat()} for e in items], 
            "total": total
        }"""
c = c.replace(return_dlq, "        return items, total")

c = c.replace(
"async def query_audit(self, admin_id: int, page: int, action: Optional[str], user_id: Optional[int], resource_type: Optional[str], request_for_audit: Any = None) -> Dict[str, Any]:",
"async def query_audit(self, admin_id: int, offset: int, limit: int, action: Optional[str], user_id: Optional[int], resource_type: Optional[str], request_for_audit: Any = None):"
)
c = c.replace(
"        offset = (page - 1) * 50",
""
)
c = c.replace(
"        items = await admin_repo.list_audit(self.db, action, user_id, resource_type, offset, 50)",
"        items = await admin_repo.list_audit(self.db, action, user_id, resource_type, offset, limit)"
)

return_audit = """        return {
            "items": [{"id": e.id, "global_seq": e.global_seq, "user_id": e.user_id, "action": e.action,
                       "resource_type": e.resource_type, "resource_id": e.resource_id, "ip_address": e.ip_address,
                       "detail": e.detail, "created_at": e.created_at.isoformat()} for e in items],
            "total": total
        }"""
c = c.replace(return_audit, "        return items, total")


c = c.replace(
"async def list_failed_jobs(self, page: int) -> Dict[str, Any]:",
"async def list_failed_jobs(self, offset: int, limit: int):"
)

c = c.replace(
"        total = await admin_repo.count_failed_jobs(self.db)",
"        total = await admin_repo.count_jobs_by_status(self.db, \"failed\")"
)
c = c.replace(
"        items = await admin_repo.list_failed_jobs(self.db, offset, 20)",
"        items = await admin_repo.list_jobs_by_status(self.db, \"failed\", offset, limit)"
)

return_jobs = """        return {
            "items": [{"id": j.id, "job_type": j.job_type, "error": j.error, "created_at": j.created_at.isoformat()} for j in items],
            "total": total
        }"""
c = c.replace(return_jobs, "        return items, total")

# Also need to fix detail logic logging in admin_service where we used `page` 
c = c.replace('detail={"page": page}', 'detail={"offset": offset, "limit": limit}')

open(path, "w", encoding="utf-8").write(c)

