"""登录与退出登录路由，负责最基础的密码门禁。"""

from fastapi import APIRouter, Form, Request, status
from fastapi.responses import RedirectResponse

from config import APP_PASSWORD
from extensions import add_flash, render_template


router = APIRouter()


def is_authenticated(request: Request) -> bool:
    """判断当前 session 是否已经登录。"""
    return bool(request.session.get("authenticated"))


def require_login(request: Request) -> RedirectResponse | None:
    """未登录时返回跳转响应，已登录时返回 None。"""
    if is_authenticated(request):
        return None
    return RedirectResponse(request.url_for("login_page"), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/login", name="login_page")
def login_page(request: Request):
    """展示登录页面；已登录用户直接跳到 OCR 页面。"""
    if is_authenticated(request):
        return RedirectResponse(request.url_for("ocr_page"), status_code=status.HTTP_303_SEE_OTHER)
    return render_template(request, "login.html")


@router.post("/login", name="login_submit")
def login(request: Request, password: str = Form(...)):
    """校验访问密码并写入登录态。"""
    if password == APP_PASSWORD:
        request.session["authenticated"] = True
        return RedirectResponse(request.url_for("ocr_page"), status_code=status.HTTP_303_SEE_OTHER)

    add_flash(request, "密码错误，请重试。", "error")
    return RedirectResponse(request.url_for("login_page"), status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout", name="logout")
def logout(request: Request):
    """清空登录态并回到登录页面。"""
    request.session.clear()
    return RedirectResponse(request.url_for("login_page"), status_code=status.HTTP_303_SEE_OTHER)
