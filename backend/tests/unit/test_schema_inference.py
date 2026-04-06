import pandas as pd
import pytest

DTYPE_MAPPING = {
    'int64': 'numeric',
    'float64': 'numeric',
    'Int64': 'numeric',
    'Float64': 'numeric',
    'bool': 'categorical',
    'object': 'text',
    'string': 'text',
    'category': 'categorical',
    'datetime64[ns]': 'datetime'
}

def map_pandas_dtype(pd_type) -> str:
    pd_type_str = str(pd_type)
    return DTYPE_MAPPING.get(pd_type_str, 'text')

def test_numeric_mapping():
    assert map_pandas_dtype(pd.Series([1, 2, 3]).dtype) == 'numeric'
    assert map_pandas_dtype(pd.Series([1.0, 2.5]).dtype) == 'numeric'

def test_categorical_mapping():
    assert map_pandas_dtype(pd.Series([True, False]).dtype) == 'categorical'
    assert map_pandas_dtype(pd.Series(["A", "B"], dtype="category").dtype) == 'categorical'

def test_datetime_mapping():
    assert map_pandas_dtype(pd.to_datetime(["2020-01-01"]).dtype) == 'datetime'

def test_text_fallback_mapping():
    assert map_pandas_dtype(pd.Series(["foo", "bar"]).dtype) == 'text'
    # Unknown type falls back to text
    assert map_pandas_dtype("complex128") == 'text'
