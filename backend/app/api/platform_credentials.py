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
from app.services import token_refresh
from app.services.audit import audit_event

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
    platform_id = row.platform_id
    account_id = row.account_id
    db.delete(row)
    db.commit()
    audit_event(
        "deleted",
        "platform_credential",
        credential_id=credential_id,
        platform_id=platform_id,
        account_id=account_id,
    )


@router.post("/{credential_id}/refresh", response_model=PlatformCredentialOut)
def refresh_credential(
    credential_id: int, db: Session = Depends(get_session)
) -> PlatformCredential:
    """Force-refresh a Meta long-lived token on demand.

    Dashboard "Refresh now" button calls this. The scheduler auto-refreshes
    the same set daily, so this is just for users who want to exercise the
    path manually (e.g. right after connecting).
    """
    row = db.get(PlatformCredential, credential_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    try:
        return token_refresh.refresh_one(db, row)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface platform failures as 502
        raise HTTPException(
            status_code=502, detail=f"Meta refresh failed: {exc}"
        ) from exc
