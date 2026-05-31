from datetime import datetime, timedelta

import pytest

from agent.scheduler import parse_interval, parse_delay, calc_next_run, _infer_type


class TestParseInterval:

    def test_every_30m(self):
        assert parse_interval("every 30m") == timedelta(minutes=30)

    def test_every_2h(self):
        assert parse_interval("every 2h") == timedelta(hours=2)

    def test_every_1d(self):
        assert parse_interval("every 1d") == timedelta(days=1)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid interval"):
            parse_interval("30m")

    def test_invalid_unit_raises(self):
        with pytest.raises(ValueError, match="Invalid interval"):
            parse_interval("every 30s")


class TestParseDelay:

    def test_2h(self):
        assert parse_delay("2h") == timedelta(hours=2)

    def test_30m(self):
        assert parse_delay("30m") == timedelta(minutes=30)

    def test_1d(self):
        assert parse_delay("1d") == timedelta(days=1)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid delay"):
            parse_delay("every 30m")

    def test_bare_number_raises(self):
        with pytest.raises(ValueError, match="Invalid delay"):
            parse_delay("2")


class TestCalcNextRun:

    def test_cron_expression(self):
        result = calc_next_run("0 9 * * 1-5")
        dt = datetime.fromisoformat(result)
        assert dt.hour == 9
        assert dt.minute == 0
        assert dt.weekday() < 5  # Mon-Fri
        assert dt > datetime.now()

    def test_interval(self):
        before = datetime.now()
        result = calc_next_run("every 30m")
        dt = datetime.fromisoformat(result)
        expected = before + timedelta(minutes=30)
        assert abs((dt - expected).total_seconds()) < 5

    def test_delay(self):
        before = datetime.now()
        result = calc_next_run("2h")
        dt = datetime.fromisoformat(result)
        expected = before + timedelta(hours=2)
        assert abs((dt - expected).total_seconds()) < 5

    def test_time_string(self):
        result = calc_next_run("13:25")
        dt = datetime.fromisoformat(result)
        assert dt.hour == 13
        assert dt.minute == 25

    def test_iso_datetime(self):
        future = "2027-06-15T10:00:00"
        result = calc_next_run(future)
        assert result == future

    def test_past_iso_raises(self):
        with pytest.raises(ValueError, match="不支持"):
            calc_next_run("2020-01-01T00:00:00")

    def test_unsupported_format_raises(self):
        with pytest.raises(ValueError, match="不支持"):
            calc_next_run("garbage")


class TestInferType:

    def test_delay_m_is_once(self):
        assert _infer_type("30m") == "once"

    def test_delay_h_is_once(self):
        assert _infer_type("2h") == "once"

    def test_delay_d_is_once(self):
        assert _infer_type("1d") == "once"

    def test_time_string_is_recurring(self):
        assert _infer_type("13:25") == "recurring"

    def test_cron_expr_is_recurring(self):
        assert _infer_type("0 9 * * *") == "recurring"

    def test_every_interval_is_recurring(self):
        assert _infer_type("every 30m") == "recurring"

    def test_iso_datetime_is_once(self):
        assert _infer_type("2026-12-31T23:59:00") == "once"
