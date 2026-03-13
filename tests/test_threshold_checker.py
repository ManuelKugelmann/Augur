"""Tests for threshold_checker — pure threshold evaluation logic."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "alerts"))
import threshold_checker as tc  # noqa: E402


class TestCheckThresholds:
    def test_less_than_breach(self):
        data = {"rsi_14": 25.0}
        thresholds = [{"field": "rsi_14", "op": "<", "value": 30,
                       "severity": "high", "label": "RSI oversold"}]
        result = tc.check_thresholds(data, thresholds)
        assert len(result) == 1
        assert result[0]["field"] == "rsi_14"
        assert result[0]["actual"] == 25.0
        assert result[0]["threshold"] == 30
        assert result[0]["severity"] == "high"
        assert result[0]["label"] == "RSI oversold"

    def test_greater_than_breach(self):
        data = {"close": 250.0}
        thresholds = [{"field": "close", "op": ">", "value": 200,
                       "severity": "medium", "label": "Price above 200"}]
        result = tc.check_thresholds(data, thresholds)
        assert len(result) == 1
        assert result[0]["actual"] == 250.0

    def test_no_breach(self):
        data = {"rsi_14": 55.0}
        thresholds = [{"field": "rsi_14", "op": "<", "value": 30,
                       "severity": "high", "label": "RSI oversold"}]
        result = tc.check_thresholds(data, thresholds)
        assert result == []

    def test_equal_breach(self):
        data = {"status": "critical"}
        thresholds = [{"field": "status", "op": "==", "value": "critical",
                       "severity": "critical", "label": "Status critical"}]
        result = tc.check_thresholds(data, thresholds)
        assert len(result) == 1

    def test_not_equal_breach(self):
        data = {"status": "warning"}
        thresholds = [{"field": "status", "op": "!=", "value": "ok",
                       "severity": "low", "label": "Status not OK"}]
        result = tc.check_thresholds(data, thresholds)
        assert len(result) == 1

    def test_less_equal(self):
        data = {"value": 30}
        thresholds = [{"field": "value", "op": "<=", "value": 30,
                       "severity": "medium", "label": "At or below 30"}]
        result = tc.check_thresholds(data, thresholds)
        assert len(result) == 1

    def test_greater_equal(self):
        data = {"magnitude": 6.0}
        thresholds = [{"field": "magnitude", "op": ">=", "value": 6.0,
                       "severity": "critical", "label": "Major earthquake"}]
        result = tc.check_thresholds(data, thresholds)
        assert len(result) == 1

    def test_absent_field_breach(self):
        data = {"close": 100.0}
        thresholds = [{"field": "volume", "op": "absent", "value": None,
                       "severity": "low", "label": "Volume data missing"}]
        result = tc.check_thresholds(data, thresholds)
        assert len(result) == 1
        assert result[0]["op"] == "absent"

    def test_absent_field_no_breach(self):
        data = {"volume": 1000000}
        thresholds = [{"field": "volume", "op": "absent", "value": None,
                       "severity": "low", "label": "Volume data missing"}]
        result = tc.check_thresholds(data, thresholds)
        assert result == []

    def test_missing_field_skipped_for_numeric_ops(self):
        data = {"close": 100.0}
        thresholds = [{"field": "rsi_14", "op": "<", "value": 30,
                       "severity": "high", "label": "RSI oversold"}]
        result = tc.check_thresholds(data, thresholds)
        assert result == []

    def test_nested_field(self):
        data = {"exposure": {"risk_score": 85}}
        thresholds = [{"field": "exposure.risk_score", "op": ">", "value": 80,
                       "severity": "high", "label": "High risk exposure"}]
        result = tc.check_thresholds(data, thresholds)
        assert len(result) == 1
        assert result[0]["actual"] == 85

    def test_multiple_thresholds(self):
        data = {"rsi_14": 25.0, "close": 250.0, "volume": 5000000}
        thresholds = [
            {"field": "rsi_14", "op": "<", "value": 30,
             "severity": "high", "label": "RSI oversold"},
            {"field": "close", "op": ">", "value": 200,
             "severity": "medium", "label": "Price high"},
            {"field": "volume", "op": ">", "value": 10000000,
             "severity": "low", "label": "High volume"},
        ]
        result = tc.check_thresholds(data, thresholds)
        # rsi and close breach, volume does not
        assert len(result) == 2
        assert {r["field"] for r in result} == {"rsi_14", "close"}

    def test_unknown_operator_skipped(self):
        data = {"value": 10}
        thresholds = [{"field": "value", "op": "~=", "value": 10,
                       "severity": "low", "label": "test"}]
        result = tc.check_thresholds(data, thresholds)
        assert result == []

    def test_type_mismatch_handled(self):
        data = {"value": "not_a_number"}
        thresholds = [{"field": "value", "op": "<", "value": 30,
                       "severity": "low", "label": "test"}]
        # Should not raise, just skip
        result = tc.check_thresholds(data, thresholds)
        assert result == []

    def test_empty_thresholds(self):
        result = tc.check_thresholds({"x": 1}, [])
        assert result == []

    def test_empty_data(self):
        thresholds = [{"field": "x", "op": ">", "value": 0,
                       "severity": "low", "label": "test"}]
        result = tc.check_thresholds({}, thresholds)
        assert result == []


class TestGetThresholdsFromProfile:
    def test_extracts_thresholds(self):
        profile = {
            "id": "AAPL", "name": "Apple",
            "signal": {
                "thresholds": [
                    {"field": "rsi_14", "op": "<", "value": 30,
                     "severity": "high", "label": "RSI oversold"},
                ]
            }
        }
        result = tc.get_thresholds_from_profile(profile)
        assert len(result) == 1

    def test_missing_signal(self):
        result = tc.get_thresholds_from_profile({"id": "X", "name": "X"})
        assert result == []

    def test_missing_thresholds(self):
        result = tc.get_thresholds_from_profile({"signal": {}})
        assert result == []


class TestMaxSeverity:
    def test_returns_highest(self):
        breaches = [
            {"severity": "low", "label": "a"},
            {"severity": "critical", "label": "b"},
            {"severity": "medium", "label": "c"},
        ]
        assert tc.max_severity(breaches) == "critical"

    def test_single_breach(self):
        assert tc.max_severity([{"severity": "high"}]) == "high"

    def test_empty_breaches(self):
        assert tc.max_severity([]) == "low"
