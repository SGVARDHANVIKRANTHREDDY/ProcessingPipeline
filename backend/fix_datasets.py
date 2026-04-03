import os
import re
path = "app/api/v1/endpoints/datasets.py"
c = open(path, "r", encoding="utf-8").read()

c = c.replace("from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request", "from fastapi import APIRouter, Depends, UploadFile, File, Form, Request\nfrom app.core.exceptions import ValidationError, DomainError")

# Replace HTTPExceptions with domain exceptions
c = re.sub(r'raise HTTPException\(status_code*=[^,]+,\s*detail=(.*?)\)', r'raise ValidationError(\1)', c)
c = re.sub(r'raise HTTPException\(\d+,\s*(.*?)\)', r'raise ValidationError(\1)', c)
open(path, "w", encoding="utf-8").write(c)

