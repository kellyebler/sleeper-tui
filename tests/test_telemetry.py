from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from sleeper_tui.telemetry import datadog_otlp_endpoint, parameterize_path, trace_http_client, trace_operation


def _memory_tracer() -> tuple[InMemorySpanExporter, object]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    previous = getattr(trace, "_TRACER_PROVIDER", None)
    trace._TRACER_PROVIDER = provider
    return exporter, previous


def _restore_tracer(previous: object) -> None:
    trace._TRACER_PROVIDER = previous


def test_datadog_otlp_endpoint_uses_site():
    assert datadog_otlp_endpoint("datadoghq.com") == "https://otlp.datadoghq.com"
    assert datadog_otlp_endpoint("us3.datadoghq.com") == "https://otlp.us3.datadoghq.com"
    assert datadog_otlp_endpoint("app.datadoghq.eu") == "https://otlp.datadoghq.eu"


def test_parameterize_path_strips_usernames_and_ids():
    assert parameterize_path("/user/kellyebler") == "/user/{user}"
    assert parameterize_path("/user/483459259485384704/leagues/nfl/2026") == "/user/{user}/leagues/nfl/2026"
    assert parameterize_path("/league/123456789/matchups/1") == "/league/{league_id}/matchups/{week}"
    assert parameterize_path("/stats/nfl/regular/2026/1") == "/stats/nfl/regular/{season}/{week}"
    assert parameterize_path("/players/nfl/4984/news") == "/players/nfl/{player_id}/news"


def test_http_client_span_is_child_of_operation():
    exporter, previous = _memory_tracer()
    try:
        with trace_operation("load matchup", **{"sleeper.week": 1}):
            with trace_http_client("GET", "/league/{league_id}") as span:
                span.set_attribute("http.response.status_code", 200)
        spans = exporter.get_finished_spans()
        names = {span.name: span for span in spans}
        assert "load matchup" in names
        assert "GET /league/{league_id}" in names
        parent = names["load matchup"]
        child = names["GET /league/{league_id}"]
        assert parent.kind == SpanKind.INTERNAL
        assert child.kind == SpanKind.CLIENT
        assert child.parent is not None
        assert child.parent.span_id == parent.context.span_id
        assert "kelly" not in str(child.attributes)
    finally:
        _restore_tracer(previous)


def test_failed_operation_sets_error_status():
    exporter, previous = _memory_tracer()
    try:
        try:
            with trace_operation("bootstrap"):
                raise RuntimeError("Sleeper returned 404 for /user/{user}")
        except RuntimeError:
            pass
        span = exporter.get_finished_spans()[0]
        assert span.status.status_code == StatusCode.ERROR
        assert span.status.description
        assert "RuntimeError" in span.status.description
    finally:
        _restore_tracer(previous)
