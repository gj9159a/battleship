from fastapi import APIRouter

from app.rulesets import list_rulesets

router = APIRouter(prefix="/api/v1/rulesets", tags=["rulesets"])


@router.get("")
async def get_rulesets() -> list[dict]:
    rulesets = list_rulesets()
    return [
        {
            "id": ruleset.id,
            "name": ruleset.name,
            "board_size": ruleset.board_size,
            "fleet": list(ruleset.fleet),
            "placement_no_touch": ruleset.placement_no_touch,
            "extra_turn_on_hit": ruleset.extra_turn_on_hit,
        }
        for ruleset in rulesets
    ]
