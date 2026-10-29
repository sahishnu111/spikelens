from spikelens.logparse import logs_to_series, parse_line
from spikelens.synthetic import demo_log_lines

NGINX = '127.0.0.1 - - [10/Oct/2026:13:55:36 +0000] "GET /a HTTP/1.1" 503 12 "-" "curl/8"'
APACHE = '10.1.1.1 - frank [10/Oct/2026:13:55:59 -0700] "POST /b HTTP/1.0" 200 2326'


def test_parse_nginx_and_apache():
    a, b = parse_line(NGINX), parse_line(APACHE)
    assert a and a.is_error and a.fmt == "combined"
    assert b and not b.is_error and b.ts.utcoffset().total_seconds() == -7 * 3600


def test_parse_generic_levels():
    assert parse_line("2026-10-10 13:55:36,123 ERROR db timeout").is_error
    assert not parse_line("2026-10-10T13:55:36Z INFO ok").is_error
    assert parse_line("[2026-10-10 13:55:36] FATAL boom").is_error


def test_garbage_is_skipped():
    s = logs_to_series(["hello world", "", NGINX])
    assert s.parsed == 1 and s.skipped == 1


def test_bucketing_fills_gaps():
    lines = [
        "2026-10-10 13:00:05 INFO a",
        "2026-10-10 13:00:50 ERROR b",
        "2026-10-10 13:03:00 INFO c",
    ]
    s = logs_to_series(lines)
    assert s.counts == [2, 0, 0, 1]
    assert s.errors == [1, 0, 0, 0]
    assert s.error_rate[0] == 0.5


def test_demo_logs_have_error_burst():
    s = logs_to_series(demo_log_lines())
    assert len(s.counts) == 240
    assert max(s.error_rate[90:94]) > 0.3
    assert max(s.error_rate[:80]) < 0.2
