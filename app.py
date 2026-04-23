"""FastAPI 应用入口，负责组装路由、中间件和启动流程。"""

import uvicorn
from fastapi import FastAPI, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from config import APP_HOST, APP_NAME, APP_PORT, SESSION_SECRET, STATIC_DIR
from routes.auth import router as auth_router
from routes.dashboard import router as dashboard_router
from routes.ocr import router as ocr_router
from routes.stats import router as stats_router


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    app = FastAPI(title=APP_NAME) # title 用于 API 文档（如 Swagger UI）的标题

    # 登录中间件
    app.add_middleware(
        SessionMiddleware,
        secret_key=SESSION_SECRET,
        same_site="lax",
        https_only=False,
    )

    # 将 URL 前缀 /static 映射到 STATIC_DIR（如 static/），让浏览器可以访问 CSS、JS 等静态资源。
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


    app.include_router(auth_router)
    app.include_router(ocr_router)
    app.include_router(stats_router)
    app.include_router(dashboard_router)

    @app.get("/", include_in_schema=False)
    def index(request: Request):
        """根路径默认跳转到统计概览页。"""
        return RedirectResponse(request.url_for("stats_page"), status_code=status.HTTP_303_SEE_OTHER)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app:app", host=APP_HOST, port=APP_PORT, reload=True)
