from dataclasses import dataclass
from typing import Literal

Coord = tuple[int, int]
Orientation = Literal["H", "V"]
ShotOutcome = Literal["miss", "hit", "sunk"]


@dataclass(frozen=True, slots=True)
class Placement:
    row: int
    col: int
    length: int
    orientation: Orientation

    def cells(self) -> tuple[Coord, ...]:
        if self.orientation == "H":
            return tuple((self.row, self.col + offset) for offset in range(self.length))
        return tuple((self.row + offset, self.col) for offset in range(self.length))


@dataclass(frozen=True, slots=True)
class ShotResult:
    outcome: ShotOutcome
    ship_id: int | None


@dataclass(frozen=True, slots=True)
class TurnResult:
    shooter: int
    target: int
    row: int
    col: int
    outcome: ShotOutcome
    game_over: bool
    winner: int | None
    next_player: int
