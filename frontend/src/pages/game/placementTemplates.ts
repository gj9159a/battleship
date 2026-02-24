import type { Placement } from '../../shared/api/types';

export const PLAYER_TEMPLATE: Placement[] = [
  { row: 0, col: 0, length: 5, orientation: 'H' },
  { row: 2, col: 0, length: 4, orientation: 'H' },
  { row: 4, col: 0, length: 3, orientation: 'H' },
  { row: 6, col: 0, length: 3, orientation: 'H' },
  { row: 8, col: 0, length: 2, orientation: 'H' },
];

export const OPPONENT_TEMPLATE: Placement[] = [
  { row: 0, col: 5, length: 5, orientation: 'H' },
  { row: 2, col: 6, length: 4, orientation: 'H' },
  { row: 4, col: 7, length: 3, orientation: 'H' },
  { row: 6, col: 7, length: 3, orientation: 'H' },
  { row: 8, col: 8, length: 2, orientation: 'H' },
];

export function shipCells(placements: Placement[]): Set<string> {
  const cells = new Set<string>();
  for (const placement of placements) {
    for (let i = 0; i < placement.length; i += 1) {
      const row = placement.orientation === 'H' ? placement.row : placement.row + i;
      const col = placement.orientation === 'H' ? placement.col + i : placement.col;
      cells.add(`${row}:${col}`);
    }
  }
  return cells;
}

export function makeBotCellOrder(size: number, seedText: string): Array<[number, number]> {
  const cells: Array<[number, number]> = [];
  for (let row = 0; row < size; row += 1) {
    for (let col = 0; col < size; col += 1) {
      cells.push([row, col]);
    }
  }

  let seed = 0;
  for (let i = 0; i < seedText.length; i += 1) {
    seed = (seed * 31 + seedText.charCodeAt(i)) >>> 0;
  }

  const offset = cells.length === 0 ? 0 : seed % cells.length;
  return cells.slice(offset).concat(cells.slice(0, offset));
}
