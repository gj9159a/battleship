from dataclasses import replace

from .models import Ruleset

CLASSIC_V1 = Ruleset(
    id="classic_v1",
    name="Classic Battleship v1",
    board_size=10,
    fleet=(5, 4, 3, 3, 2),
    placement_no_touch=False,
    extra_turn_on_hit=False,
)

_RULESETS: dict[str, Ruleset] = {
    CLASSIC_V1.id: CLASSIC_V1,
}
_ARCHIVED_RULESET_IDS: set[str] = set()
_ACTIVE_RULESET_ID: str = CLASSIC_V1.id


def is_ruleset_archived(ruleset_id: str) -> bool:
    return ruleset_id in _ARCHIVED_RULESET_IDS


def get_active_ruleset_id() -> str:
    return _ACTIVE_RULESET_ID


def get_ruleset(ruleset_id: str) -> Ruleset:
    try:
        return _RULESETS[ruleset_id]
    except KeyError as exc:
        raise KeyError(f"Unknown ruleset_id: {ruleset_id}") from exc


def list_rulesets(include_archived: bool = False) -> list[Ruleset]:
    if include_archived:
        return list(_RULESETS.values())
    return [ruleset for ruleset in _RULESETS.values() if ruleset.id not in _ARCHIVED_RULESET_IDS]


def create_ruleset(
    ruleset_id: str,
    name: str,
    board_size: int,
    fleet: tuple[int, ...],
    placement_no_touch: bool,
    extra_turn_on_hit: bool,
) -> Ruleset:
    if ruleset_id in _RULESETS:
        raise ValueError(f"ruleset already exists: {ruleset_id}")
    if board_size <= 0:
        raise ValueError("board_size must be positive")
    if not fleet or any(length <= 0 for length in fleet):
        raise ValueError("fleet must contain positive ship lengths")

    ruleset = Ruleset(
        id=ruleset_id,
        name=name,
        board_size=board_size,
        fleet=fleet,
        placement_no_touch=placement_no_touch,
        extra_turn_on_hit=extra_turn_on_hit,
    )
    _RULESETS[ruleset.id] = ruleset
    return ruleset


def clone_ruleset(source_ruleset_id: str, new_ruleset_id: str, new_name: str) -> Ruleset:
    source = get_ruleset(source_ruleset_id)
    return create_ruleset(
        ruleset_id=new_ruleset_id,
        name=new_name,
        board_size=source.board_size,
        fleet=source.fleet,
        placement_no_touch=source.placement_no_touch,
        extra_turn_on_hit=source.extra_turn_on_hit,
    )


def update_ruleset(
    ruleset_id: str,
    *,
    name: str | None = None,
    board_size: int | None = None,
    fleet: tuple[int, ...] | None = None,
    placement_no_touch: bool | None = None,
    extra_turn_on_hit: bool | None = None,
) -> Ruleset:
    current = get_ruleset(ruleset_id)
    if board_size is not None and board_size <= 0:
        raise ValueError("board_size must be positive")
    if fleet is not None and (not fleet or any(length <= 0 for length in fleet)):
        raise ValueError("fleet must contain positive ship lengths")

    updated = replace(
        current,
        name=current.name if name is None else name,
        board_size=current.board_size if board_size is None else board_size,
        fleet=current.fleet if fleet is None else fleet,
        placement_no_touch=current.placement_no_touch if placement_no_touch is None else placement_no_touch,
        extra_turn_on_hit=current.extra_turn_on_hit if extra_turn_on_hit is None else extra_turn_on_hit,
    )
    _RULESETS[ruleset_id] = updated
    return updated


def archive_ruleset(ruleset_id: str) -> Ruleset:
    if ruleset_id == _ACTIVE_RULESET_ID:
        raise ValueError(f"cannot archive active ruleset: {ruleset_id}")
    ruleset = get_ruleset(ruleset_id)
    _ARCHIVED_RULESET_IDS.add(ruleset_id)
    return ruleset


def activate_ruleset(ruleset_id: str) -> Ruleset:
    if ruleset_id in _ARCHIVED_RULESET_IDS:
        raise ValueError(f"cannot activate archived ruleset: {ruleset_id}")
    ruleset = get_ruleset(ruleset_id)

    global _ACTIVE_RULESET_ID
    _ACTIVE_RULESET_ID = ruleset_id
    return ruleset
