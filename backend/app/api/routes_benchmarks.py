from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_frozen_benchmarks, get_placement_diagnostics, get_training_jobs
from app.schemas import (
    FrozenSuiteEnsureRequest,
    FrozenSuiteResponse,
    FrozenSuiteRunBotVersionRequest,
    FrozenSuiteRunCheckpointRequest,
    FrozenSuiteRunResponse,
    PlacementBiasAnalyzeRequest,
    PlacementBiasReportResponse,
)
from app.services.frozen_benchmarks import FrozenBenchmarkService
from app.services.placement_diagnostics import PlacementDiagnosticsService
from app.services.training_jobs import TrainingJobService

router = APIRouter(prefix="/api/v1/benchmarks", tags=["benchmarks"])


def _suite_to_response(suite) -> FrozenSuiteResponse:
    return FrozenSuiteResponse(
        suite_id=suite.suite_id,
        name=suite.name,
        ruleset_id=suite.ruleset_id,
        suite_kind=suite.suite_kind,
        suite_tier=suite.suite_tier,
        created_at=suite.created_at,
        suite_protocol_hash=suite.suite_protocol_hash,
        seed_anchor=suite.seed_anchor,
        seed_count=suite.seed_count,
        seed_derivation_scheme=suite.seed_derivation_scheme,
        games_per_seed=suite.games_per_seed,
        series_count=suite.series_count,
        mirrored_first_player=suite.mirrored_first_player,
        opponent_policy_type=suite.opponent_policy_type,
        opponent_bot_version_id=suite.opponent_bot_version_id,
        opponent_weights=dict(suite.opponent_weights),
        opponent_lookahead_policy_version=suite.opponent_lookahead_policy_version,
    )


def _run_to_response(run) -> FrozenSuiteRunResponse:
    return FrozenSuiteRunResponse(
        run_id=run.run_id,
        suite_id=run.suite_id,
        created_at=run.created_at,
        subject_type=run.subject_type,
        subject_ref=run.subject_ref,
        suite_protocol_hash=run.suite_protocol_hash,
        eval_seed_anchor=run.eval_seed_anchor,
        seed_count=run.seed_count,
        games_per_seed=run.games_per_seed,
        paired_eval=run.paired_eval,
        mirrored_first_player=run.mirrored_first_player,
        winrate=run.winrate,
        lcb=run.lcb,
        avg_shots_to_sink_all=run.avg_shots_to_sink_all,
        p95_shots_to_sink_all=run.p95_shots_to_sink_all,
        avg_shots_to_first_hit=run.avg_shots_to_first_hit,
        avg_shots_after_first_hit_to_sink_all=run.avg_shots_after_first_hit_to_sink_all,
        avg_misses_before_first_hit=run.avg_misses_before_first_hit,
        raw_metrics=dict(run.raw_metrics),
    )


@router.get("/suites", response_model=list[FrozenSuiteResponse])
async def list_frozen_suites(
    ruleset_id: str | None = None,
    suite_tier: Literal["canonical", "ci_smoke"] | None = None,
    frozen_benchmarks: FrozenBenchmarkService = Depends(get_frozen_benchmarks),
) -> list[FrozenSuiteResponse]:
    suites = frozen_benchmarks.list_suites(ruleset_id=ruleset_id, suite_tier=suite_tier)
    return [_suite_to_response(suite) for suite in suites]


@router.post("/suites/ensure", response_model=list[FrozenSuiteResponse])
async def ensure_frozen_suites(
    payload: FrozenSuiteEnsureRequest,
    frozen_benchmarks: FrozenBenchmarkService = Depends(get_frozen_benchmarks),
) -> list[FrozenSuiteResponse]:
    try:
        suites_by_kind = frozen_benchmarks.ensure_frozen_suites(
            payload.ruleset_id,
            suite_tier=payload.suite_tier,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    suites = sorted(suites_by_kind.values(), key=lambda item: item.suite_kind)
    return [_suite_to_response(suite) for suite in suites]


@router.get("/suites/{suite_id}/runs", response_model=list[FrozenSuiteRunResponse])
async def list_frozen_suite_runs(
    suite_id: str,
    frozen_benchmarks: FrozenBenchmarkService = Depends(get_frozen_benchmarks),
) -> list[FrozenSuiteRunResponse]:
    try:
        runs = frozen_benchmarks.list_suite_runs(suite_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_run_to_response(run) for run in runs]


@router.post("/suites/{suite_id}/runs/bot-version", response_model=FrozenSuiteRunResponse)
async def run_suite_for_bot_version(
    suite_id: str,
    payload: FrozenSuiteRunBotVersionRequest,
    frozen_benchmarks: FrozenBenchmarkService = Depends(get_frozen_benchmarks),
) -> FrozenSuiteRunResponse:
    try:
        run = frozen_benchmarks.run_suite_for_bot_version(suite_id, payload.bot_version_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _run_to_response(run)


@router.post("/suites/{suite_id}/runs/checkpoint", response_model=FrozenSuiteRunResponse)
async def run_suite_for_checkpoint(
    suite_id: str,
    payload: FrozenSuiteRunCheckpointRequest,
    frozen_benchmarks: FrozenBenchmarkService = Depends(get_frozen_benchmarks),
    training_jobs: TrainingJobService = Depends(get_training_jobs),
) -> FrozenSuiteRunResponse:
    _ = suite_id
    _ = payload
    _ = frozen_benchmarks
    _ = training_jobs
    raise HTTPException(status_code=410, detail="Checkpoint system is disabled")


@router.post("/placement-bias/analyze", response_model=PlacementBiasReportResponse)
async def analyze_placement_bias(
    payload: PlacementBiasAnalyzeRequest,
    placement_diagnostics: PlacementDiagnosticsService = Depends(get_placement_diagnostics),
) -> PlacementBiasReportResponse:
    try:
        report = placement_diagnostics.analyze_bias(
            ruleset_id=payload.ruleset_id,
            sample_count=payload.sample_count,
            seed_anchor=payload.seed_anchor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PlacementBiasReportResponse.model_validate(report)


@router.get("/placement-bias/latest", response_model=PlacementBiasReportResponse)
async def get_latest_placement_bias_report(
    ruleset_id: str,
    placement_diagnostics: PlacementDiagnosticsService = Depends(get_placement_diagnostics),
) -> PlacementBiasReportResponse:
    report = placement_diagnostics.get_last_report(ruleset_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Placement bias report not found for ruleset_id={ruleset_id}")
    return PlacementBiasReportResponse.model_validate(report)
