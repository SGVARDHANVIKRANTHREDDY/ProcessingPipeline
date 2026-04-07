import pandas as pd
import numpy as np
from app.services.profiler import profile_dataframe

def test_profile_empty_dataframe():
    df = pd.DataFrame()
    profile = profile_dataframe(df)
    assert profile["summary"]["n_rows"] == 0
    assert profile["summary"]["n_cols"] == 0
    assert profile["summary"]["health_score"] == 100
    assert len(profile["columns"]) == 0

def test_profile_all_missing():
    df = pd.DataFrame({"x": [np.nan, np.nan, np.nan]})
    profile = profile_dataframe(df)
    
    assert profile["summary"]["health_score"] == 90
    
    col_x = profile["columns"][0]
    assert col_x["name"] == "x"
    assert col_x["missing_pct"] == 1.0
    assert col_x["unique_count"] == 0

def test_profile_single_value():
    df = pd.DataFrame({"x": [1, 1, 1, 1]})
    profile = profile_dataframe(df)
    
    assert profile["summary"]["health_score"] == 90
    
    col_x = profile["columns"][0]
    assert col_x["unique_count"] == 1
    assert col_x["missing_pct"] == 0.0

def test_profile_mixed_types():
    df = pd.DataFrame({"x": [1, "a", 3.5]})
    profile = profile_dataframe(df)
    
    col_x = profile["columns"][0]
    assert col_x["logical_type"] == "categorical"
    assert "distribution" in col_x

def test_profile_numeric_outliers():
    df = pd.DataFrame({"x": [1, 2, 3, 1000]}) # 1000 is an outlier
    profile = profile_dataframe(df)
    
    col_x = profile["columns"][0]
    assert col_x["logical_type"] == "numeric"
    assert col_x["outliers"]["outlier_count"] > 0
    assert col_x["outliers"]["method"] == "iqr"

def test_profile_correlations():
    df = pd.DataFrame({
        "x": [1, 2, 3],
        "y": [2, 4, 6]
    })
    profile = profile_dataframe(df)
    
    assert "correlations" in profile
    assert "x" in profile["correlations"]
    assert "y" in profile["correlations"]["x"]
    assert profile["correlations"]["x"]["y"] > 0.99
