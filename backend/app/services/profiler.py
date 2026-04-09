"""profiler.py — pure stateless dataset analysis."""
import numpy as np
import pandas as pd
from typing import Any


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    profiles, numeric_cols = [], []

    for col in df.columns:
        series = df[col]
        null_count = int(series.isna().sum())
        null_pct   = round(null_count / max(len(series), 1) * 100, 2)
        non_null   = series.dropna()

        if pd.api.types.is_numeric_dtype(series) and len(non_null):
            numeric_cols.append(col)
            vals = non_null.values.astype(float)
            s    = np.sort(vals)
            mean = float(np.mean(vals))
            n    = len(s)
            med  = float((s[n // 2 - 1] + s[n // 2]) / 2) if n % 2 == 0 else float(s[n // 2])
            std  = float(np.std(vals, ddof=0))
            q1   = float(np.percentile(vals, 25))
            q3   = float(np.percentile(vals, 75))
            iqr  = q3 - q1
            outliers = int(np.sum((vals < q1 - 1.5 * iqr) | (vals > q3 + 1.5 * iqr)))
            skew = (3 * (mean - med) / std) if std > 0 else 0.0
            profiles.append({
                "col": col, "type": "numeric", "null_count": null_count, "null_pct": null_pct,
                "mean": round(mean, 4), "median": round(med, 4), "std": round(std, 4),
                "min": float(s[0]), "max": float(s[-1]),
                "q1": round(q1, 4), "q3": round(q3, 4), "iqr": round(iqr, 4),
                "outliers_count": outliers, "skew": round(skew, 4),
            })
        else:
            freq = non_null.value_counts().head(5)
            profiles.append({
                "col": col, "type": "categorical",
                "null_count": null_count, "null_pct": null_pct,
                "unique_count": int(non_null.nunique()),
                "top_values": [[str(k), int(v)] for k, v in freq.items()],
            })

    # Pearson correlation matrix
    correlations: dict = {}
    if len(numeric_cols) >= 2:
        corr = df[numeric_cols].corr(method="pearson")
        for c1 in numeric_cols:
            correlations[c1] = {}
            for c2 in numeric_cols:
                v = corr.loc[c1, c2] if c1 in corr.index and c2 in corr.columns else 0
                correlations[c1][c2] = round(float(v) if not np.isnan(v) else 0.0, 4)

    avg_null    = sum(p["null_pct"] for p in profiles) / max(len(profiles), 1)
    outlier_cols = sum(1 for p in profiles if p.get("outliers_count", 0) > 0)
    health_score = max(0, min(100, round(100 - avg_null * 0.8 - outlier_cols * 4)))

    return {
        "profiles": profiles, "correlations": correlations,
        "numeric_cols": numeric_cols, "health_score": health_score,
        "row_count": len(df), "col_count": len(df.columns),
    }


def generate_smart_suggestions(profile: dict) -> list[dict]:
    suggestions = []
    profs = profile.get("profiles", [])
    nums  = profile.get("numeric_cols", [])
    null_cols    = [p for p in profs if p["null_pct"] > 0]
    outlier_cols = [p for p in profs if p.get("outliers_count", 0) > 0]
    cat_cols     = [p for p in profs if p["type"] == "categorical"]
    high_skew    = [p for p in profs if p["type"] == "numeric" and abs(p.get("skew", 0)) > 1]

    if null_cols:
        avg = round(sum(p["null_pct"] for p in null_cols) / len(null_cols), 1)
        suggestions.append({"prompt": "fill missing values with mean", "reason": f"{len(null_cols)} col(s) have nulls (avg {avg}%)", "icon": "○"})
    if outlier_cols:
        total = sum(p["outliers_count"] for p in outlier_cols)
        suggestions.append({"prompt": "remove outliers", "reason": f"{total} outliers across {len(outlier_cols)} col(s)", "icon": "⚡"})
    if len(nums) > 1:
        suggestions.append({"prompt": "normalize all numeric columns", "reason": f"{len(nums)} numeric cols → [0,1]", "icon": "↕"})
    if cat_cols:
        suggestions.append({"prompt": "encode categorical columns", "reason": f"{len(cat_cols)} text col(s) → integers for ML", "icon": "#"})
    if high_skew:
        suggestions.append({"prompt": "standardize numeric columns", "reason": f"{len(high_skew)} col(s) highly skewed", "icon": "~"})
    suggestions.append({"prompt": "remove duplicate rows", "reason": "Deduplicate records", "icon": "="})
    return suggestions[:5]

def detect_anomalies(df: pd.DataFrame, max_results: int = 100) -> list[dict]:
    """Detects multi-variate anomalies using IQR Z-Score thresholding"""
    numeric_df = df.select_dtypes(include=[np.number]).dropna()
    if numeric_df.empty:
        return []

    # Calculate Z-scores
    z_scores = np.abs((numeric_df - numeric_df.mean()) / numeric_df.std(ddof=0))
    # Fill any NaNs with 0 (e.g. constant columns causing division by zero)
    z_scores = z_scores.fillna(0)
    
    # Calculate a composite anomaly score per row (sum of squared Z-scores or simply max)
    row_max_z = z_scores.max(axis=1)
    
    # Classify anomalies (e.g. max Z > 3 => 99.7% confidence interval)
    anomalous_indices = row_max_z[row_max_z > 3].sort_values(ascending=False).index[:max_results]
    
    results = []
    for idx in anomalous_indices:
        # Extract the highest contributing column for this row
        row_z = z_scores.loc[idx]
        reason_col = row_z.idxmax()
        max_val = row_z[reason_col]
        
        row_data = df.loc[idx].replace({np.nan: None}).to_dict()
        results.append({
            "idx": int(idx),
            "score": round(float(max_val), 2),
            "reason": f"Column '{reason_col}' value ({df.loc[idx, reason_col]}) is {round(float(max_val), 1)} standard deviations from mean.",
            "data": row_data
        })
        
    return results
