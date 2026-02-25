from app.services.placement_diagnostics import PlacementDiagnosticsService


def test_bias_report_is_deterministic_for_same_seed_and_sample_count() -> None:
    service = PlacementDiagnosticsService()

    report_a = service.analyze_bias(ruleset_id="classic_v1", sample_count=256, seed_anchor=42)
    report_b = service.analyze_bias(ruleset_id="classic_v1", sample_count=256, seed_anchor=42)

    assert report_a["occupancy_heatmap"] == report_b["occupancy_heatmap"]
    assert report_a["occupancy_by_ship_len"] == report_b["occupancy_by_ship_len"]
    assert report_a["orientation_stats_by_len"] == report_b["orientation_stats_by_len"]
    assert report_a["edge_center_bias"] == report_b["edge_center_bias"]
    assert report_a["corner_bias"] == report_b["corner_bias"]
    assert report_a["seed_reproducibility_check"]["deterministic"] is True


def test_bias_latest_report_returns_last_run() -> None:
    service = PlacementDiagnosticsService()

    first = service.analyze_bias(ruleset_id="classic_v1", sample_count=128, seed_anchor=7)
    second = service.analyze_bias(ruleset_id="classic_v1", sample_count=64, seed_anchor=9)
    latest = service.get_last_report("classic_v1")

    assert first["report_id"] != second["report_id"]
    assert latest is not None
    assert latest["report_id"] == second["report_id"]
    assert latest["sample_count"] == 64
