"""统计页面路由，输出当前 OCR 任务的基础概览数据。"""

from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import RESULT_DIR, UPLOAD_DIR
from extensions import get_db, render_template
from models import OcrResult, OcrTask
from routes.auth import is_authenticated
from services.dashboard_service import (
    KEY_PROCESS_OPTIONS,
    SHIFT_OPTIONS,
    delete_dashboard_records_for_task,
    infer_dashboard_key_from_markdown,
    list_board_records_for_stats,
)

router = APIRouter()


def _parse_date_param(raw: str | None) -> date | None:
    if not raw or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _dedupe_unverified_task_rows(db: Session) -> list[tuple[OcrTask, OcrResult]]:
    """成功且未验证的任务，每个 task 只保留最新一条 ocr_result。"""
    stmt = (
        select(OcrTask, OcrResult)
        .join(OcrResult, OcrResult.task_id == OcrTask.id)
        .where(OcrTask.status == "success", OcrResult.is_verified == False)  # noqa: E712
        .order_by(OcrTask.created_at.desc(), OcrResult.id.desc())
    )
    rows = db.execute(stmt).all()
    seen: set[int] = set()
    out: list[tuple[OcrTask, OcrResult]] = []
    for task, result in rows:
        if task.id in seen:
            continue
        seen.add(task.id)
        out.append((task, result))
    return out


def _safe_unlink_upload_file(file_path: str | None) -> None:
    """仅允许删除 UPLOAD_DIR 下文件，避免路径越界。"""
    if not file_path:
        return
    try:
        upload_root = UPLOAD_DIR.resolve()
        target = Path(file_path).resolve()
    except OSError:
        return
    if upload_root not in target.parents or not target.is_file():
        return
    try:
        target.unlink(missing_ok=True)
    except OSError:
        return


@router.get("/stats", name="stats_page")
def page(request: Request, db: Session = Depends(get_db)):
    """渲染统计页面并聚合最近的任务数据。"""
    total_count = db.scalar(select(func.count()).select_from(OcrTask)) or 0
    success_count = db.scalar(
        select(func.count()).select_from(OcrTask).where(OcrTask.status == "success")
    ) or 0
    failed_count = db.scalar(
        select(func.count()).select_from(OcrTask).where(OcrTask.status == "failed")
    ) or 0
    verified_count = db.scalar(
        select(func.count())
        .select_from(OcrTask)
        .join(OcrResult, OcrResult.task_id == OcrTask.id)
        .where(OcrTask.status == "success", OcrResult.is_verified == True)  # noqa: E712
    ) or 0
    unverified_count = db.scalar(
        select(func.count())
        .select_from(OcrTask)
        .join(OcrResult, OcrResult.task_id == OcrTask.id)
        .where(OcrTask.status == "success", OcrResult.is_verified == False)  # noqa: E712
    ) or 0
    avg_elapsed = db_avg_elapsed(db)

    unverified_chongya: list[OcrTask] = []
    unverified_jinjia: list[OcrTask] = []
    unverified_unknown: list[OcrTask] = []
    for task, result in _dedupe_unverified_task_rows(db):
        inferred = infer_dashboard_key_from_markdown(result.markdown_content)
        if inferred == "沖壓":
            unverified_chongya.append(task)
        elif inferred == "金加":
            unverified_jinjia.append(task)
        else:
            unverified_unknown.append(task)

    qp = request.query_params
    end_default = date.today()
    start_default = end_default - timedelta(days=29)
    v_end = _parse_date_param(qp.get("v_end")) or end_default
    v_start = _parse_date_param(qp.get("v_start")) or start_default
    if v_start > v_end:
        v_start, v_end = v_end, v_start

    cy_process = qp.get("cy_process") or ""
    cy_process = cy_process if cy_process in KEY_PROCESS_OPTIONS["沖壓"] else None
    cy_shift = qp.get("cy_shift") or ""
    cy_shift = cy_shift if cy_shift in ("白班", "晚班") else None

    jj_process = qp.get("jj_process") or ""
    jj_process = jj_process if jj_process in KEY_PROCESS_OPTIONS["金加"] else None
    jj_shift = qp.get("jj_shift") or ""
    jj_shift = jj_shift if jj_shift in ("白班", "晚班") else None

    verified_board_chongya = list_board_records_for_stats(
        db,
        key_name="沖壓",
        process_name=cy_process,
        shift_filter=cy_shift,
        start_date=v_start,
        end_date=v_end,
    )
    verified_board_jinjia = list_board_records_for_stats(
        db,
        key_name="金加",
        process_name=jj_process,
        shift_filter=jj_shift,
        start_date=v_start,
        end_date=v_end,
    )

    return render_template(
        request,
        "stats.html",
        total_count=total_count,
        success_count=success_count,
        failed_count=failed_count,
        verified_count=verified_count,
        unverified_count=unverified_count,
        avg_elapsed=avg_elapsed,
        unverified_chongya_tasks=unverified_chongya,
        unverified_jinjia_tasks=unverified_jinjia,
        unverified_unknown_tasks=unverified_unknown,
        verified_board_chongya=verified_board_chongya,
        verified_board_jinjia=verified_board_jinjia,
        v_start=v_start.isoformat(),
        v_end=v_end.isoformat(),
        cy_process=cy_process or "",
        cy_shift=cy_shift or "",
        jj_process=jj_process or "",
        jj_shift=jj_shift or "",
        chongya_process_options=KEY_PROCESS_OPTIONS["沖壓"],
        jinjia_process_options=KEY_PROCESS_OPTIONS["金加"],
        shift_options=SHIFT_OPTIONS,
    )


@router.post("/api/stats/unverified-task/{task_id:int}/delete", name="stats_delete_unverified_task")
def delete_unverified_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    """删除待验证任务及其关联文件；已验证任务不允许删除。"""
    if not is_authenticated(request):
        return JSONResponse(
            {"success": False, "message": "请先登录。"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    task = db.get(OcrTask, task_id)
    if not task or task.status != "success":
        return JSONResponse(
            {"success": False, "message": "任务不存在或不可删除。"},
            status_code=status.HTTP_404_NOT_FOUND,
        )

    has_verified = db.scalar(
        select(func.count())
        .select_from(OcrResult)
        .where(OcrResult.task_id == task_id, OcrResult.is_verified == True)  # noqa: E712
    ) or 0
    if has_verified:
        return JSONResponse(
            {"success": False, "message": "已验证任务不允许删除。"},
            status_code=status.HTTP_409_CONFLICT,
        )

    has_unverified = db.scalar(
        select(func.count())
        .select_from(OcrResult)
        .where(OcrResult.task_id == task_id, OcrResult.is_verified == False)  # noqa: E712
    ) or 0
    if not has_unverified:
        return JSONResponse(
            {"success": False, "message": "当前任务不在待验证队列中。"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    delete_dashboard_records_for_task(db, task_id)
    parsed_path = RESULT_DIR / f"task_{task_id}.md"
    try:
        parsed_path.unlink(missing_ok=True)
    except OSError:
        pass
    _safe_unlink_upload_file(task.file_path)
    db.delete(task)
    db.commit()
    return JSONResponse({"success": True, "message": "待验证任务已删除。"})


def db_avg_elapsed(db: Session) -> int:
    """计算 OCR 平均耗时，供统计卡片展示。"""
    value = db.scalar(select(func.avg(OcrTask.ocr_elapsed_ms)))
    return int(value) if value else 0
