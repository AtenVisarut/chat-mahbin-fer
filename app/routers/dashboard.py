import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.dependencies import analytics_tracker, alert_manager

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")
limiter = Limiter(key_func=get_remote_address)


@router.get("/dashboard", response_class=HTMLResponse)
@limiter.limit("30/minute")
async def dashboard(request: Request):
    if not request.session.get("user"):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/api/analytics/dashboard")
@limiter.limit("60/minute")
async def get_dashboard_data(request: Request, days: int = 1):
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not analytics_tracker:
        raise HTTPException(status_code=503, detail="Analytics service not available")
    return await analytics_tracker.get_dashboard_stats(days=days)


@router.get("/api/analytics/health")
@limiter.limit("60/minute")
async def get_system_health(request: Request):
    if not analytics_tracker:
        raise HTTPException(status_code=503, detail="Analytics service not available")
    return await analytics_tracker.get_system_health()


@router.get("/api/analytics/alerts")
@limiter.limit("60/minute")
async def get_alerts(request: Request):
    if not alert_manager:
        raise HTTPException(status_code=503, detail="Alert service not available")
    return await alert_manager.get_active_alerts()
