from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Ruleset:
    id: str
    name: str
    board_size: int
    fleet: tuple[int, ...]
    placement_no_touch: bool = True
    extra_turn_on_hit: bool = True
