import re

f = "app/services/pipeline_service.py"
content = open(f, encoding="utf-8").read()
# fix create_pipeline
content = re.sub(
    r'(await audit\(self\.db, AuditAction\.PIPELINE_CREATE.*?request=request_for_audit\)\n\s*)return pipe',
    r'\1return await self.get_pipeline(pipe.id, user_id)',
    content,
    flags=re.DOTALL
)
# fix update_pipeline
content = re.sub(
    r'(await audit\(self\.db, AuditAction\.PIPELINE_UPDATE.*?request=request_for_audit\)\n\s*)return pipe',
    r'\1return await self.get_pipeline(pipe.id, user_id)',
    content,
    flags=re.DOTALL
)
open(f, "w", encoding="utf-8").write(content)
