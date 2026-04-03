import os
path = "app/services/pipeline_service.py"
c = open(path, "r", encoding="utf-8").read()

old_list = """    async def list_pipelines(self, user_id: int, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        page_size = min(page_size, 100)
        offset = (page - 1) * page_size
        total = await pipeline_repo.count_by_user(self.db, user_id)
        items = await pipeline_repo.list_by_user(self.db, user_id, offset, page_size)
        return {"items": items, "total": total, "page": page, "page_size": page_size}"""

new_list = """    async def list_pipelines(self, user_id: int, offset: int = 0, limit: int = 20):
        limit = min(limit, 100)
        total = await pipeline_repo.count_by_user(self.db, user_id)
        items = await pipeline_repo.list_by_user(self.db, user_id, offset, limit)
        return items, total"""

c = c.replace(old_list, new_list)

old_list_exec = """    async def list_executions(self, pipeline_id: int, user_id: int) -> List[Any]:
        await self.get_pipeline( pipeline_id, user_id)
        execs = await execution_repo.list_by_pipeline(self.db, pipeline_id)
        out = []
        from app.schemas import ExecutionOut
        for ex in execs:
            d = ExecutionOut.model_validate(ex)
            if ex.output_s3_key and ex.status in ("success", "partial"):
                try: d.download_url = await get_signed_url_async(ex.output_s3_key, settings.S3_BUCKET_OUTPUT)
                except: pass
            out.append(d)
        return out"""

new_list_exec = """    async def list_executions(self, pipeline_id: int, user_id: int):
        await self.get_pipeline( pipeline_id, user_id)
        execs = await execution_repo.list_by_pipeline(self.db, pipeline_id)
        for ex in execs:
            if ex.output_s3_key and ex.status in ("success", "partial"):
                try: ex.download_url = await get_signed_url_async(ex.output_s3_key, settings.S3_BUCKET_OUTPUT)
                except: pass
        return execs"""

c = c.replace(old_list_exec, new_list_exec)

old_get_exec = """    async def get_execution(self, pipeline_id: int, execution_id: int, user_id: int) -> Any:
        await self.get_pipeline( pipeline_id, user_id)
        ex = await execution_repo.get_by_pipeline(self.db, pipeline_id, execution_id)
        if not ex:
            raise NotFoundError("Execution not found")
        from app.schemas import ExecutionOut
        d = ExecutionOut.model_validate(ex)
        if ex.output_s3_key and ex.status in ("success", "partial"):
            try: d.download_url = await get_signed_url_async(ex.output_s3_key, settings.S3_BUCKET_OUTPUT)
            except: pass
        return d"""

new_get_exec = """    async def get_execution(self, pipeline_id: int, execution_id: int, user_id: int) -> Any:
        await self.get_pipeline( pipeline_id, user_id)
        ex = await execution_repo.get_by_pipeline(self.db, pipeline_id, execution_id)
        if not ex:
            raise NotFoundError("Execution not found")
        if ex.output_s3_key and ex.status in ("success", "partial"):
            try: ex.download_url = await get_signed_url_async(ex.output_s3_key, settings.S3_BUCKET_OUTPUT)
            except: pass
        return ex"""

c = c.replace(old_get_exec, new_get_exec)

open(path, "w", encoding="utf-8").write(c)

