from app.deps import Ctx
from app.models import ActivityLog


def log(ctx: Ctx, action: str, entity_type: str, entity_id: str | None, summary: str, **meta) -> None:
    ctx.db.add(
        ActivityLog(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary[:300],
            meta=meta,
        )
    )
