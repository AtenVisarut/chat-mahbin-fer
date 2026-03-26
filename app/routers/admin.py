import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import ADMIN_USERNAME, ADMIN_PASSWORD, EMBEDDING_MODEL
from app.dependencies import openai_client, supabase_client
from app.services.cache import clear_all_caches

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory="templates")


class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request, login_data: LoginRequest):
    if login_data.username == ADMIN_USERNAME and login_data.password == ADMIN_PASSWORD:
        request.session["user"] = "admin"
        return {"status": "success", "message": "Login successful"}
    else:
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "Invalid username or password"}
        )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login")


@router.post("/cache/clear")
async def clear_cache_endpoint(request: Request):
    await clear_all_caches()
    return {"status": "success", "message": "All caches cleared"}


@router.post("/admin/regenerate-embeddings")
async def regenerate_embeddings_endpoint(request: Request):
    """
    Regenerate embeddings for mahbin_npk fertilizer data after changes.
    Body (optional): {"crop": "นาข้าว"}  — regenerate one crop
    Body empty or {}                      — regenerate ALL rows
    """
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not openai_client or not supabase_client:
        raise HTTPException(status_code=503, detail="OpenAI or Supabase not available")

    try:
        body = await request.json()
    except Exception:
        body = {}

    crop_filter = body.get("crop")

    # Fetch rows to regenerate
    if crop_filter:
        result = supabase_client.table('mahbin_npk').select('*').ilike('crop', f'%{crop_filter}%').execute()
    else:
        result = supabase_client.table('mahbin_npk').select('*').execute()

    if not result.data:
        return {"status": "error", "message": f"ไม่พบข้อมูลพืช: {crop_filter}" if crop_filter else "ไม่พบข้อมูลในระบบ"}

    rows = result.data
    success_count = 0
    errors = []

    for row in rows:
        try:
            text_parts = [
                f"พืช: {row.get('crop', '')}",
                f"ระยะการเติบโต: {row.get('growth_stage', '')}",
                f"สูตรปุ๋ย: {row.get('fertilizer_formula', '')}",
                f"อัตราการใช้: {row.get('usage_rate', '')}",
                f"ธาตุอาหารหลัก: {row.get('primary_nutrients', '')}",
                f"ประโยชน์: {row.get('benefits', '')}",
            ]
            text = " | ".join([p for p in text_parts if p])

            resp = await openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=text
            )
            embedding = resp.data[0].embedding

            supabase_client.table('mahbin_npk').update({
                'embedding': embedding
            }).eq('id', row['id']).execute()

            success_count += 1
        except Exception as e:
            errors.append(f"{row.get('crop', '?')} / {row.get('growth_stage', '?')}: {str(e)}")

    # Clear caches so new embeddings take effect immediately
    await clear_all_caches()

    return {
        "status": "success",
        "regenerated": success_count,
        "total": len(rows),
        "errors": errors if errors else None,
        "cache_cleared": True
    }
