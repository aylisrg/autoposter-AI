"""Content plans (M1).

Endpoints:
    POST   /api/plans                     — create empty plan
    POST   /api/plans/generate            — create + populate via PlannerAgent
    GET    /api/plans                     — list
    GET    /api/plans/{id}                — detail with slots
    PATCH  /api/plans/{id}                — rename/status
    DELETE /api/plans/{id}
    POST   /api/plans/{id}/chat           — conversational refinement
    POST   /api/plans/{id}/slots          — manual slot add
    PATCH  /api/plans/slots/{slot_id}     — edit (drag-n-drop uses this)
    DELETE /api/plans/slots/{slot_id}
    POST   /api/plans/slots/{slot_id}/generate-post
                                          — spin the slot's post_type + topic_hint
                                            through `generate_post`, link the Post.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.agents.planner import (
    PlanProposal,
    RefinementResult,
    SlotProposal,
    propose_plan,
    refine_plan,
)
from app.ai.content import generate_post
from app.db import get_session
from app.db.models import (
    BusinessProfile,
    ContentPlan,
    PlanSlot,
    PlanStatus,
    Post,
    PostStatus,
    SlotStatus,
)
from app.schemas import (
    ContentPlanOut,
    ContentPlanPatch,
    PlanChatRequest,
    PlanChatResponse,
    PlanGenerateRequest,
    PlanSlotIn,
    PlanSlotOut,
    PlanSlotPatch,
    SlotGeneratePostResponse,
)

log = logging.getLogger("api.plans")

router = APIRouter(prefix="/api/plans", tags=["plans"])


def _eager(db: Session, plan_id: int) -> ContentPlan | None:
    return (
        db.query(ContentPlan)
        .options(selectinload(ContentPlan.slots))
        .filter(ContentPlan.id == plan_id)
        .first()
    )


def _require_profile(db: Session) -> BusinessProfile:
    bp = db.query(BusinessProfile).order_by(BusinessProfile.id.asc()).first()
    if bp is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Business profile must be set before planning.",
        )
    return bp


def _apply_slot_proposals(
    db: Session, plan: ContentPlan, slots: list[SlotProposal], replace: bool
) -> None:
    if replace:
        for existing in list(plan.slots):
            db.delete(existing)
        db.flush()
    for s in slots:
        db.add(
            PlanSlot(
                plan_id=plan.id,
                scheduled_for=s.scheduled_for,
                post_type=s.post_type,
                topic_hint=s.topic_hint,
                rationale=s.rationale,
                status=SlotStatus.PLANNED,
            )
        )


@router.get("", response_model=list[ContentPlanOut])
def list_plans(
    status_filter: PlanStatus | None = None,
    db: Session = Depends(get_session),
) -> list[ContentPlan]:
    q = db.query(ContentPlan).options(selectinload(ContentPlan.slots))
    if status_filter is not None:
        q = q.filter(ContentPlan.status == status_filter)
    return q.order_by(ContentPlan.created_at.desc()).all()


@router.get("/{plan_id}", response_model=ContentPlanOut)
def get_plan(plan_id: int, db: Session = Depends(get_session)) -> ContentPlan:
    plan = _eager(db, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.post("", response_model=ContentPlanOut, status_code=status.HTTP_201_CREATED)
def create_plan_empty(
    payload: PlanGenerateRequest,
    db: Session = Depends(get_session),
) -> ContentPlan:
    """Create an empty plan (no AI). Slots are added manually later."""
    plan = ContentPlan(
        name=payload.name,
        goal=payload.goal,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status=PlanStatus.DRAFT,
        generation_params={},
        chat_history=[],
    )
    db.add(plan)
    db.commit()
    refreshed = _eager(db, plan.id)
    if refreshed is None:
        raise HTTPException(status_code=500, detail="Plan vanished after commit")
    return refreshed


@router.post(
    "/generate", response_model=ContentPlanOut, status_code=status.HTTP_201_CREATED
)
def generate_plan(
    payload: PlanGenerateRequest,
    db: Session = Depends(get_session),
) -> ContentPlan:
    """Kick the PlannerAgent and persist the resulting plan + slots."""
    bp = _require_profile(db)
    proposal: PlanProposal = propose_plan(
        business_profile=bp,
        start_date=payload.start_date,
        end_date=payload.end_date,
        goal=payload.goal,
    )
    plan = ContentPlan(
        name=payload.name,
        goal=payload.goal,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status=PlanStatus.DRAFT,
        generation_params={
            "posts_per_day": bp.posts_per_day,
            "post_type_ratios": bp.post_type_ratios,
            "posting_window": [
                bp.posting_window_start_hour,
                bp.posting_window_end_hour,
            ],
            "summary": proposal.summary,
        },
        chat_history=[
            {"role": "assistant", "content": proposal.summary or "Plan drafted."}
        ],
        generation_cost_usd=proposal.cost_usd,
    )
    db.add(plan)
    db.flush()
    _apply_slot_proposals(db, plan, proposal.slots, replace=False)
    db.commit()
    refreshed = _eager(db, plan.id)
    if refreshed is None:
        raise HTTPException(status_code=500, detail="Plan vanished after commit")
    return refreshed


@router.patch("/{plan_id}", response_model=ContentPlanOut)
def patch_plan(
    plan_id: int,
    payload: ContentPlanPatch,
    db: Session = Depends(get_session),
) -> ContentPlan:
    plan = db.get(ContentPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, key, value)
    db.commit()
    refreshed = _eager(db, plan.id)
    if refreshed is None:
        raise HTTPException(status_code=500, detail="Plan vanished after commit")
    return refreshed


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_id: int, db: Session = Depends(get_session)) -> None:
    plan = db.get(ContentPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    db.delete(plan)
    db.commit()


@router.post("/{plan_id}/chat", response_model=PlanChatResponse)
def chat_refine(
    plan_id: int,
    payload: PlanChatRequest,
    db: Session = Depends(get_session),
) -> PlanChatResponse:
    """User chats with Planner. Agent may update the slot list or just reply."""
    plan = _eager(db, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    bp = _require_profile(db)

    current_slots_dump = [
        {
            "scheduled_for": s.scheduled_for.isoformat(),
            "post_type": s.post_type.value,
            "topic_hint": s.topic_hint,
            "rationale": s.rationale,
        }
        for s in plan.slots
    ]

    result: RefinementResult = refine_plan(
        business_profile=bp,
        start_date=plan.start_date,
        end_date=plan.end_date,
        current_slots=current_slots_dump,
        chat_history=list(plan.chat_history or []),
        user_message=payload.message,
    )

    history = list(plan.chat_history or [])
    history.append({"role": "user", "content": payload.message})
    history.append({"role": "assistant", "content": result.reply})
    plan.chat_history = history
    plan.generation_cost_usd = (plan.generation_cost_usd or 0) + result.cost_usd

    if result.slots:
        _apply_slot_proposals(db, plan, result.slots, replace=True)

    db.commit()
    refreshed = _eager(db, plan.id)
    if refreshed is None:
        raise HTTPException(status_code=500, detail="Plan vanished after commit")
    return PlanChatResponse(
        reply=result.reply,
        updated=bool(result.slots),
        plan=ContentPlanOut.model_validate(refreshed),
    )


@router.post(
    "/{plan_id}/slots",
    response_model=PlanSlotOut,
    status_code=status.HTTP_201_CREATED,
)
def create_slot(
    plan_id: int,
    payload: PlanSlotIn,
    db: Session = Depends(get_session),
) -> PlanSlot:
    plan = db.get(ContentPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    slot = PlanSlot(
        plan_id=plan.id,
        scheduled_for=payload.scheduled_for,
        post_type=payload.post_type,
        topic_hint=payload.topic_hint,
        rationale=payload.rationale,
        notes=payload.notes,
        status=SlotStatus.PLANNED,
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot


@router.patch("/slots/{slot_id}", response_model=PlanSlotOut)
def patch_slot(
    slot_id: int,
    payload: PlanSlotPatch,
    db: Session = Depends(get_session),
) -> PlanSlot:
    slot = db.get(PlanSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Slot not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(slot, key, value)
    db.commit()
    db.refresh(slot)
    return slot


@router.delete("/slots/{slot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_slot(slot_id: int, db: Session = Depends(get_session)) -> None:
    slot = db.get(PlanSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Slot not found")
    db.delete(slot)
    db.commit()


@router.post(
    "/slots/{slot_id}/generate-post", response_model=SlotGeneratePostResponse
)
def generate_post_from_slot(
    slot_id: int,
    db: Session = Depends(get_session),
) -> SlotGeneratePostResponse:
    """Generate the post text for a slot and link it."""
    slot = db.get(PlanSlot, slot_id)
    if slot is None:
        raise HTTPException(status_code=404, detail="Slot not found")
    if slot.post_id is not None:
        existing_post = db.get(Post, slot.post_id)
        if existing_post is not None:
            raise HTTPException(
                status_code=409,
                detail="Slot already has a linked post. Delete it first to regenerate.",
            )

    bp = _require_profile(db)
    generated = generate_post(
        db=db,
        post_type=slot.post_type,
        business_profile=bp,
        topic_hint=slot.topic_hint,
        use_few_shot=True,
    )
    post = Post(
        post_type=slot.post_type,
        status=PostStatus.DRAFT,
        text=generated.text,
        generation_prompt=generated.user_prompt,
        generation_model=generated.model,
        generation_cost_usd=generated.cost_usd,
        scheduled_for=slot.scheduled_for,
    )
    db.add(post)
    db.flush()
    slot.post_id = post.id
    slot.status = SlotStatus.GENERATED
    db.commit()
    db.refresh(slot)
    db.refresh(post)
    return SlotGeneratePostResponse(
        slot=PlanSlotOut.model_validate(slot),
        post=_post_out(post),
    )


def _post_out(post: Post):
    """Late-imported PostOut to avoid circular import at module load."""
    from app.schemas import PostOut

    return PostOut.model_validate(post)
