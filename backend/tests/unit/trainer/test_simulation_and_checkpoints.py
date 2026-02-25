from pathlib import Path

from app.trainer import CheckpointStore, DeterministicSimulator
from app.trainer.simulation import compute_score


def test_simulator_is_deterministic_for_same_seed() -> None:
    s1 = DeterministicSimulator(seed=99)
    s2 = DeterministicSimulator(seed=99)

    seq1 = [s1.next_window(i).score for i in range(5)]
    seq2 = [s2.next_window(i).score for i in range(5)]

    assert seq1 == seq2


def test_compute_score_uses_min_lcb_when_provided() -> None:
    score = compute_score(
        wr_baseline=0.9,
        wr_active=0.8,
        avg_turns_win=30.0,
        lcb_random=0.61,
        lcb_strong=0.57,
        lcb_active=0.63,
    )
    assert score == 0.57


def test_checkpoint_store_save_and_load(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path / 'checkpoints')

    checkpoint = store.save(
        job_id='job-1',
        batches_done=3,
        games_played=150,
        best_score=0.73,
        stage_state='MainOptimization',
        search_state={"search_policy": "sep_cma_es_lite_v1", "cma_generation": 2},
    )
    loaded = store.load(checkpoint)

    assert loaded['checkpoint_id'] == checkpoint.checkpoint_id
    assert loaded['job_id'] == 'job-1'
    assert loaded['batches_done'] == 3
    assert loaded['games_played'] == 150
    assert loaded['best_score'] == 0.73
    assert loaded['stage_state'] == 'MainOptimization'
    assert loaded['search_state']['search_policy'] == 'sep_cma_es_lite_v1'
