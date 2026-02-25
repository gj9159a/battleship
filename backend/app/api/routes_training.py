from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_bot_catalog, get_training_jobs
from app.schemas import (
    TrainingCheckpointResponse,
    TrainingCommandRequest,
    TrainingJobCreateRequest,
    TrainingJobResponse,
    TrainingParamsDTO,
    TrainingProgressDTO,
)
from app.services.training_jobs import TrainingJobService
from app.services import BotCatalogService
from app.trainer import TrainingParams

router = APIRouter(prefix="/api/v1/training/jobs", tags=["training"])


def _to_response(job) -> TrainingJobResponse:
    return TrainingJobResponse(
        id=job.id,
        ruleset_id=job.ruleset_id,
        lifecycle_state=job.lifecycle_state,
        stage_state=job.stage_state,
        profile_id=job.profile_id,
        seed_bot_version_id=job.seed_bot_version_id,
        seed=job.seed,
        stop_reason=job.stop_reason,
        current_weights=dict(job.current_weights),
        best_weights=dict(job.best_weights),
        params=TrainingParamsDTO(
            microbatch_size=job.params.microbatch_size,
            eval_window_batches=job.params.eval_window_batches,
            checkpoint_interval_batches=job.params.checkpoint_interval_batches,
            population_size=job.params.population_size,
            train_split=job.params.train_split,
            worker_count=job.params.worker_count,
            quality_gate_games=job.params.quality_gate_games,
            quality_gate_min_winrate=job.params.quality_gate_min_winrate,
            quality_gate_min_lower_bound=job.params.quality_gate_min_lower_bound,
            target_score=job.params.target_score,
            improvement_delta=job.params.improvement_delta,
            plateau_delta=job.params.plateau_delta,
            plateau_patience_windows=job.params.plateau_patience_windows,
            early_stop_plateau_windows=job.params.early_stop_plateau_windows,
            min_windows_before_early_stop=job.params.min_windows_before_early_stop,
            tick_delay_ms=job.params.tick_delay_ms,
            autoevolve_enabled=job.params.autoevolve_enabled,
            meta_plateau_patience_cycles=job.params.meta_plateau_patience_cycles,
            strictness_max_level=job.params.strictness_max_level,
        ),
        progress=TrainingProgressDTO(
            games_played=job.progress.games_played,
            batches_done=job.progress.batches_done,
            windows_done=job.progress.windows_done,
            best_score=job.progress.best_score,
            last_score=job.progress.last_score,
            plateau_windows=job.progress.plateau_windows,
            cycle_index=job.progress.cycle_index,
            strictness_level=job.progress.strictness_level,
            meta_plateau_counter=job.progress.meta_plateau_counter,
            champion_gate_lcb=job.progress.champion_gate_lcb,
            eval_protocol_hash=job.progress.eval_protocol_hash,
            last_wr_baseline=job.progress.last_wr_baseline,
            last_wr_active=job.progress.last_wr_active,
            last_avg_turns_win=job.progress.last_avg_turns_win,
            last_avg_shots_to_sink_all=job.progress.last_avg_shots_to_sink_all,
            last_p95_shots_to_sink_all=job.progress.last_p95_shots_to_sink_all,
            last_avg_shots_to_first_hit=job.progress.last_avg_shots_to_first_hit,
            last_avg_shots_after_first_hit_to_sink_all=job.progress.last_avg_shots_after_first_hit_to_sink_all,
            last_avg_misses_before_first_hit=job.progress.last_avg_misses_before_first_hit,
            last_eval_seed_anchor=job.progress.last_eval_seed_anchor,
            last_incumbent_seed_anchor=job.progress.last_incumbent_seed_anchor,
            last_eval_paired=job.progress.last_eval_paired,
            last_eval_mirrored=job.progress.last_eval_mirrored,
            selection_robust_score_candidate=job.progress.selection_robust_score_candidate,
            selection_robust_score_incumbent=job.progress.selection_robust_score_incumbent,
            selection_robust_delta=job.progress.selection_robust_delta,
            selection_noninferiority_passed=job.progress.selection_noninferiority_passed,
            selection_attack_efficiency_candidate=job.progress.selection_attack_efficiency_candidate,
            selection_attack_efficiency_incumbent=job.progress.selection_attack_efficiency_incumbent,
            selection_attack_delta=job.progress.selection_attack_delta,
            selection_tiebreak_used=job.progress.selection_tiebreak_used,
            selection_decision_reason=job.progress.selection_decision_reason,
            elite_candidates_evaluated=job.progress.elite_candidates_evaluated,
            elite_selected_candidate_index=job.progress.elite_selected_candidate_index,
            elite_selection_reason=job.progress.elite_selection_reason,
            sigma_mean=job.progress.sigma_mean,
            sigma_min=job.progress.sigma_min,
            sigma_max=job.progress.sigma_max,
            search_policy=job.progress.search_policy,
            cma_sigma=job.progress.cma_sigma,
            cma_diag_mean=job.progress.cma_diag_mean,
            cma_diag_min=job.progress.cma_diag_min,
            cma_diag_max=job.progress.cma_diag_max,
            cma_generation=job.progress.cma_generation,
            cma_mean_incumbent_l2=job.progress.cma_mean_incumbent_l2,
            cma_parent_mu=job.progress.cma_parent_mu,
            cma_mueff=job.progress.cma_mueff,
            search_state_bootstrapped=job.progress.search_state_bootstrapped,
            restart_count=job.progress.restart_count,
            last_restart_reason=job.progress.last_restart_reason,
            last_restart_anchor_score=job.progress.last_restart_anchor_score,
            last_restart_window=job.progress.last_restart_window,
            elite_fallback_used=job.progress.elite_fallback_used,
            frozen_suite_summaries=dict(job.progress.frozen_suite_summaries),
        ),
    )


@router.post("", response_model=TrainingJobResponse)
async def create_training_job(
    payload: TrainingJobCreateRequest,
    training_jobs: TrainingJobService = Depends(get_training_jobs),
    bot_catalog: BotCatalogService = Depends(get_bot_catalog),
) -> TrainingJobResponse:
    try:
        seed_weights = None
        if payload.seed_bot_version_id:
            seed_bot = bot_catalog.get_bot(payload.seed_bot_version_id)
            if seed_bot.ruleset_id != payload.ruleset_id:
                raise ValueError(
                    f"seed_bot_version_id ruleset mismatch: {seed_bot.ruleset_id} != {payload.ruleset_id}"
                )
            seed_weights = dict(seed_bot.weights)

        params = TrainingParams(**payload.params.model_dump()) if payload.params else TrainingParams()
        job = training_jobs.create_job(
            payload.ruleset_id,
            payload.profile_id,
            payload.seed_bot_version_id,
            payload.seed,
            seed_weights=seed_weights,
            params=params,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _to_response(job)


@router.get("/{job_id}", response_model=TrainingJobResponse)
async def get_training_job(
    job_id: str,
    training_jobs: TrainingJobService = Depends(get_training_jobs),
) -> TrainingJobResponse:
    try:
        job = training_jobs.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_response(job)


@router.get("/{job_id}/checkpoints", response_model=list[TrainingCheckpointResponse])
async def get_training_checkpoints(
    job_id: str,
    training_jobs: TrainingJobService = Depends(get_training_jobs),
) -> list[TrainingCheckpointResponse]:
    try:
        checkpoints = training_jobs.list_checkpoints(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        TrainingCheckpointResponse(
            checkpoint_id=checkpoint.checkpoint_id,
            job_id=checkpoint.job_id,
            path=checkpoint.path,
            batches_done=checkpoint.batches_done,
            games_played=checkpoint.games_played,
            best_score=checkpoint.best_score,
            stage_state=checkpoint.stage_state,
        )
        for checkpoint in checkpoints
    ]


@router.post("/{job_id}/resume-from/{checkpoint_id}", response_model=TrainingJobResponse)
async def load_training_checkpoint(
    job_id: str,
    checkpoint_id: str,
    training_jobs: TrainingJobService = Depends(get_training_jobs),
) -> TrainingJobResponse:
    try:
        job = await training_jobs.load_checkpoint(job_id, checkpoint_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_response(job)


@router.post("/{job_id}/commands", response_model=TrainingJobResponse)
async def command_training_job(
    job_id: str,
    payload: TrainingCommandRequest,
    training_jobs: TrainingJobService = Depends(get_training_jobs),
) -> TrainingJobResponse:
    try:
        job = await training_jobs.apply_command(job_id, payload.command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _to_response(job)
