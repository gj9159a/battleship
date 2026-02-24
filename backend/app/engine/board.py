from dataclasses import dataclass, field

from app.engine.types import Coord, Placement, ShotResult
from app.rulesets.models import Ruleset


@dataclass(slots=True)
class _Ship:
    ship_id: int
    cells: set[Coord]
    hits: set[Coord] = field(default_factory=set)

    @property
    def is_sunk(self) -> bool:
        return self.cells == self.hits


class Board:
    def __init__(self, size: int, no_touch: bool = True) -> None:
        if size <= 0:
            raise ValueError("Board size must be positive")
        self.size = size
        self.no_touch = no_touch
        self._ships: list[_Ship] = []
        self._occupied: dict[Coord, int] = {}
        self._shots: set[Coord] = set()

    @property
    def ships_alive(self) -> int:
        return sum(1 for ship in self._ships if not ship.is_sunk)

    @property
    def all_sunk(self) -> bool:
        return bool(self._ships) and self.ships_alive == 0

    def place_ship(self, placement: Placement) -> None:
        if placement.length <= 0:
            raise ValueError("Ship length must be positive")

        cells = placement.cells()
        if len(cells) != placement.length:
            raise ValueError("Invalid ship cells")

        for row, col in cells:
            self._ensure_in_bounds((row, col))
            if (row, col) in self._occupied:
                raise ValueError(f"Cell {(row, col)} is already occupied")

        if self.no_touch:
            for cell in cells:
                for neighbor in self._neighbors(cell):
                    if neighbor in self._occupied:
                        raise ValueError("Ships cannot touch each other")

        ship_id = len(self._ships)
        ship = _Ship(ship_id=ship_id, cells=set(cells))
        self._ships.append(ship)
        for cell in cells:
            self._occupied[cell] = ship_id

    def fire(self, coord: Coord) -> ShotResult:
        self._ensure_in_bounds(coord)
        if coord in self._shots:
            raise ValueError(f"Shot already made at {coord}")

        self._shots.add(coord)
        ship_id = self._occupied.get(coord)
        if ship_id is None:
            return ShotResult(outcome="miss", ship_id=None)

        ship = self._ships[ship_id]
        ship.hits.add(coord)
        if ship.is_sunk:
            return ShotResult(outcome="sunk", ship_id=ship_id)
        return ShotResult(outcome="hit", ship_id=ship_id)

    def _ensure_in_bounds(self, coord: Coord) -> None:
        row, col = coord
        if row < 0 or col < 0 or row >= self.size or col >= self.size:
            raise ValueError(f"Coordinate {coord} out of bounds for size={self.size}")

    @staticmethod
    def _neighbors(coord: Coord) -> tuple[Coord, ...]:
        row, col = coord
        return tuple(
            (row + dr, col + dc)
            for dr in (-1, 0, 1)
            for dc in (-1, 0, 1)
            if not (dr == 0 and dc == 0)
        )


def build_board_from_placements(ruleset: Ruleset, placements: list[Placement]) -> Board:
    expected_fleet = sorted(ruleset.fleet)
    actual_fleet = sorted(placement.length for placement in placements)
    if expected_fleet != actual_fleet:
        raise ValueError(
            f"Fleet mismatch for ruleset={ruleset.id}. Expected {expected_fleet}, got {actual_fleet}"
        )

    board = Board(size=ruleset.board_size, no_touch=ruleset.placement_no_touch)
    for placement in placements:
        board.place_ship(placement)
    return board
