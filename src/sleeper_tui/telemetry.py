from __future__ import annotations

import atexit
import os
import re
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.trace import SpanKind, StatusCode

SERVICE_NAME = "sleeper-tui"
TRACER_NAME = "sleeper_tui"

_ID_SEGMENT = re.compile(r"/[0-9]{6,}")
_USER_SEGMENT = re.compile(r"/user/[^/]+")
_LEAGUE_SEGMENT = re.compile(r"/league/[^/]+")
_MATCHUP_WEEK = re.compile(r"/matchups/[0-9]+")
_STATS_WEEK = re.compile(r"/(stats|projections)/nfl/regular/[0-9]+/[0-9]+")
_PLAYER_NEWS = re.compile(r"/players/nfl/[^/]+/news")

_enabled = False
_meter = metrics.get_meter(TRACER_NAME)
_operation_duration = _meter.create_histogram(
    "sleeper.tui.operation.duration",
    unit="s",
    description="Duration of a sleeper-tui operation",
)


def service_version() -> str:
    try:
        return version("sleeper-tui")
    except PackageNotFoundError:
        from sleeper_tui import __version__

        return __version__


def parameterize_path(path: str) -> str:
    path = _PLAYER_NEWS.sub("/players/nfl/{player_id}/news", path)
    path = _STATS_WEEK.sub(r"/\1/nfl/regular/{season}/{week}", path)
    path = _MATCHUP_WEEK.sub("/matchups/{week}", path)
    path = _LEAGUE_SEGMENT.sub("/league/{league_id}", path)
    path = _USER_SEGMENT.sub("/user/{user}", path)
    return _ID_SEGMENT.sub("/{id}", path)


def monitoring_requested(explicit: bool = False) -> bool:
    if explicit:
        return True
    flag = os.environ.get("SLEEPER_TUI_MONITORING", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))


def datadog_otlp_endpoint(site: str | None = None) -> str:
    host = (site or os.environ.get("DD_SITE") or "datadoghq.com").strip()
    host = host.removeprefix("https://").removeprefix("http://")
    host = host.removeprefix("app.").removeprefix("api.").removeprefix("otlp.")
    host = host.rstrip("/")
    if host in {"", "datadoghq.com"}:
        return "https://otlp.datadoghq.com"
    return f"https://otlp.{host}"


def setup_telemetry(*, otlp_endpoint: str | None = None) -> bool:
    """Start tracing/metrics via OTLP. Default is Datadog intake, not a local Agent."""
    global _enabled, _meter, _operation_duration
    if _enabled:
        return True

    environment = os.environ.get("DD_ENV") or os.environ.get("DEPLOYMENT_ENVIRONMENT") or "development"
    instance_id = os.environ.get("OTEL_SERVICE_INSTANCE_ID") or str(uuid.uuid4())
    os.environ.setdefault("OTEL_SERVICE_NAME", SERVICE_NAME)
    os.environ.setdefault(
        "OTEL_RESOURCE_ATTRIBUTES",
        ",".join(
            [
                f"service.version={service_version()}",
                f"deployment.environment.name={environment}",
                f"service.instance.id={instance_id}",
            ]
        ),
    )

    explicit_otlp = otlp_endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    api_key = os.environ.get("DD_API_KEY", "").strip()
    headers = {"dd-api-key": api_key} if api_key else None
    endpoint = explicit_otlp or (datadog_otlp_endpoint() if api_key else None)
    if not endpoint or not _try_otlp_provider(endpoint, headers=headers):
        return False
    _enabled = True
    atexit.register(shutdown_telemetry)
    return True


def _otlp_signal_url(endpoint: str, signal: str) -> str:
    base = endpoint.rstrip("/")
    for suffix in ("/v1/traces", "/v1/metrics"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return f"{base}/v1/{signal}"


def _try_otlp_provider(endpoint: str, *, headers: dict[str, str] | None = None) -> bool:
    try:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return False

    resource = Resource.create(
        {
            "service.name": os.environ.get("OTEL_SERVICE_NAME", SERVICE_NAME),
        }
    )
    tracer_provider = TracerProvider(resource=resource)
    traces_url = _otlp_signal_url(endpoint, "traces")
    metrics_url = _otlp_signal_url(endpoint, "metrics")
    exporter_headers = headers or None
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_url, headers=exporter_headers))
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=metrics_url, headers=exporter_headers)
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
    _meter = metrics.get_meter(TRACER_NAME)
    _operation_duration = _meter.create_histogram(
        "sleeper.tui.operation.duration",
        unit="s",
        description="Duration of a sleeper-tui operation",
    )
    return True


def shutdown_telemetry() -> None:
    provider = trace.get_tracer_provider()
    shutdown = getattr(provider, "shutdown", None)
    if callable(shutdown):
        shutdown()
    meter_provider = metrics.get_meter_provider()
    meter_shutdown = getattr(meter_provider, "shutdown", None)
    if callable(meter_shutdown):
        meter_shutdown()


@contextmanager
def trace_operation(name: str, **attributes: Any) -> Iterator[trace.Span]:
    tracer = trace.get_tracer(TRACER_NAME)
    started = time.perf_counter()
    with tracer.start_as_current_span(name, kind=SpanKind.INTERNAL) as span:
        for key, value in attributes.items():
            if value is not None and value != "":
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.set_status(StatusCode.ERROR, f"{type(exc).__name__}: {exc}")
            raise
        finally:
            _operation_duration.record(
                time.perf_counter() - started,
                {"sleeper.tui.operation": name},
            )


@contextmanager
def trace_http_client(method: str, url_template: str) -> Iterator[trace.Span]:
    tracer = trace.get_tracer(TRACER_NAME)
    with tracer.start_as_current_span(f"{method} {url_template}", kind=SpanKind.CLIENT) as span:
        span.set_attribute("http.request.method", method)
        span.set_attribute("url.template", url_template)
        span.set_attribute("server.address", "api.sleeper.app")
        span.set_attribute("server.port", 443)
        try:
            yield span
        except Exception as exc:
            span.set_status(StatusCode.ERROR, f"{type(exc).__name__}: {exc}")
            raise
