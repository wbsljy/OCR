"""OCR 主流程路由，负责页面展示、文件解析和结果下载。"""

import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import MAX_CONTENT_LENGTH, RESULT_DIR, UPLOAD_DIR
from data_process import md_process
from extensions import get_db, now_beijing_naive, render_template
from models import OcrResult, OcrTask
from routes.auth import is_authenticated, require_login
from services.dashboard_service import (
    apply_verified_dashboard_writes,
    parse_verified_markdown_to_records,
)
from services.ocr_client import OcrClient


router = APIRouter()
logger = logging.getLogger(__name__)
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}


def _unverified_task_id_list(db: Session) -> list[int]:
    """成功且未验证的任务 ID 列表，与统计页 dedupe 语义一致（新到旧）。"""
    stmt = (
        select(OcrTask, OcrResult)
        .join(OcrResult, OcrResult.task_id == OcrTask.id)
        .where(OcrTask.status == "success", OcrResult.is_verified == False)  # noqa: E712
        .order_by(OcrTask.created_at.desc(), OcrResult.id.desc())
    )
    rows = db.execute(stmt).all()
    seen: set[int] = set()
    out: list[int] = []
    for task, _result in rows:
        if task.id in seen:
            continue
        seen.add(task.id)
        out.append(task.id)
    return out


class VerifyRequestBody(BaseModel):
    """通过验证时提交的校对稿（与前端渲染区 HTML 结构一致）。"""

    verified_markdown: str = Field(..., min_length=1, description="用户确认后的正文")
    force_overwrite: bool = Field(
        False,
        description="与他任务业务键冲突时是否覆盖已有看板行",
    )


def sanitize_verified_html(content: str) -> str:
    """移除危险标签，与前端 sanitizeBasicHtml 思路一致。"""
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup.find_all(["script", "iframe", "object", "embed"]):
        tag.decompose()
    if soup.body:
        return soup.body.decode_contents()
    return str(soup)


@router.get("/ocr", name="ocr_page")
def page(request: Request, db: Session = Depends(get_db)):
    """渲染 OCR 主页面并展示最近任务。支持 ?task_id= 直接进入验证页。"""
    redirect_response = require_login(request)
    if redirect_response:
        return redirect_response

    recent_tasks = db.scalars(
        select(OcrTask).order_by(OcrTask.created_at.desc()).limit(20)
    ).all()
    task_id_str = request.query_params.get("task_id")
    preset_task_id = int(task_id_str) if task_id_str is not None else None
    unverified_task_ids = _unverified_task_id_list(db)
    return render_template(
        request,
        "ocr.html",
        recent_tasks=recent_tasks,
        preset_task_id=preset_task_id,
        unverified_task_ids=unverified_task_ids,
    )


@router.get("/api/tasks/unverified-queue", name="unverified_task_queue")
def unverified_task_queue(request: Request, db: Session = Depends(get_db)):
    """返回待验证任务 ID 列表（新到旧），供 OCR 页队列导航。"""
    if not is_authenticated(request):
        return JSONResponse(
            {"success": False, "message": "请先登录。"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    return JSONResponse({"success": True, "task_ids": _unverified_task_id_list(db)})


@router.post("/api/parse", name="parse_file")
def parse_file(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """接收上传文件、按页落盘（PDF 每页一文件）、调用 OCR 并写入数据库。"""

    # 理论上前端不登录不会触发解析，这里防止绕开前端直接api调用
    if not is_authenticated(request):
        return JSONResponse(
            {"success": False, "message": "请先登录后再执行 OCR 解析。"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    file_ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if file_ext not in ALLOWED_EXTENSIONS:
        return JSONResponse(
            {"success": False, "message": "仅支持 PDF、PNG、JPG、JPEG文件。"},
            status_code=400,
        )

    client = OcrClient(
        api_url="https://mineru.net/api/v4",
        api_token="eyJ0eXBlIjoiSldUIiwiYWxnIjoiSFM1MTIifQ.eyJqdGkiOiIzNTYwMDUwMyIsInJvbCI6IlJPTEVfUkVHSVNURVIiLCJpc3MiOiJPcGVuWExhYiIsImlhdCI6MTc3MzEyNTgwMywiY2xpZW50SWQiOiJsa3pkeDU3bnZ5MjJqa3BxOXgydyIsInBob25lIjoiIiwib3BlbklkIjpudWxsLCJ1dWlkIjoiZjIyZGJlY2QtNGQyZS00ZjY3LTg5ODEtOTEyODRlNmRmYzYzIiwiZW1haWwiOiIiLCJleHAiOjE3ODA5MDE4MDN9.UoxVhN6crjwqOWkKgXUKmqAADNjzBy1NCZiAEMA98JO95UdxHRh8NGpgwUNAA2aFQb7L_hPjd7ICLDlRavmcxA",
        model_version="vlm",
        language="ch",
        timeout=120,
        poll_interval=2,
    )

    temp_full_pdf: Path | None = None

    try:
        if file_ext == "pdf":
            fd, tmp_str = tempfile.mkstemp(suffix=".pdf")
            temp_full_pdf = Path(tmp_str)
            try:
                with os.fdopen(fd, "wb") as tmp_handle:
                    shutil.copyfileobj(file.file, tmp_handle)
            except Exception:
                temp_full_pdf.unlink(missing_ok=True)
                raise
            finally:
                file.file.close()

            full_size = temp_full_pdf.stat().st_size
            if full_size > MAX_CONTENT_LENGTH:
                temp_full_pdf.unlink(missing_ok=True)
                temp_full_pdf = None
                return JSONResponse(
                    {"success": False, "message": "上传文件超过大小限制。"},
                    status_code=400,
                )

            reader = PdfReader(str(temp_full_pdf))
            num_pages = len(reader.pages)
            if num_pages == 0:
                temp_full_pdf.unlink(missing_ok=True)
                temp_full_pdf = None
                return JSONResponse(
                    {"success": False, "message": "PDF 不包含任何页面。"},
                    status_code=400,
                )

            stem = Path(file.filename or "document.pdf").stem
            stem_safe = re.sub(r"[^A-Za-z0-9._-]", "_", stem) or "document"

            task_ids: list[int] = []
            page_results: list[dict] = []
            total_elapsed = 0

            for i in range(num_pages):
                page_num = i + 1
                stored_name = build_stored_name(f"{stem_safe}_page_{page_num}.pdf")
                permanent_path = UPLOAD_DIR / stored_name
                writer = PdfWriter()
                writer.add_page(reader.pages[i])
                with permanent_path.open("wb") as out_f:
                    writer.write(out_f)

                page_size = permanent_path.stat().st_size
                task = OcrTask(
                    stored_file_name=stored_name,
                    file_path=str(permanent_path),
                    file_type=file_ext,
                    file_size=page_size,
                    status="processing",
                )
                db.add(task)
                db.commit()
                db.refresh(task)

                try:
                    result = client.parse_file(str(permanent_path))
                    md = result.get("markdown", "").strip()
                    print("md",md)
                    if not md:
                        raise ValueError("OCR 接口返回成功，但未提取到 Markdown 内容。")
                    total_elapsed += result.get("elapsed_ms", 0)

                    task.status = "success"
                    task.ocr_elapsed_ms = result.get("elapsed_ms")
                    md=md_process(md)
                    db.add(
                        OcrResult(
                            task_id=task.id,
                            markdown_content=md,
                            is_verified=False,
                        )
                    )
                    save_markdown_page(task.id, md)
                    db.commit()
                    task_ids.append(task.id)
                    page_results.append(
                        {
                            "task_id": task.id,
                            "markdown": md,
                            "is_verified": False,
                            "file_url": f"/uploads/{stored_name}",
                            "file_type": file_ext,
                        }
                    )
                except Exception as page_exc:  # noqa: BLE001
                    logger.exception("PDF 第 %d 页 OCR 失败: task_id=%s", page_num, task.id)
                    task.status = "failed"
                    task.error_message = str(page_exc)
                    db.commit()
                    raise

            return JSONResponse(
                {
                    "success": True,
                    "task_ids": task_ids,
                    "task_id": task_ids[0] if task_ids else None,
                    "file_type": file_ext,
                    "pages": page_results,
                    "total_pages": len(page_results),
                    "elapsed_ms": total_elapsed,
                    "message": "解析完成",
                }
            )

        # region 图片分支：直接落盘 UPLOAD_DIR，一文件一task
        stored_name = build_stored_name(file.filename or "upload.bin")
        save_path = UPLOAD_DIR / stored_name
        with save_path.open("wb") as file_handle:
            shutil.copyfileobj(file.file, file_handle)
        file.file.close()

        file_size = save_path.stat().st_size
        if file_size > MAX_CONTENT_LENGTH:
            save_path.unlink(missing_ok=True)
            return JSONResponse(
                {"success": False, "message": "上传文件超过大小限制。"},
                status_code=400,
            )

        task = OcrTask(
            stored_file_name=stored_name,
            file_path=str(save_path),
            file_type=file_ext,
            file_size=file_size,
            status="processing",
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        result = client.parse_file(str(save_path))
        markdown = result.get("markdown", "").strip()

        if not markdown:
            raise ValueError("OCR 接口返回成功，但未提取到 Markdown 内容。")

        task.status = "success"
        task.ocr_elapsed_ms = result.get("elapsed_ms")

        markdown=md_process(markdown)

        page_results = [
            {
                "task_id": task.id,
                "markdown": markdown,
                "is_verified": False,
                "file_url": f"/uploads/{stored_name}",
                "file_type": file_ext,
            }
        ]

        db.add(
            OcrResult(
                task_id=task.id,
                markdown_content=markdown,
                is_verified=False,
            )
        )
        save_markdown_page(task.id, markdown)
        db.commit()

        return JSONResponse(
            {
                "success": True,
                "task_ids": [task.id],
                "task_id": task.id,
                "stored_file_name": task.stored_file_name,
                "file_type": task.file_type,
                "pages": page_results,
                "total_pages": 1,
                "markdown": markdown,
                "status": task.status,
                "elapsed_ms": task.ocr_elapsed_ms,
                "message": "解析完成",
            }
        )
        #endregion
        
    except Exception as exc:  # noqa: BLE001
        logger.exception("OCR 解析失败")
        return JSONResponse(
            {"success": False, "message": f"OCR 服务调用失败：{exc}"},
            status_code=500,
        )
    finally:
        if temp_full_pdf is not None:
            try:
                temp_full_pdf.unlink(missing_ok=True)
            except OSError:
                pass


@router.get("/api/task/{task_id:int}/result", name="task_result")
def task_result(
    request: Request,
    task_id: int,
    db: Session = Depends(get_db),
):
    """获取指定任务的识别结果，供前端加载历史记录。"""
    redirect_response = require_login(request)
    if redirect_response:
        return redirect_response

    task = db.get(OcrTask, task_id)
    if not task or task.status != "success":
        return JSONResponse(
            {"success": False, "message": "任务不存在或未完成。"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    result = (
        db.scalars(
            select(OcrResult)
            .where(OcrResult.task_id == task_id)
            .order_by(OcrResult.id.desc())
            .limit(1)
        ).first()
    )
    if not result:
        return JSONResponse(
            {"success": False, "message": "未找到识别结果。"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    raw = (result.verified_markdown or result.markdown_content or "").strip()
    pages = [{"markdown": p.strip()} for p in raw.split("\f") if p.strip()]
    if not pages and raw.strip():
        pages = [{"markdown": raw}]

    file_url = f"/uploads/{task.stored_file_name}"
    pages_with_meta = []
    for p in pages:
        if isinstance(p, dict):
            pages_with_meta.append(
                {
                    **p,
                    "task_id": task.id,
                    "is_verified": result.is_verified,
                    "file_url": file_url,
                    "file_type": task.file_type,
                }
            )
        else:
            pages_with_meta.append(
                {
                    "markdown": str(p) if p else "",
                    "task_id": task.id,
                    "is_verified": result.is_verified,
                    "file_url": file_url,
                    "file_type": task.file_type,
                }
            )

    has_verified = bool(result.verified_markdown and result.verified_markdown.strip())
    return JSONResponse(
        {
            "success": True,
            "task_id": task.id,
            "stored_file_name": task.stored_file_name,
            "file_url": file_url,
            "file_type": task.file_type,
            "pages": pages_with_meta,
            "total_pages": len(pages),
            "is_verified": result.is_verified,
            "has_verified_markdown": has_verified,
        }
    )


@router.post("/api/task/{task_id:int}/verify", name="task_verify")
def task_verify(
    request: Request,
    task_id: int,
    body: VerifyRequestBody,
    db: Session = Depends(get_db),
):
    """写入校对稿并标记任务为已验证。"""
    if not is_authenticated(request):
        return JSONResponse(
            {"success": False, "message": "请先登录。"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    task = db.get(OcrTask, task_id)
    if not task or task.status != "success":
        return JSONResponse(
            {"success": False, "message": "任务不存在或未完成。"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    ocr_result = (
        db.scalars(
            select(OcrResult)
            .where(OcrResult.task_id == task_id)
            .order_by(OcrResult.id.desc())
            .limit(1)
        ).first()
    )
    if not ocr_result:
        return JSONResponse(
            {"success": False, "message": "未找到识别结果。"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    cleaned = sanitize_verified_html(body.verified_markdown).strip()
    if not cleaned:
        return JSONResponse(
            {"success": False, "message": "verified_markdown 清洗后为空，请检查内容。"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        records = parse_verified_markdown_to_records(
            cleaned,
            task_id=task.id,
            ocr_result_id=ocr_result.id,
        )
    except ValueError as exc:
        return JSONResponse(
            {"success": False, "message": f"结构化入库失败：{exc}"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if not records:
        return JSONResponse(
            {
                "success": False,
                "message": "未从 verified_markdown 中解析出可入库的数据块。",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    conflicts = apply_verified_dashboard_writes(
        db,
        task.id,
        ocr_result,
        records,
        force_overwrite=body.force_overwrite,
    )
    if conflicts:
        return JSONResponse(
            {
                "success": False,
                "code": "dashboard_duplicate",
                "message": "已存在相同业务键的看板记录（生产日期、班别、品名；锻压另含页码；CNC0 另含抽检位置），是否覆盖？",
                "conflicts": conflicts,
            },
            status_code=status.HTTP_409_CONFLICT,
        )
    ocr_result.verified_markdown = cleaned
    ocr_result.is_verified = True
    db.commit()
    return JSONResponse({"success": True, "message": "已保存校对稿并标记为通过验证。"})


@router.get("/uploads/{filename:path}", name="uploaded_file")
def uploaded_file(request: Request, filename: str):
    """返回已上传的文件，供页面预览使用。"""
    redirect_response = require_login(request)
    if redirect_response:
        return redirect_response

    upload_dir = UPLOAD_DIR.resolve()
    file_path = (upload_dir / filename).resolve()
    if upload_dir not in file_path.parents or not file_path.is_file():
        return JSONResponse({"detail": "文件不存在。"}, status_code=status.HTTP_404_NOT_FOUND)

    return FileResponse(file_path)


def build_stored_name(original_name: str) -> str:
    """构造安全且尽量不重复的落盘文件名。时间戳 + 处理后的原文件名"""
    base_name = Path(original_name).name
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", base_name) or "upload.bin"
    timestamp = now_beijing_naive().strftime("%Y%m%d%H%M%S")
    return f"{timestamp}_{safe_name}"


def save_markdown_page(task_id: int, markdown: str) -> None:
    """将 OCR 结果持久化为 parsed_results/task_{id}.md（每个 task 一份）。"""
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    if not markdown:
        return
    path = RESULT_DIR / f"task_{task_id}.md"
    path.write_text(markdown, encoding="utf-8")

