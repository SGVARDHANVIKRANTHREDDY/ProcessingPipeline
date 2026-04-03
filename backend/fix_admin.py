import os
path = "app/api/v1/endpoints/admin.py"
c = open(path, "r", encoding="utf-8").read()
c = c.replace("from fastapi import APIRouter, Depends, HTTPException, Request", "from fastapi import APIRouter, Depends, Request\nfrom app.core.exceptions import ForbiddenError")
c = c.replace("raise HTTPException(403, \"Admin access required\")", "raise ForbiddenError(\"Admin access required\")")
c = c.replace("raise HTTPException(403, \"Super-admin access required for this operation\")", "raise ForbiddenError(\"Super-admin access required for this operation\")")
open(path, "w", encoding="utf-8").write(c)
