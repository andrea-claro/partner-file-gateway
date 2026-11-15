"""FastAPI app: overview, transfers, partners and the upload simulator.

Read-only by design: the only state-changing endpoint is POST /simulate, which
performs a rate-limited SFTP upload of a bundled sample file as the demo partner.

Run: uvicorn --factory dashboard.main:create_app
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import jinja2
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dashboard.ratelimit import SlidingWindowLimiter
from dashboard.repository import STATUSES, Repository
from dashboard.settings import Settings
from dashboard.simulator import SftpUploader, Simulator, list_samples

PACKAGE_DIR = Path(__file__).resolve().parent

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


def human_bytes(value: Any) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "-"


def short_time(value: Any) -> str:
    if not value:
        return "-"
    try:
        moment = datetime.fromisoformat(str(value)).astimezone(UTC)
    except ValueError:
        return str(value)
    return moment.strftime("%Y-%m-%d %H:%M:%S UTC")


def build_templates() -> Jinja2Templates:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(PACKAGE_DIR / "templates"),
        autoescape=True,
    )
    env.filters["bytes"] = human_bytes
    env.filters["time"] = short_time
    return Jinja2Templates(env=env)


def client_ip(request: Request) -> str:
    # Behind Cloudflare Tunnel the visitor address is in CF-Connecting-IP. The
    # dashboard port only listens on 127.0.0.1, so the header cannot be forged
    # from outside the tunnel.
    return request.headers.get("cf-connecting-ip") or (
        request.client.host if request.client else "unknown"
    )


def create_app(
    settings: Settings | None = None,
    repository: Repository | None = None,
    simulator: Simulator | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    repository = repository or Repository(
        boto3.resource("dynamodb"), settings.transfers_table, settings.partners_table
    )
    if simulator is None:
        simulator = Simulator(
            list_samples(settings.samples_dir),
            SftpUploader(
                settings.sftp_host,
                settings.sftp_port,
                settings.simulator_partner,
                settings.simulator_key,
                settings.known_hosts,
            ),
        )
    per_ip = SlidingWindowLimiter(settings.simulate_per_ip_per_minute)
    overall = SlidingWindowLimiter(settings.simulate_global_per_minute)
    templates = build_templates()

    app = FastAPI(title="partner-file-gateway", docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.exception_handler(BotoCoreError)
    @app.exception_handler(ClientError)
    async def backend_unavailable(request: Request, exc: Exception) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "unavailable.html",
            {"active": "", "error": type(exc).__name__},
            status_code=503,
        )

    def render(request: Request, name: str, **context: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, name, context)

    def is_htmx(request: Request) -> bool:
        return request.headers.get("hx-request") == "true"

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/", response_class=HTMLResponse)
    def overview(request: Request) -> HTMLResponse:
        return render(
            request,
            "overview.html",
            active="overview",
            summary=repository.summary(datetime.now(UTC)),
            transfers=repository.transfers(limit=10),
            statuses=STATUSES,
        )

    @app.get("/transfers", response_class=HTMLResponse)
    def transfers(
        request: Request,
        status: str | None = None,
        partner: str | None = None,
        limit: int = 100,
    ) -> HTMLResponse:
        status = status if status in STATUSES else None
        partner = partner or None
        items = repository.transfers(status=status, partner=partner, limit=max(1, min(limit, 100)))
        if is_htmx(request):
            return render(request, "_transfer_rows.html", transfers=items)
        return render(
            request,
            "transfers.html",
            active="transfers",
            transfers=items,
            statuses=STATUSES,
            partners=[p["partner_id"] for p in repository.partners()],
            selected_status=status or "",
            selected_partner=partner or "",
        )

    @app.get("/transfers/{transfer_id}", response_class=HTMLResponse)
    def transfer_detail(request: Request, transfer_id: str) -> HTMLResponse:
        item = repository.transfer(transfer_id)
        if item is None:
            return templates.TemplateResponse(
                request, "not_found.html", {"active": "transfers"}, status_code=404
            )
        return render(request, "transfer.html", active="transfers", transfer=item)

    @app.get("/partners", response_class=HTMLResponse)
    def partners(request: Request) -> HTMLResponse:
        return render(request, "partners.html", active="partners", partners=repository.partners())

    @app.post("/simulate", response_class=HTMLResponse)
    def simulate(request: Request) -> HTMLResponse:
        # Custom header = cheap CSRF guard: cross-site forms cannot set it.
        if not is_htmx(request):
            return HTMLResponse("Use the button on the overview page.", status_code=400)
        if not per_ip.allow(client_ip(request)) or not overall.allow("global"):
            return templates.TemplateResponse(
                request,
                "_simulate_result.html",
                {"result": None, "message": "Rate limit reached, try again in a minute."},
                status_code=429,
            )
        try:
            result = simulator.run()
        except Exception:  # any failure is shown to visitors as one generic message
            return templates.TemplateResponse(
                request,
                "_simulate_result.html",
                {"result": None, "message": "The SFTP upload failed. Is the demo partner set up?"},
                status_code=502,
            )
        return render(request, "_simulate_result.html", result=result, message="")

    return app
