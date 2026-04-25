"""公开数据看板页面路由。"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from extensions import get_db, render_template
from services.dashboard_service import SHIFT_OPTIONS, build_dashboard_context
from services.export import (
    build_dashboard_export_bytes,
    export_rows_is_empty,
    fetch_dashboard_records_for_export,
)


router = APIRouter()


@router.get("/dashboard", name="dashboard_page")
def page(request: Request, db: Session = Depends(get_db)):
    """渲染无需登录的数据看板。"""
    context = build_dashboard_context(
        db,
        key_name=request.query_params.get("key"),
        process_name=request.query_params.get("process"),
        shift_name=request.query_params.get("shift"),
        start_date=request.query_params.get("start_date"),
        end_date=request.query_params.get("end_date"),
        batch=request.query_params.get("batch"),
        line=request.query_params.get("line"),
        inspection_location=request.query_params.get("inspection_location"),
        production_name=request.query_params.get("production_name"),
    )
    return render_template(request, "dashboard.html", **context)


@router.get("/dashboard/export", name="dashboard_export")
def export_dashboard(
    db: Session = Depends(get_db),
    key: str | None = None,
    process: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    production_name: str | None = None,
    inspection_location: str | None = None,
    shift: str | None = None,
):
    """按 key、製程、日期区间、品名与班别导出 Excel；金加 CNC0 时含抽检位置。不含批次/线别筛选。"""
    try:
        selected_key, selected_process, start_value, end_value, records = (
            fetch_dashboard_records_for_export(
                db,
                key_name=key,
                process_name=process,
                start_date=start_date,
                end_date=end_date,
                production_name=production_name,
                inspection_location=inspection_location,
                shift_name=shift,
            )
        )
    except ValueError as exc:
        return JSONResponse(
            {"success": False, "message": str(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    if export_rows_is_empty(records):
        return JSONResponse(
            {"success": False, "message": "所选日期范围内暂无数据。"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    payload = build_dashboard_export_bytes(
        key,
        process,
        data=records,
        production_name=production_name,
        inspection_location=inspection_location,
        shift=shift,
    )
    sel_shift = shift if shift in SHIFT_OPTIONS else "不限"
    shift_seg = f"_{sel_shift}" if sel_shift != "不限" else ""
    fname = (
        f"看板_{selected_key}_{selected_process}{shift_seg}_{start_value.isoformat()}_{end_value.isoformat()}.xlsx"
    )
    ascii_fallback = f"dashboard_{start_value.isoformat()}_{end_value.isoformat()}.xlsx"
    cd = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(fname)}"
    return StreamingResponse(
        iter([payload]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": cd},
    )
