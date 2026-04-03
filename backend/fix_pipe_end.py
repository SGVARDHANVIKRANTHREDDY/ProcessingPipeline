import os
path = "app/api/v1/endpoints/pipelines.py"
c = open(path, "r", encoding="utf-8").read()

c = c.replace(
"async def list_pipelines(page: int = 1, page_size: int = 20,\n                           user=Depends(get_current_user), service: PipelineService = Depends(get_pipeline_read_service)):\n    return await service.list_pipelines(user.id, page, page_size)",
"async def list_pipelines(page: int = 1, page_size: int = 20,\n                           user=Depends(get_current_user), service: PipelineService = Depends(get_pipeline_read_service)):\n    offset = (page - 1) * page_size\n    items, total = await service.list_pipelines(user.id, offset, page_size)\n    return {\"items\": items, \"total\": total, \"page\": page, \"page_size\": page_size}"
)

c = c.replace(
"async def list_executions(pipeline_id: int, user=Depends(get_current_user), service: PipelineService = Depends(get_pipeline_read_service)):\n    return await service.list_executions(pipeline_id, user.id)",
"async def list_executions(pipeline_id: int, user=Depends(get_current_user), service: PipelineService = Depends(get_pipeline_read_service)):\n    execs = await service.list_executions(pipeline_id, user.id)\n    return {\"items\": execs}"
)

open(path, "w", encoding="utf-8").write(c)

