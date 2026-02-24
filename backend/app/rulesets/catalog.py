from .models import Ruleset

CLASSIC_V1 = Ruleset(
    id="classic_v1",
    name="Classic Battleship v1",
    board_size=10,
    fleet=(4, 3, 3, 2, 2, 2, 1, 1, 1, 1),
    placement_no_touch=True,
    extra_turn_on_hit=True,
)

_RULESETS: dict[str, Ruleset] = {
    CLASSIC_V1.id: CLASSIC_V1,
}


def get_ruleset(ruleset_id: str) -> Ruleset:
    try:
        return _RULESETS[ruleset_id]
    except KeyError as exc:
        raise KeyError(f"Unknown ruleset_id: {ruleset_id}") from exc


def list_rulesets() -> list[Ruleset]:
    return list(_RULESETS.values())
