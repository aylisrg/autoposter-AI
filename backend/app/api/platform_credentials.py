"""Platform credentials CRUD (list + delete).

The actual write-path is OAuth (`/api/meta/oauth/*`) or the manual paste
endpoint (`/api/meta/credentials`). This module just provides read / delete
for the dashboard Platforms page.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.db.models import PlatformCredential
from app.schemas import PlatformCredentialOut

router = APIRouter(prefix="/api/platform-credentials", tags=["platforms"])


@router.get("", response_model=list[PlatformCredentialOut])
def list_credentials(db: Session = Depends(get_session)) -> list[PlatformCredential]:
    return (
        db.query(PlatformCredential)
        .order_by(PlatformCredential.updated_at.desc())
        .all()
    )


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credential(credential_id: int, db: Session = Depends(get_session)) -> None:
    row = db.get(PlatformCredential, credential_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    db.delete(row)
    db.commit()
