import pandas as pd
import pytest
import numpy as np

from app.services.pipeline_engine import ActionRegistry

def test_drop_nulls():
    df = pd.DataFrame({
        "A": [1, 2, None, 4],
        "B": ["a", None, "c", "d"]
    })
    
    # Drop all nulls
    out = ActionRegistry.apply_drop_nulls(df, {})
    assert len(out) == 2
    assert list(out["A"]) == [1.0, 4.0]
    
    # Drop only nulls in 'B'
    out_b = ActionRegistry.apply_drop_nulls(df, {"columns": ["B"]})
    assert len(out_b) == 3
    assert list(out_b["B"]) == ["a", "c", "d"]


def test_fill_nulls():
    df = pd.DataFrame({
        "A": [1, 2, None, 4],
        "B": ["a", "b", "c", "d"]
    })
    
    # Default (zero)
    out_zero = ActionRegistry.apply_fill_nulls(df, {"columns": ["A"]})
    assert list(out_zero["A"]) == [1.0, 2.0, 0.0, 4.0]
    
    # mean
    out_mean = ActionRegistry.apply_fill_nulls(df, {"columns": ["A"], "method": "mean"})
    # mean of [1, 2, 4] = 7/3 = 2.333
    assert abs(list(out_mean["A"])[2] - 2.3333) < 0.01


def test_remove_outliers():
    df = pd.DataFrame({
        "A": [1, 2, 3, 4, 100],  # 100 is an outlier clearly
        "B": [10, 20, 30, 40, 50]
    })
    
    out = ActionRegistry.apply_remove_outliers(df, {"columns": ["A"]})
    assert len(out) == 4
    assert 100 not in list(out["A"])


def test_normalize():
    df = pd.DataFrame({
        "A": [0, 50, 100]
    })
    out = ActionRegistry.apply_normalize(df, {"columns": ["A"]})
    assert list(out["A"]) == [0.0, 0.5, 1.0]

def test_standardize():
    df = pd.DataFrame({
        "A": [10, 20, 30]
    })
    out = ActionRegistry.apply_standardize(df, {"columns": ["A"]})
    assert abs(out["A"].mean()) < 0.001
    assert out["A"].std() > 0

def test_select_columns():
    df = pd.DataFrame({"A": [1], "B": [2], "C": [3]})
    out = ActionRegistry.apply_select_columns(df, {"columns": ["A", "C"]})
    assert list(out.columns) == ["A", "C"]

def test_rename_columns():
    df = pd.DataFrame({"A": [1], "B": [2]})
    out = ActionRegistry.apply_rename_columns(df, {"mapping": {"A": "Alpha"}})
    assert list(out.columns) == ["Alpha", "B"]

def test_drop_columns():
    df = pd.DataFrame({"A": [1], "B": [2]})
    out = ActionRegistry.apply_drop_columns(df, {"columns": ["A"]})
    assert list(out.columns) == ["B"]
