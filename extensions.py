"""放置数据库、模板和通用基础设施函数。"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import APP_NAME, DATABASE_URL, TEMPLATE_DIR


def now_beijing_naive() -> datetime:
    """当前北京时间，去掉 tzinfo 写入 DateTime（与库内既有 naive 字段类型一致）。"""
    return datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)


Base = declarative_base()


engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
templates.env.globals["app_name"] = APP_NAME


def get_db():
    """为每次请求提供独立数据库会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def add_flash(request: Request, message: str, category: str = "info") -> None:
    """把一次性提示消息写入 session，供下次页面渲染读取。"""
    flashes = list(request.session.get("_flash_messages", []))
    flashes.append({"category": category, "message": message})
    request.session["_flash_messages"] = flashes


def pop_flash_messages(request: Request) -> list[dict[str, str]]:
    """读取并清空一次性提示消息。"""
    return list(request.session.pop("_flash_messages", []))


def render_template(
    request: Request,
    template_name: str,
    status_code: int = 200,
    **context: Any,
):
    """统一给模板注入 request 和全局提示消息。"""
    template_context = {
        "request": request,
        "messages": pop_flash_messages(request),
        **context,
    }
    return templates.TemplateResponse(request, template_name, template_context, status_code=status_code)
