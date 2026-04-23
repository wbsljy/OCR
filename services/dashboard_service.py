from __future__ import annotations

"""数据看板的结构化解析、入库与查询服务。"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from bs4 import BeautifulSoup, Tag
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from models import (
    BoardChongyaDuanya,
    BoardChongyaGurong,
    BoardChongyaShixiao,
    BoardJinjiaCnc0,
    BoardJinjiaCnc0Full,
    OcrResult,
    OcrTask,
)

KEY_PROCESS_OPTIONS: dict[str, list[str]] = {
    "沖壓": ["鍛壓", "固熔", "時效"],
    "金加": ["CNC0", "CNC0 全檢"],
}
SHIFT_OPTIONS = ["不限", "白班", "晚班"]
INSPECTION_LOCATION_OPTIONS = ["不限", "製程抽檢", "入庫抽檢"]
PRODUCT_NAME_OPTIONS = ["Y20 Housing", "X3784 Housing"]
DEFAULT_PRODUCT_NAME = PRODUCT_NAME_OPTIONS[0]

PROCESS_MODEL_MAP = {
    ("沖壓", "鍛壓"): BoardChongyaDuanya,
    ("沖壓", "固熔"): BoardChongyaGurong,
    ("沖壓", "時效"): BoardChongyaShixiao,
    ("金加", "CNC0"): BoardJinjiaCnc0,
    ("金加", "CNC0 全檢"): BoardJinjiaCnc0Full,
}


@dataclass
class ParsedDashboardRecord:
    model: type
    unique_filter: dict[str, Any]
    payload: dict[str, Any]


def find_existing_board_row(
    db: Session,
    model: type,
    payload: dict[str, Any],
) -> Any | None:
    """按业务唯一键（生产日期+班别；CNC0 另加抽检位置）查一行。"""
    d = payload["production_date"]
    shift_val = payload.get("shift")
    stmt = select(model).where(model.production_date == d)
    if shift_val is None:
        stmt = stmt.where(model.shift.is_(None))
    else:
        stmt = stmt.where(model.shift == shift_val)
    if model is BoardJinjiaCnc0:
        loc = payload.get("inspection_location")
        if loc is None:
            stmt = stmt.where(model.inspection_location.is_(None))
        else:
            stmt = stmt.where(model.inspection_location == loc)
    return db.scalars(stmt.limit(1)).first()


def _apply_payload_to_board_row(row: Any, payload: dict[str, Any]) -> None:
    for key, val in payload.items():
        if key == "id":
            continue
        setattr(row, key, val)


def collect_dashboard_duplicate_conflicts(
    db: Session,
    records: list[ParsedDashboardRecord],
    current_task_id: int,
) -> list[dict[str, Any]]:
    """与其它任务已占用相同业务键时的冲突列表（供前端提示）。同一 task 下旧 ocr_result 写的行不算冲突。"""
    conflicts: list[dict[str, Any]] = []
    for item in records:
        ex = find_existing_board_row(db, item.model, item.payload)
        if ex and ex.task_id != current_task_id:
            p = item.payload
            row: dict[str, Any] = {
                "process_name": p.get("process_name"),
                "production_date": p["production_date"].isoformat()
                if hasattr(p["production_date"], "isoformat")
                else str(p["production_date"]),
                "shift": p.get("shift"),
                "existing_task_id": ex.task_id,
                "existing_ocr_result_id": ex.ocr_result_id,
            }
            if item.model is BoardJinjiaCnc0:
                row["inspection_location"] = p.get("inspection_location")
            conflicts.append(row)
    return conflicts


def apply_verified_dashboard_writes(
    db: Session,
    task_id: int,
    ocr_result: OcrResult,
    records: list[ParsedDashboardRecord],
    *,
    force_overwrite: bool,
) -> list[dict[str, Any]]:
    """删除本 task 下全部看板行后，按业务键 INSERT 或 UPDATE 他任务已占用的键。
    若存在与他任务的冲突且未确认覆盖，返回 conflicts，且不删不写。"""
    conflicts = collect_dashboard_duplicate_conflicts(db, records, task_id)
    if conflicts and not force_overwrite:
        return conflicts

    delete_dashboard_records_for_task(db, task_id)

    for item in records:
        ex = find_existing_board_row(db, item.model, item.payload)
        if ex:
            _apply_payload_to_board_row(ex, item.payload)
        else:
            db.add(item.model(**item.payload))
        db.flush()
    return []


def upsert_verified_dashboard_records(
    db: Session,
    task: OcrTask,
    ocr_result: OcrResult,
    *,
    records: list[ParsedDashboardRecord] | None = None,
    force_overwrite: bool = True,
) -> int:
    """把 verified_markdown 解析并写入 5 张业务表之一；若调用方已传入 records 则不再解析。"""
    if records is None:
        if not ocr_result.verified_markdown:
            raise ValueError("verified_markdown 为空，无法写入数据看板。")
        records = parse_verified_markdown_to_records(
            ocr_result.verified_markdown,
            task_id=task.id,
            ocr_result_id=ocr_result.id,
        )
    if not records:
        raise ValueError("未从 verified_markdown 中解析出可入库的数据块。")

    pending = apply_verified_dashboard_writes(
        db, task.id, ocr_result, records, force_overwrite=force_overwrite
    )
    if pending:
        raise ValueError("存在未处理的数据看板业务键冲突。")
    return len(records)


def parse_verified_markdown_to_records(
    verified_markdown: str,
    *,
    task_id: int,
    ocr_result_id: int,
) -> list[ParsedDashboardRecord]:
    """把 verified_markdown 解析成 1-N 条结构化业务记录。"""
    soup = BeautifulSoup(f"<div>{verified_markdown}</div>", "html.parser")
    tables = soup.find_all("table")
    records: list[ParsedDashboardRecord] = []
    i = 0
    while i < len(tables):
        table = tables[i]
        if not _is_summary_table(table):
            i += 1
            continue
        if i + 1 >= len(tables):
            break
        summary = _parse_summary_table(tables[i])
        main_table = tables[i + 1]
        block_html = str(tables[i]) + str(main_table)
        summary = _fill_summary_fallbacks(summary, block_html)
        records.append(
            _build_record_from_tables(
                summary,
                main_table,
                task_id=task_id,
                ocr_result_id=ocr_result_id,
            )
        )
        i += 2
    return records


def build_dashboard_context(
    db: Session,
    *,
    key_name: str | None,
    process_name: str | None,
    shift_name: str | None,
    start_date: str | None,
    end_date: str | None,
    batch: str | None = None,
    line: str | None = None,
    inspection_location: str | None = None,
    production_name: str | None = None,
) -> dict[str, Any]:
    """按查询条件构造 SSR 看板上下文。"""
    selected_key = key_name if key_name in KEY_PROCESS_OPTIONS else "沖壓"
    process_options = KEY_PROCESS_OPTIONS[selected_key]
    selected_process = process_name if process_name in process_options else process_options[0]
    selected_shift = shift_name if shift_name in SHIFT_OPTIONS else "不限"
    end_value = _parse_iso_date(end_date) or date.today()
    start_value = _parse_iso_date(start_date) or (end_value - timedelta(days=29))

    selected_batch = (batch or "").strip() or ""
    selected_line = (line or "").strip() or ""
    selected_inspection_location = (
        inspection_location
        if inspection_location in INSPECTION_LOCATION_OPTIONS
        else "不限"
    )
    selected_production_name = (
        production_name if production_name in PRODUCT_NAME_OPTIONS else DEFAULT_PRODUCT_NAME
    )

    model = PROCESS_MODEL_MAP[(selected_key, selected_process)]
    stmt = (
        select(model)
        .where(model.production_date >= start_value, model.production_date <= end_value)
        .order_by(model.production_date.asc())
    )
    if selected_shift != "不限":
        stmt = stmt.where(model.shift == selected_shift)

    if selected_process == "鍛壓" and selected_batch:
        stmt = stmt.where(or_(
            model.batch_1 == selected_batch,
            model.batch_2 == selected_batch,
            model.batch_3 == selected_batch,
            model.batch_4 == selected_batch,
        ))
    if selected_process == "鍛壓" and selected_line:
        stmt = stmt.where(or_(
            model.line_1 == selected_line,
            model.line_2 == selected_line,
            model.line_3 == selected_line,
            model.line_4 == selected_line,
        ))
    elif selected_process == "固熔" and selected_line:
        stmt = stmt.where(or_(
            model.line_1 == selected_line,
            model.line_2 == selected_line,
            model.line_3 == selected_line,
        ))
    if selected_process == "CNC0" and selected_inspection_location != "不限":
        stmt = stmt.where(model.inspection_location == selected_inspection_location)
    stmt = stmt.where(model.product_name == selected_production_name)

    records = db.scalars(stmt).all()

    overview = _build_overview(records, selected_process, selected_batch, selected_line)
    charts = _build_chart_specs(records, selected_process, selected_batch, selected_line)
    table_headers, table_rows = _build_table_data(records, selected_process, selected_batch, selected_line)

    return {
        "selected_key": selected_key,
        "selected_process": selected_process,
        "selected_shift": selected_shift,
        "selected_batch": selected_batch,
        "selected_line": selected_line,
        "selected_inspection_location": selected_inspection_location,
        "selected_production_name": selected_production_name,
        "process_options": process_options,
        "key_options": list(KEY_PROCESS_OPTIONS.keys()),
        "shift_options": SHIFT_OPTIONS,
        "inspection_location_options": INSPECTION_LOCATION_OPTIONS,
        "product_name_options": PRODUCT_NAME_OPTIONS,
        "start_date": start_value.isoformat(),
        "end_date": end_value.isoformat(),
        "overview": overview,
        "chart_specs": charts,
        "table_headers": table_headers,
        "table_rows": table_rows,
    }


def _build_record_from_tables(
    summary: dict[str, str],
    main_table: Tag,
    *,
    task_id: int,
    ocr_result_id: int,
) -> ParsedDashboardRecord:
    process = (summary.get("製程") or "").strip()
    key_name = _key_from_process(process)
    model = PROCESS_MODEL_MAP.get((key_name, process))
    if not model:
        raise ValueError(f"无法识别看板类型：key={key_name}, 製程={process}")

    production_date = _parse_iso_date(summary.get("生產日期"))
    if not production_date:
        raise ValueError("缺少有效的 生產日期，无法写入看板表。")

    common_payload = {
        "task_id": task_id,
        "ocr_result_id": ocr_result_id,
        "key_name": key_name,
        "production_date": production_date,
        "shift": summary.get("班別"),
        "product_name": summary.get("品名"),
        "process_name": process,
    }
    if model is BoardJinjiaCnc0:
        common_payload["inspection_location"] = summary.get("抽檢位置")
    grid = _table_to_grid(main_table)

    if model is BoardChongyaDuanya:
        print("gird",grid)
        payload = build_duanya_payload(grid)
        unique_filter = {
            "key_name": key_name,
            "process_name": process,
        }
    elif model is BoardChongyaGurong:
        payload = build_gurong_payload(grid)
        unique_filter = {
            "key_name": key_name,
            "process_name": process,
        }
    elif model is BoardChongyaShixiao:
        payload = build_shixiao_payload(grid)
        unique_filter = {
            "key_name": key_name,
            "process_name": process,
        }
    elif model is BoardJinjiaCnc0:
        payload = build_cnc0_payload(grid)
        unique_filter = {
            "key_name": key_name,
            "process_name": process,
        }
    else:
        payload = build_cnc0_full_payload(grid)
        unique_filter = {
            "key_name": key_name,
            "process_name": process,
        }

    return ParsedDashboardRecord(
        model=model,
        unique_filter=unique_filter,
        payload={**common_payload, **payload},
    )


def build_duanya_payload(grid: list[list[str]]) -> dict[str, Any]:
    """锻压数据解析函数，统一处理所有字段类型和良率计算"""
    
    # 列索引：data_cols列对应数据
    data_cols = [3, 5, 7, 9]  # 对应 _1, _2, _3, _4
    
    # 提取各系列数据
    # 原材批次
    batch_vals = [gird_extract_value(grid, 1, col) for col in data_cols]
    # 線別/模號
    line_vals = [gird_extract_value(grid, 2, col) if gird_extract_value(grid, 2, col) !=  "線 模" else None for col in data_cols] #前面_table_to_grid得到gird时去掉了首位空白
    # 投入数，良品数，不良数
    input_vals = [int(gird_extract_value(grid, 3, col)) if gird_extract_value(grid, 3, col) is not None else None for col in data_cols]
    input_total = sum(val for val in input_vals if val is not None)
    good_vals = [int(gird_extract_value(grid, 4, col)) if gird_extract_value(grid, 4, col) is not None else None for col in data_cols]
    good_total = sum(val for val in good_vals if val is not None)
    bad_vals = [int(gird_extract_value(grid, 5, col)) if gird_extract_value(grid, 5, col) is not None else None for col in data_cols]
    bad_total =  sum(val for val in bad_vals if val is not None)
    # 实际良率
    actual_yield_vals = [None]*4
    for i in range(0,4):
        if good_vals[i] is not None and input_vals[i] is not None:
            actual_yield_vals[i] = round((good_vals[i] / input_vals[i])*100,2)
        else: actual_yield_vals[i] = None
    actual_yield_total = round((good_total / input_total)*100,2)

    #region 具体不良类型数目,9-17行
    # 不良类型1,5.0+1.0/-0.3偏小
    defect_type_1_num_val = [None]*4
    for i in range(0,4):
        col = data_cols[i]
        if input_vals[i] is not None and gird_extract_value(grid, 9, col) is not None:
            defect_type_1_num_val[i] = int(gird_extract_value(grid, 9, col))
        elif input_vals[i] is not None:
            defect_type_1_num_val[i] = 0
        else:
            defect_type_1_num_val[i] = None
    defect_type_1_num_total = sum(val for val in defect_type_1_num_val if val is not None)
    defect_type_1_rate_val = [None]*4
    for i in range(0,4):
        if input_vals[i] is not None and defect_type_1_num_val[i] is not None:
            defect_type_1_rate_val[i] = round((defect_type_1_num_val[i] / input_vals[i])*100,2)
        elif input_vals[i] is not None and defect_type_1_num_val[i] == 0:
            defect_type_1_rate_val[i] = 0
        elif input_vals[i] is None:
            defect_type_1_rate_val[i] = None
    defect_type_1_rate_total = round((defect_type_1_num_total / input_total)*100,2)

    # 不良类型2,50+12/-3偏小
    defect_type_2_num_val = [None]*4
    for i in range(0,4):
        col = data_cols[i]
        if input_vals[i] is not None and gird_extract_value(grid, 10, col) is not None:
            defect_type_2_num_val[i] = int(gird_extract_value(grid, 10, col))
        elif input_vals[i] is not None:
            defect_type_2_num_val[i] = 0
        else:
            defect_type_2_num_val[i] = None
    defect_type_2_num_total = sum(val for val in defect_type_2_num_val if val is not None)
    defect_type_2_rate_val = [None]*4
    for i in range(0,4):
        if input_vals[i] is not None and defect_type_2_num_val[i] is not None:
            defect_type_2_rate_val[i] = round((defect_type_2_num_val[i] / input_vals[i])*100,2)
        elif input_vals[i] is not None and defect_type_2_num_val[i] == 0:
            defect_type_2_rate_val[i] = 0
        elif input_vals[i] is None:
            defect_type_2_rate_val[i] = None
    defect_type_2_rate_total = round((defect_type_2_num_total / input_total)*100,2)

    # 不良类型3,50+12/-3偏大
    defect_type_3_num_val = [None]*4
    for i in range(0,4):
        col = data_cols[i]
        if input_vals[i] is not None and gird_extract_value(grid, 11, col) is not None:
            defect_type_3_num_val[i] = int(gird_extract_value(grid, 11, col))
        elif input_vals[i] is not None:
            defect_type_3_num_val[i] = 0
        else:
            defect_type_3_num_val[i] = None
    defect_type_3_num_total = sum(val for val in defect_type_3_num_val if val is not None)
    defect_type_3_rate_val = [None]*4
    for i in range(0,4):
        if input_vals[i] is not None and defect_type_3_num_val[i] is not None:
            defect_type_3_rate_val[i] = round((defect_type_3_num_val[i] / input_vals[i])*100,2)
        elif input_vals[i] is not None and defect_type_3_num_val[i] == 0:
            defect_type_3_rate_val[i] = 0
        elif input_vals[i] is None:
            defect_type_3_rate_val[i] = None
    defect_type_3_rate_total = round((defect_type_3_num_total / input_total)*100,2)

    # 不良类型4,垂直度0.40偏大
    defect_type_4_num_val = [None]*4
    for i in range(0,4):
        col = data_cols[i]
        if input_vals[i] is not None and gird_extract_value(grid, 12, col) is not None:
            defect_type_4_num_val[i] = int(gird_extract_value(grid, 12, col))
        elif input_vals[i] is not None:
            defect_type_4_num_val[i] = 0
        else:
            defect_type_4_num_val[i] = None
    defect_type_4_num_total = sum(val for val in defect_type_4_num_val if val is not None)
    defect_type_4_rate_val = [None]*4
    for i in range(0,4):
        if input_vals[i] is not None and defect_type_4_num_val[i] is not None:
            defect_type_4_rate_val[i] = round((defect_type_4_num_val[i] / input_vals[i])*100,2)
        elif input_vals[i] is not None and defect_type_4_num_val[i] == 0:
            defect_type_4_rate_val[i] = 0
        elif input_vals[i] is None:
            defect_type_4_rate_val[i] = None
    defect_type_4_rate_total = round((defect_type_4_num_total / input_total)*100,2)

    # 不良类型5,垂直度0.70偏大
    defect_type_5_num_val = [None]*4
    for i in range(0,4):
        col = data_cols[i]
        if input_vals[i] is not None and gird_extract_value(grid, 13, col) is not None:
            defect_type_5_num_val[i] = int(gird_extract_value(grid, 13, col))
        elif input_vals[i] is not None:
            defect_type_5_num_val[i] = 0
        else:
            defect_type_5_num_val[i] = None
    defect_type_5_num_total = sum(val for val in defect_type_5_num_val if val is not None)
    defect_type_5_rate_val = [None]*4
    for i in range(0,4):
        if input_vals[i] is not None and defect_type_5_num_val[i] is not None:
            defect_type_5_rate_val[i] = round((defect_type_5_num_val[i] / input_vals[i])*100,2)
        elif input_vals[i] is not None and defect_type_5_num_val[i] == 0:
            defect_type_5_rate_val[i] = 0
        elif input_vals[i] is None:
            defect_type_5_rate_val[i] = None
    defect_type_5_rate_total = round((defect_type_5_num_total / input_total)*100,2)

    # 不良类型6,4.20+/-0.30￨P1-P3￨＜0.2偏大
    defect_type_6_num_val = [None]*4
    for i in range(0,4):
        col = data_cols[i]
        if input_vals[i] is not None and gird_extract_value(grid, 14, col) is not None:
            defect_type_6_num_val[i] = int(gird_extract_value(grid, 14, col))
        elif input_vals[i] is not None:
            defect_type_6_num_val[i] = 0
        else:
            defect_type_6_num_val[i] = None
    defect_type_6_num_total = sum(val for val in defect_type_6_num_val if val is not None)
    defect_type_6_rate_val = [None]*4
    for i in range(0,4):
        if input_vals[i] is not None and defect_type_6_num_val[i] is not None:
            defect_type_6_rate_val[i] = round((defect_type_6_num_val[i] / input_vals[i])*100,2)
        elif input_vals[i] is not None and defect_type_6_num_val[i] == 0:
            defect_type_6_rate_val[i] = 0
        elif input_vals[i] is None:
            defect_type_6_rate_val[i] = None
    defect_type_6_rate_total = round((defect_type_6_num_total / input_total)*100,2)

    # 不良类型7,4.20+/-0.30￨P2-P4￨＜0.2偏大
    defect_type_7_num_val = [None]*4
    for i in range(0,4):
        col = data_cols[i]
        if input_vals[i] is not None and gird_extract_value(grid, 15, col) is not None:
            defect_type_7_num_val[i] = int(gird_extract_value(grid, 15, col))
        elif input_vals[i] is not None:
            defect_type_7_num_val[i] = 0
        else:
            defect_type_7_num_val[i] = None
    defect_type_7_num_total = sum(val for val in defect_type_7_num_val if val is not None)
    defect_type_7_rate_val = [None]*4
    for i in range(0,4):
        if input_vals[i] is not None and defect_type_7_num_val[i] is not None:
            defect_type_7_rate_val[i] = round((defect_type_7_num_val[i] / input_vals[i])*100,2)
        elif input_vals[i] is not None and defect_type_7_num_val[i] == 0:
            defect_type_7_rate_val[i] = 0
        elif input_vals[i] is None:
            defect_type_7_rate_val[i] = None
    defect_type_7_rate_total = round((defect_type_7_num_total / input_total)*100,2)

    # 不良类型8,2D碼偏位
    defect_type_8_num_val = [None]*4
    for i in range(0,4):
        col = data_cols[i]
        if input_vals[i] is not None and gird_extract_value(grid, 16, col) is not None:
            defect_type_8_num_val[i] = int(gird_extract_value(grid, 16, col))
        elif input_vals[i] is not None:
            defect_type_8_num_val[i] = 0
        else:
            defect_type_8_num_val[i] = None
    defect_type_8_num_total = sum(val for val in defect_type_8_num_val if val is not None)
    defect_type_8_rate_val = [None]*4
    for i in range(0,4):
        if input_vals[i] is not None and defect_type_8_num_val[i] is not None:
            defect_type_8_rate_val[i] = round((defect_type_8_num_val[i] / input_vals[i])*100,2)
        elif input_vals[i] is not None and defect_type_8_num_val[i] == 0:
            defect_type_8_rate_val[i] = 0
        elif input_vals[i] is None:
            defect_type_8_rate_val[i] = None
    defect_type_8_rate_total = round((defect_type_8_num_total / input_total)*100,2)

    # 不良类型9,DDS
    defect_type_9_num_val = [None]*4
    for i in range(0,4):
        col = data_cols[i]
        if input_vals[i] is not None and gird_extract_value(grid, 17, col) is not None:
            defect_type_9_num_val[i] = int(gird_extract_value(grid, 17, col))
        elif input_vals[i] is not None:
            defect_type_9_num_val[i] = 0
        else:
            defect_type_9_num_val[i] = None
    defect_type_9_num_total = sum(val for val in defect_type_9_num_val if val is not None)
    defect_type_9_rate_val = [None]*4
    for i in range(0,4):
        if input_vals[i] is not None and defect_type_9_num_val[i] is not None:
            defect_type_9_rate_val[i] = round((defect_type_9_num_val[i] / input_vals[i])*100,2)
        elif input_vals[i] is not None and defect_type_9_num_val[i] == 0:
            defect_type_9_rate_val[i] = 0
        elif input_vals[i] is None:
            defect_type_9_rate_val[i] = None
    defect_type_9_rate_total = round((defect_type_9_num_total / input_total)*100,2)
    #endregion

    # 构建基础字段
    payload = {
        # 批次和线别
        "batch_1": batch_vals[0], "batch_2": batch_vals[1], "batch_3": batch_vals[2], "batch_4": batch_vals[3],
        "line_1": line_vals[0], "line_2": line_vals[1], "line_3": line_vals[2], "line_4": line_vals[3],
        
        # 投入数（字符串）
        "input_1": input_vals[0], "input_2": input_vals[1], "input_3": input_vals[2], "input_4": input_vals[3],
        "input_total": input_total,
        
        # 良品数和不良数（整数）
        "good_1": good_vals[0], "good_2": good_vals[1], "good_3": good_vals[2], "good_4": good_vals[3],
        "good_total": good_total,
        "bad_1": bad_vals[0], "bad_2": bad_vals[1], "bad_3": bad_vals[2], "bad_4": bad_vals[3],
        "bad_total": bad_total,
        
        # 实际良率（浮点数）
        "actual_yield_1": actual_yield_vals[0], "actual_yield_2": actual_yield_vals[1],
        "actual_yield_3": actual_yield_vals[2], "actual_yield_4": actual_yield_vals[3],
        "actual_yield_total": actual_yield_total,
        
        # 目标良率（固定值）
        "target_yield_1": 99.80, "target_yield_2": 99.80, "target_yield_3": 99.80, "target_yield_4": 99.80,
        "target_yield_total": 99.80,

        # 5.0+1.0/-0.3 偏小，数量
        "_5_0_1_0_0_3_pian_xiao_badnum_1": defect_type_1_num_val[0], "_5_0_1_0_0_3_pian_xiao_badnum_2": defect_type_1_num_val[1],
        "_5_0_1_0_0_3_pian_xiao_badnum_3": defect_type_1_num_val[2], "_5_0_1_0_0_3_pian_xiao_badnum_4": defect_type_1_num_val[3],
        "_5_0_1_0_0_3_pian_xiao_badnum_total": defect_type_1_num_total,

        # 5.0+1.0/-0.3 偏小，不良率
        "_5_0_1_0_0_3_pian_xiao_badrate_1": defect_type_1_rate_val[0], "_5_0_1_0_0_3_pian_xiao_badrate_2": defect_type_1_rate_val[1],
        "_5_0_1_0_0_3_pian_xiao_badrate_3": defect_type_1_rate_val[2], "_5_0_1_0_0_3_pian_xiao_badrate_4": defect_type_1_rate_val[3],
        "_5_0_1_0_0_3_pian_xiao_badrate_total": defect_type_1_rate_total,

        # 50+12/-3 偏小，数量
        "_50_12_3_pian_xiao_badnum_1": defect_type_2_num_val[0], "_50_12_3_pian_xiao_badnum_2": defect_type_2_num_val[1],
        "_50_12_3_pian_xiao_badnum_3": defect_type_2_num_val[2], "_50_12_3_pian_xiao_badnum_4": defect_type_2_num_val[3],
        "_50_12_3_pian_xiao_badnum_total": defect_type_2_num_total,

        # 50+12/-3 偏小，不良率
        "_50_12_3_pian_xiao_badrate_1": defect_type_2_rate_val[0], "_50_12_3_pian_xiao_badrate_2": defect_type_2_rate_val[1],
        "_50_12_3_pian_xiao_badrate_3": defect_type_2_rate_val[2], "_50_12_3_pian_xiao_badrate_4": defect_type_2_rate_val[3],
        "_50_12_3_pian_xiao_badrate_total": defect_type_2_rate_total,

        # 50+12/-3 偏大，数量
        "_50_12_3_pian_da_badnum_1": defect_type_3_num_val[0], "_50_12_3_pian_da_badnum_2": defect_type_3_num_val[1],
        "_50_12_3_pian_da_badnum_3": defect_type_3_num_val[2], "_50_12_3_pian_da_badnum_4": defect_type_3_num_val[3],
        "_50_12_3_pian_da_badnum_total": defect_type_3_num_total,

        # 50+12/-3 偏大，不良率
        "_50_12_3_pian_da_badrate_1": defect_type_3_rate_val[0], "_50_12_3_pian_da_badrate_2": defect_type_3_rate_val[1],
        "_50_12_3_pian_da_badrate_3": defect_type_3_rate_val[2], "_50_12_3_pian_da_badrate_4": defect_type_3_rate_val[3],
        "_50_12_3_pian_da_badrate_total": defect_type_3_rate_total,

        # 垂直度 0.40 偏大，数量
        "chui_zhi_du_0_40_pian_da_badnum_1": defect_type_4_num_val[0], "chui_zhi_du_0_40_pian_da_badnum_2": defect_type_4_num_val[1],
        "chui_zhi_du_0_40_pian_da_badnum_3": defect_type_4_num_val[2], "chui_zhi_du_0_40_pian_da_badnum_4": defect_type_4_num_val[3],
        "chui_zhi_du_0_40_pian_da_badnum_total": defect_type_4_num_total,

        # 垂直度 0.40 偏大，不良率
        "chui_zhi_du_0_40_pian_da_badrate_1": defect_type_4_rate_val[0], "chui_zhi_du_0_40_pian_da_badrate_2": defect_type_4_rate_val[1],
        "chui_zhi_du_0_40_pian_da_badrate_3": defect_type_4_rate_val[2], "chui_zhi_du_0_40_pian_da_badrate_4": defect_type_4_rate_val[3],
        "chui_zhi_du_0_40_pian_da_badrate_total": defect_type_4_rate_total,

        # 垂直度 0.70 偏大，数量
        "chui_zhi_du_0_70_pian_da_badnum_1": defect_type_5_num_val[0], "chui_zhi_du_0_70_pian_da_badnum_2": defect_type_5_num_val[1],
        "chui_zhi_du_0_70_pian_da_badnum_3": defect_type_5_num_val[2], "chui_zhi_du_0_70_pian_da_badnum_4": defect_type_5_num_val[3],
        "chui_zhi_du_0_70_pian_da_badnum_total": defect_type_5_num_total,

        # 垂直度 0.70 偏大，不良率
        "chui_zhi_du_0_70_pian_da_badrate_1": defect_type_5_rate_val[0], "chui_zhi_du_0_70_pian_da_badrate_2": defect_type_5_rate_val[1],
        "chui_zhi_du_0_70_pian_da_badrate_3": defect_type_5_rate_val[2], "chui_zhi_du_0_70_pian_da_badrate_4": defect_type_5_rate_val[3],
        "chui_zhi_du_0_70_pian_da_badrate_total": defect_type_5_rate_total,

        # 4.20+/-0.30∣P1-P3∣＜0.2 偏大，数量
        "_4_20_0_30_P1_P3_0_2_pian_da_badnum_1": defect_type_6_num_val[0], "_4_20_0_30_P1_P3_0_2_pian_da_badnum_2": defect_type_6_num_val[1],
        "_4_20_0_30_P1_P3_0_2_pian_da_badnum_3": defect_type_6_num_val[2], "_4_20_0_30_P1_P3_0_2_pian_da_badnum_4": defect_type_6_num_val[3],
        "_4_20_0_30_P1_P3_0_2_pian_da_badnum_total": defect_type_6_num_total,

        # 4.20+/-0.30∣P1-P3∣＜0.2 偏大，不良率
        "_4_20_0_30_P1_P3_0_2_pian_da_badrate_1": defect_type_6_rate_val[0], "_4_20_0_30_P1_P3_0_2_pian_da_badrate_2": defect_type_6_rate_val[1],
        "_4_20_0_30_P1_P3_0_2_pian_da_badrate_3": defect_type_6_rate_val[2], "_4_20_0_30_P1_P3_0_2_pian_da_badrate_4": defect_type_6_rate_val[3],
        "_4_20_0_30_P1_P3_0_2_pian_da_badrate_total": defect_type_6_rate_total,

        # 4.20+/-0.30∣P2-P4∣＜0.2 偏大，数量
        "_4_20_0_30_P2_P4_0_2_pian_da_badnum_1": defect_type_7_num_val[0], "_4_20_0_30_P2_P4_0_2_pian_da_badnum_2": defect_type_7_num_val[1],
        "_4_20_0_30_P2_P4_0_2_pian_da_badnum_3": defect_type_7_num_val[2], "_4_20_0_30_P2_P4_0_2_pian_da_badnum_4": defect_type_7_num_val[3],
        "_4_20_0_30_P2_P4_0_2_pian_da_badnum_total": defect_type_7_num_total,

        # 4.20+/-0.30∣P2-P4∣＜0.2 偏大，不良率
        "_4_20_0_30_P2_P4_0_2_pian_da_badrate_1": defect_type_7_rate_val[0], "_4_20_0_30_P2_P4_0_2_pian_da_badrate_2": defect_type_7_rate_val[1],
        "_4_20_0_30_P2_P4_0_2_pian_da_badrate_3": defect_type_7_rate_val[2], "_4_20_0_30_P2_P4_0_2_pian_da_badrate_4": defect_type_7_rate_val[3],
        "_4_20_0_30_P2_P4_0_2_pian_da_badrate_total": defect_type_7_rate_total,

        # 2D 碼偏位，数量
        "_2D_ma_pian_wei_badnum_1": defect_type_8_num_val[0], "_2D_ma_pian_wei_badnum_2": defect_type_8_num_val[1],
        "_2D_ma_pian_wei_badnum_3": defect_type_8_num_val[2], "_2D_ma_pian_wei_badnum_4": defect_type_8_num_val[3],
        "_2D_ma_pian_wei_badnum_total": defect_type_8_num_total,

        # 2D 碼偏位，不良率
        "_2D_ma_pian_wei_badrate_1": defect_type_8_rate_val[0], "_2D_ma_pian_wei_badrate_2": defect_type_8_rate_val[1],
        "_2D_ma_pian_wei_badrate_3": defect_type_8_rate_val[2], "_2D_ma_pian_wei_badrate_4": defect_type_8_rate_val[3],
        "_2D_ma_pian_wei_badrate_total": defect_type_8_rate_total,

        # DDS,数量
        "DDS_badnum_1": defect_type_9_num_val[0], "DDS_badnum_2": defect_type_9_num_val[1],
        "DDS_badnum_3": defect_type_9_num_val[2], "DDS_badnum_4": defect_type_9_num_val[3],
        "DDS_badnum_total": defect_type_9_num_total,

        # DDS,不良率
        "DDS_badrate_1": defect_type_9_rate_val[0], "DDS_badrate_2": defect_type_9_rate_val[1],
        "DDS_badrate_3": defect_type_9_rate_val[2], "DDS_badrate_4": defect_type_9_rate_val[3],
        "DDS_badrate_total": defect_type_9_rate_total,

    }
    
    return payload


def build_gurong_payload(grid: list[list[str]]) -> dict[str, Any]:
    """固熔数据解析函数，统一处理所有字段类型和良率计算"""
    # 列索引：data_cols列对应数据
    data_cols = [3, 5, 7]  # 对应 _1, _2, _3
    # 提取各系列数据
    # 線別
    line_vals = []
    for col in data_cols:
        val = gird_extract_value(grid, 1, col)
        line_vals.append(val if val is not None and val.strip() != "線" else None)
    # 投入数，良品数，不良数
    input_vals = [int(gird_extract_value(grid, 2, col)) if gird_extract_value(grid, 2, col) is not None else None for col in data_cols]
    input_total = sum(val for val in input_vals if val is not None)
    good_vals = [int(gird_extract_value(grid, 3, col)) if gird_extract_value(grid, 3, col) is not None else None for col in data_cols]
    good_total = sum(val for val in good_vals if val is not None)
    bad_vals = [int(gird_extract_value(grid, 4, col)) if gird_extract_value(grid, 4, col) is not None else None for col in data_cols]
    bad_total =  sum(val for val in bad_vals if val is not None)
    # 实际良率
    actual_yield_vals = [None]*3
    for i in range(0,3):
        if good_vals[i] is not None and input_vals[i] is not None:
            actual_yield_vals[i] = round((good_vals[i] / input_vals[i])*100,2)
        else: actual_yield_vals[i] = None
    actual_yield_total = round((good_total / input_total)*100,2)

    #region 具体不良类型数目,8-10行
    # 不良类型1,硬度40≤Hba≤60偏大
    defect_type_1_num_val = [None]*3
    for i in range(0,3):
        col = data_cols[i]
        if input_vals[i] is not None and gird_extract_value(grid, 8, col) is not None:
            defect_type_1_num_val[i] = int(gird_extract_value(grid, 8, col))
        elif input_vals[i] is not None:
            defect_type_1_num_val[i] = 0
        else:
            defect_type_1_num_val[i] = None
    defect_type_1_num_total = sum(val for val in defect_type_1_num_val if val is not None)
    defect_type_1_rate_val = [None]*3
    for i in range(0,3):
        if input_vals[i] is not None and defect_type_1_num_val[i] is not None:
            defect_type_1_rate_val[i] = round((defect_type_1_num_val[i] / input_vals[i])*100,2)
        elif input_vals[i] is not None and defect_type_1_num_val[i] == 0:
            defect_type_1_rate_val[i] = 0
        elif input_vals[i] is None:
            defect_type_1_rate_val[i] = None
    defect_type_1_rate_total = round((defect_type_1_num_total / input_total)*100,2)

    # 不良类型2,變形
    defect_type_2_num_val = [None]*3
    for i in range(0,3):
        col = data_cols[i]
        if input_vals[i] is not None and gird_extract_value(grid, 9, col) is not None:
            defect_type_2_num_val[i] = int(gird_extract_value(grid, 9, col))
        elif input_vals[i] is not None:
            defect_type_2_num_val[i] = 0
        else:
            defect_type_2_num_val[i] = None
    defect_type_2_num_total = sum(val for val in defect_type_2_num_val if val is not None)
    defect_type_2_rate_val = [None]*3
    for i in range(0,3):
        if input_vals[i] is not None and defect_type_2_num_val[i] is not None:
            defect_type_2_rate_val[i] = round((defect_type_2_num_val[i] / input_vals[i])*100,2)
        elif input_vals[i] is not None and defect_type_2_num_val[i] == 0:
            defect_type_2_rate_val[i] = 0
        elif input_vals[i] is None:
            defect_type_2_rate_val[i] = None
    defect_type_2_rate_total = round((defect_type_2_num_total / input_total)*100,2)

    # 不良类型3,DDS
    defect_type_3_num_val = [None]*3
    for i in range(0,3):
        col = data_cols[i]
        if input_vals[i] is not None and gird_extract_value(grid, 10, col) is not None:
            defect_type_3_num_val[i] = int(gird_extract_value(grid, 10, col))
        elif input_vals[i] is not None:
            defect_type_3_num_val[i] = 0
        else:
            defect_type_3_num_val[i] = None
    defect_type_3_num_total = sum(val for val in defect_type_3_num_val if val is not None)
    defect_type_3_rate_val = [None]*3
    for i in range(0,3):
        if input_vals[i] is not None and defect_type_3_num_val[i] is not None:
            defect_type_3_rate_val[i] = round((defect_type_3_num_val[i] / input_vals[i])*100,2)
        elif input_vals[i] is not None and defect_type_3_num_val[i] == 0:
            defect_type_3_rate_val[i] = 0
        elif input_vals[i] is None:
            defect_type_3_rate_val[i] = None
    defect_type_3_rate_total = round((defect_type_3_num_total / input_total)*100,2)
    #endregion

    payload = {
    # 线别
    "line_1": line_vals[0], "line_2": line_vals[1], "line_3": line_vals[2],
    
    # 投入数
    "input_1": input_vals[0], "input_2": input_vals[1], "input_3": input_vals[2],
    "input_total": input_total,
    
    # 良品数和不良数
    "good_1": good_vals[0], "good_2": good_vals[1], "good_3": good_vals[2],
    "good_total": good_total,
    "bad_1": bad_vals[0], "bad_2": bad_vals[1], "bad_3": bad_vals[2],
    "bad_total": bad_total,
    
    # 实际良率
    "actual_yield_1": actual_yield_vals[0], "actual_yield_2": actual_yield_vals[1], "actual_yield_3": actual_yield_vals[2],
    "actual_yield_total": actual_yield_total,
    
    # 目标良率（固定值）
    "target_yield_1": 100.00, "target_yield_2": 100.00, "target_yield_3": 100.00,
    "target_yield_total": 100.00,
    
    # 硬度 40≤Hba≤60 偏大，数量
    "ying_du_40_Hba_60_pian_da_badnum_1": defect_type_1_num_val[0], "ying_du_40_Hba_60_pian_da_badnum_2": defect_type_1_num_val[1], "ying_du_40_Hba_60_pian_da_badnum_3": defect_type_1_num_val[2],
    "ying_du_40_Hba_60_pian_da_badnum_total": defect_type_1_num_total,
    
    # 硬度 40≤Hba≤60 偏大，不良率
    "ying_du_40_Hba_60_pian_da_badrate_1": defect_type_1_rate_val[0], "ying_du_40_Hba_60_pian_da_badrate_2": defect_type_1_rate_val[1], "ying_du_40_Hba_60_pian_da_badrate_3": defect_type_1_rate_val[2],
    "ying_du_40_Hba_60_pian_da_badrate_total": defect_type_1_rate_total,
    
    # 變形，数量
    "bian_xing_badnum_1": defect_type_2_num_val[0], "bian_xing_badnum_2": defect_type_2_num_val[1], "bian_xing_badnum_3": defect_type_2_num_val[2],
    "bian_xing_badnum_total": defect_type_2_num_total,
    
    # 變形，不良率
    "bian_xing_badrate_1": defect_type_2_rate_val[0], "bian_xing_badrate_2": defect_type_2_rate_val[1], "bian_xing_badrate_3": defect_type_2_rate_val[2],
    "bian_xing_badrate_total": defect_type_2_rate_total,
    
    # DDS,数量
    "DDS_badnum_1": defect_type_3_num_val[0], "DDS_badnum_2": defect_type_3_num_val[1], "DDS_badnum_3": defect_type_3_num_val[2],
    "DDS_badnum_total": defect_type_3_num_total,
    
    # DDS,不良率
    "DDS_badrate_1": defect_type_3_rate_val[0], "DDS_badrate_2": defect_type_3_rate_val[1], "DDS_badrate_3": defect_type_3_rate_val[2],
    "DDS_badrate_total": defect_type_3_rate_total,
    }

    return payload


def build_shixiao_payload(grid: list[list[str]]) -> dict[str, Any]:
    """时效数据解析函数，统一处理所有字段类型和良率计算"""
    # 投入数，良品数，不良数
    input = int(gird_extract_value(grid, 1, 3)) 
    good = int(gird_extract_value(grid, 2, 3)) 
    bad = int(gird_extract_value(grid, 3, 3)) if gird_extract_value(grid, 3, 3) is not None else 0 # 应该只有这个会不填吧
    actual_yield = round((good / input)*100,2)
     # 不良项目 1，變形
    defect_type_1_num = int(gird_extract_value(grid, 7, 3)) if (gird_extract_value(grid, 7, 3)) is not None else 0
    defect_type_1_rate = round((defect_type_1_num / input) * 100, 2) 
    
    # 不良项目 2，機械性能送檢
    defect_type_2_num = int(gird_extract_value(grid, 8, 3)) if (gird_extract_value(grid, 8, 3)) is not None else 0
    defect_type_2_rate = round((defect_type_2_num / input) * 100, 2) 
    
    # 不良项目 3，硬度 Hba≥74 偏小
    defect_type_3_num = int(gird_extract_value(grid, 9, 3)) if (gird_extract_value(grid, 9, 3)) is not None else 0
    defect_type_3_rate = round((defect_type_3_num / input) * 100, 2) 
    
    # 不良项目 4,DDS
    defect_type_4_num = int(gird_extract_value(grid, 10, 3)) if (gird_extract_value(grid, 10, 3)) is not None else 0
    defect_type_4_rate = round((defect_type_4_num / input) * 100, 2) 
    payload =  {
        # 基础数据
        "input": input,
        "good": good,
        "bad": bad,
        "actual_yield": actual_yield,
        "target_yield": 100.00,  # 时效的目标良率通常是 100%

        # 不良类型数据
        "bian_xing_badnum_total": defect_type_1_num,
        "bian_xing_badrate_total": defect_type_1_rate,
        
        "ji_xie_xing_neng_song_jian_badnum_total": defect_type_2_num,
        "ji_xie_xing_neng_song_jian_badrate_total": defect_type_2_rate,
        
        "ying_du_Hba_74_pian_xiao_badnum_total": defect_type_3_num,
        "ying_du_Hba_74_pian_xiao_badrate_total": defect_type_3_rate,
        
        "DDS_badnum_total": defect_type_4_num,
        "DDS_badrate_total": defect_type_4_rate,
    }
    return payload

def build_cnc0_payload(grid: list[list[str]]) -> dict[str, Any]:
    """cnc0 数据解析函数，统一处理所有字段类型和良率计算"""
    # 投入數，抽檢數，一次良品數，不良數，可重工不良數，不可重工不良數，一次良率，二次良率，一次良率目標，二次良率目標
    input = int(gird_extract_value(grid, 1, 3)) 
    sample = int(gird_extract_value(grid, 2, 3)) 
    first_good = int(gird_extract_value(grid, 3, 3)) 
    bad_count = int(gird_extract_value(grid, 4, 3)) 
    reworkable_bad = int(gird_extract_value(grid, 5, 3)) 
    unreworkable_bad = int(gird_extract_value(grid, 6, 3)) 
    first_yield = round((first_good / input)*100,2)
    second_yield = round(((input-unreworkable_bad) / input)*100,2)
    first_target_yield = 99.70
    second_target_yield = 100.00

    #不良类型 1，DDS
    defect_type_1_reworkable_num = int(gird_extract_value(grid, 12, 3)) if (gird_extract_value(grid, 12, 3)) is not None else 0
    defect_type_1_unreworkable_num = int(gird_extract_value(grid, 12, 4)) if (gird_extract_value(grid, 12, 4)) is not None else 0
    defect_type_1_rate = round(((defect_type_1_reworkable_num + defect_type_1_unreworkable_num) / input) * 100, 2) 
    # 不良类型 2，臺階/過切
    defect_type_2_reworkable_num = int(gird_extract_value(grid, 13, 3)) if (gird_extract_value(grid, 13, 3)) is not None else 0
    defect_type_2_unreworkable_num = int(gird_extract_value(grid, 13, 4)) if (gird_extract_value(grid, 13, 4)) is not None else 0
    defect_type_2_rate = round(((defect_type_2_reworkable_num + defect_type_2_unreworkable_num) / input) * 100, 2) 
    
    # 不良类型 3，毛邊/毛刺
    defect_type_3_reworkable_num = int(gird_extract_value(grid, 14, 3)) if (gird_extract_value(grid, 14, 3)) is not None else 0
    defect_type_3_unreworkable_num = int(gird_extract_value(grid, 14, 4)) if (gird_extract_value(grid, 14, 4)) is not None else 0
    defect_type_3_rate = round(((defect_type_3_reworkable_num + defect_type_3_unreworkable_num) / input) * 100, 2) 
    
    # 不良类型 4，大平面未見光
    defect_type_4_reworkable_num = int(gird_extract_value(grid, 15, 3)) if (gird_extract_value(grid, 15, 3)) is not None else 0
    defect_type_4_unreworkable_num = int(gird_extract_value(grid, 15, 4)) if (gird_extract_value(grid, 15, 4)) is not None else 0
    defect_type_4_rate = round(((defect_type_4_reworkable_num + defect_type_4_unreworkable_num) / input) * 100, 2) 
    
    # 不良类型 5，大平面刀紋/刀痕
    defect_type_5_reworkable_num = int(gird_extract_value(grid, 16, 3)) if (gird_extract_value(grid, 16, 3)) is not None else 0
    defect_type_5_unreworkable_num = int(gird_extract_value(grid, 16, 4)) if (gird_extract_value(grid, 16, 4)) is not None else 0
    defect_type_5_rate = round(((defect_type_5_reworkable_num + defect_type_5_unreworkable_num) / input) * 100, 2) 
    
    # 不良类型 6，平面度 0.10 偏大
    defect_type_6_reworkable_num = int(gird_extract_value(grid, 17, 3)) if (gird_extract_value(grid, 17, 3)) is not None else 0
    defect_type_6_unreworkable_num = int(gird_extract_value(grid, 17, 4)) if (gird_extract_value(grid, 17, 4)) is not None else 0
    defect_type_6_rate = round(((defect_type_6_reworkable_num + defect_type_6_unreworkable_num) / input) * 100, 2) 
    
    # 不良类型 7，4.70+/-0.10 偏大
    defect_type_7_reworkable_num = int(gird_extract_value(grid, 18, 3)) if (gird_extract_value(grid, 18, 3)) is not None else 0
    defect_type_7_unreworkable_num = int(gird_extract_value(grid, 18, 4)) if (gird_extract_value(grid, 18, 4)) is not None else 0
    defect_type_7_rate = round(((defect_type_7_reworkable_num + defect_type_7_unreworkable_num) / input) * 100, 2) 
    
    # 不良类型 8，4.70+/-0.10 偏小
    defect_type_8_reworkable_num = int(gird_extract_value(grid, 19, 3)) if (gird_extract_value(grid, 19, 3)) is not None else 0
    defect_type_8_unreworkable_num = int(gird_extract_value(grid, 19, 4)) if (gird_extract_value(grid, 19, 4)) is not None else 0
    defect_type_8_rate = round(((defect_type_8_reworkable_num + defect_type_8_unreworkable_num) / input) * 100, 2) 

    payload = {
        # 基础数据
        "input": input,
        "sample": sample,
        "first_good": first_good,
        "bad_count": bad_count,
        "reworkable_bad": reworkable_bad,
        "unreworkable_bad": unreworkable_bad,
        "first_yield": first_yield,
        "second_yield": second_yield,
        "first_target_yield": first_target_yield,
        "second_target_yield": second_target_yield,

        # 不良类型数据 - DDS
        "DDS_badnum_reworkable": defect_type_1_reworkable_num,
        "DDS_badnum_unreworkable": defect_type_1_unreworkable_num,
        "DDS_badrate_total": defect_type_1_rate,

        # 不良类型数据 - 臺階/過切
        "tai_jie_guo_qie_badnum_reworkable": defect_type_2_reworkable_num,
        "tai_jie_guo_qie_badnum_unreworkable": defect_type_2_unreworkable_num,
        "tai_jie_guo_qie_badrate_total": defect_type_2_rate,

        # 不良类型数据 - 毛邊/毛刺
        "mao_bian_mao_ci_badnum_reworkable": defect_type_3_reworkable_num,
        "mao_bian_mao_ci_badnum_unreworkable": defect_type_3_unreworkable_num,
        "mao_bian_mao_ci_badrate_total": defect_type_3_rate,

        # 不良类型数据 - 大平面未見光
        "da_ping_mian_wei_jian_guang_badnum_reworkable": defect_type_4_reworkable_num,
        "da_ping_mian_wei_jian_guang_badnum_unreworkable": defect_type_4_unreworkable_num,
        "da_ping_mian_wei_jian_guang_badrate_total": defect_type_4_rate,

        # 不良类型数据 - 大平面刀紋/刀痕
        "da_ping_mian_dao_wen_dao_hen_badnum_reworkable": defect_type_5_reworkable_num,
        "da_ping_mian_dao_wen_dao_hen_badnum_unreworkable": defect_type_5_unreworkable_num,
        "da_ping_mian_dao_wen_dao_hen_badrate_total": defect_type_5_rate,

        # 不良类型数据 - 平面度 0.10 偏大
        "ping_mian_du_0_10_pian_da_badnum_reworkable": defect_type_6_reworkable_num,
        "ping_mian_du_0_10_pian_da_badnum_unreworkable": defect_type_6_unreworkable_num,
        "ping_mian_du_0_10_pian_da_badrate_total": defect_type_6_rate,

        # 不良类型数据 - 4.70+/-0.10 偏大
        "_4_70_0_10_pian_da_badnum_reworkable": defect_type_7_reworkable_num,
        "_4_70_0_10_pian_da_badnum_unreworkable": defect_type_7_unreworkable_num,
        "_4_70_0_10_pian_da_badrate_total": defect_type_7_rate,

        # 不良类型数据 - 4.70+/-0.10 偏小
        "_4_70_0_10_pian_xiao_badnum_reworkable": defect_type_8_reworkable_num,
        "_4_70_0_10_pian_xiao_badnum_unreworkable": defect_type_8_unreworkable_num,
        "_4_70_0_10_pian_xiao_badrate_total": defect_type_8_rate,
    }

    return payload


def build_cnc0_full_payload(grid: list[list[str]]) -> dict[str, Any]:
    """cnc0 全检 数据解析函数，统一处理所有字段类型和良率计算"""
    # 投入數，一次良品數，不良數，可重工不良數，不可重工不良數，一次良率，二次良率，一次良率目標,二次良率目標
    input = int(gird_extract_value(grid, 1, 3)) 
    first_good = int(gird_extract_value(grid, 2, 3)) 
    bad_count = int(gird_extract_value(grid, 3, 3)) 
    reworkable_bad = int(gird_extract_value(grid, 4, 3)) 
    unreworkable_bad = int(gird_extract_value(grid, 5, 3)) 
    first_yield = round((first_good / input)*100,2)
    second_yield = round(((input-unreworkable_bad) / input)*100,2)
    first_target_yield = 99.90
    second_target_yield = 100.00
    
    #不良类型 1，大平面刀紋/刀痕
    defect_type_1_num = int(gird_extract_value(grid, 11, 3)) if (gird_extract_value(grid, 11, 3)) is not None else 0
    defect_type_1_rate = round((defect_type_1_num / input) * 100, 2) 
    
    #不良类型 2，毛邊
    defect_type_2_num = int(gird_extract_value(grid, 12, 3)) if (gird_extract_value(grid, 12, 3)) is not None else 0
    defect_type_2_rate = round((defect_type_2_num / input) * 100, 2) 
    
    #不良类型 3，大平面未見光
    defect_type_3_num = int(gird_extract_value(grid, 13, 3)) if (gird_extract_value(grid, 13, 3)) is not None else 0
    defect_type_3_rate = round((defect_type_3_num / input) * 100, 2) 

    payload = {
        # 基础数据
        "input": input,
        "first_good": first_good,
        "bad": bad_count,
        "reworkable_bad": reworkable_bad,
        "unreworkable_bad": unreworkable_bad,
        "first_yield": first_yield,
        "second_yield": second_yield,
        "first_target_yield": first_target_yield,
        "second_target_yield": second_target_yield,

        # 不良类型数据 - 大平面刀紋/刀痕
        "da_ping_mian_dao_wen_dao_hen_badnum_total": defect_type_1_num,
        "da_ping_mian_dao_wen_dao_hen_badrate_total": defect_type_1_rate,

        # 不良类型数据 - 毛邊/毛刺（与 board_jinjia_cnc0_full 列名一致）
        "mao_bian_mao_ci_badnum_total": defect_type_2_num,
        "mao_bian_mao_ci_badrate_total": defect_type_2_rate,

        # 不良类型数据 - 大平面未見光
        "da_ping_mian_wei_jian_guang_badnum_total": defect_type_3_num,
        "da_ping_mian_wei_jian_guang_badrate_total": defect_type_3_rate,
    }

    return payload


DUANYA_DEFECT_TYPES: list[tuple[str, str]] = [
    ("_5_0_1_0_0_3_pian_xiao", "5.0+1.0/-0.3偏小"),
    ("_50_12_3_pian_xiao", "50+12/-3偏小"),
    ("_50_12_3_pian_da", "50+12/-3偏大"),
    ("chui_zhi_du_0_40_pian_da", "垂直度0.40偏大"),
    ("chui_zhi_du_0_70_pian_da", "垂直度0.70偏大"),
    ("_4_20_0_30_P1_P3_0_2_pian_da", "4.20±0.30|P1-P3|偏大"),
    ("_4_20_0_30_P2_P4_0_2_pian_da", "4.20±0.30|P2-P4|偏大"),
    ("_2D_ma_pian_wei", "2D碼偏位"),
    ("DDS", "DDS"),
]

GURONG_DEFECT_TYPES: list[tuple[str, str]] = [
    ("ying_du_40_Hba_60_pian_da", "硬度40≤Hba≤60偏大"),
    ("bian_xing", "變形"),
    ("DDS", "DDS"),
]

SHIXIAO_DEFECT_TYPES: list[tuple[str, str]] = [
    ("bian_xing", "變形"),
    ("ji_xie_xing_neng_song_jian", "機械性能送檢"),
    ("ying_du_Hba_74_pian_xiao", "硬度Hba≥74偏小"),
    ("DDS", "DDS"),
]

CNC0_DEFECT_TYPES: list[tuple[str, str]] = [
    ("DDS", "DDS"),
    ("tai_jie_guo_qie", "臺階/過切"),
    ("mao_bian_mao_ci", "毛邊/毛刺"),
    ("da_ping_mian_wei_jian_guang", "大平面未見光"),
    ("da_ping_mian_dao_wen_dao_hen", "大平面刀紋/刀痕"),
    ("ping_mian_du_0_10_pian_da", "平面度0.10偏大"),
    ("_4_70_0_10_pian_da", "4.70±0.10偏大"),
    ("_4_70_0_10_pian_xiao", "4.70±0.10偏小"),
]

CNC0_FULL_DEFECT_TYPES: list[tuple[str, str]] = [
    ("da_ping_mian_dao_wen_dao_hen", "大平面刀紋/刀痕"),
    ("mao_bian_mao_ci", "毛邊/毛刺"),
    ("da_ping_mian_wei_jian_guang", "大平面未見光"),
]

PROCESS_DEFECT_MAP: dict[str, list[tuple[str, str]]] = {
    "鍛壓": DUANYA_DEFECT_TYPES,
    "固熔": GURONG_DEFECT_TYPES,
    "時效": SHIXIAO_DEFECT_TYPES,
    "CNC0": CNC0_DEFECT_TYPES,
    "CNC0 全檢": CNC0_FULL_DEFECT_TYPES,
}


def _matching_col_indices(
    record, process: str,
    batch_filter: str = "", line_filter: str = "",
) -> list[int]:
    """返回记录中匹配筛选条件的列位置(1-based)，空筛选=全部列。"""
    if process == "鍛壓":
        all_cols = [1, 2, 3, 4]
        batches = [record.batch_1, record.batch_2, record.batch_3, record.batch_4]
        lines = [record.line_1, record.line_2, record.line_3, record.line_4]
    elif process == "固熔":
        all_cols = [1, 2, 3]
        batches = [None, None, None]
        lines = [record.line_1, record.line_2, record.line_3]
    else:
        return []

    result = set(all_cols)
    if batch_filter:
        result &= {i for i, b in zip(all_cols, batches) if b == batch_filter}
    if line_filter:
        result &= {i for i, ln in zip(all_cols, lines) if ln == line_filter}
    return sorted(result)


def _build_overview(
    records: list[Any], process_name: str,
    batch_filter: str = "", line_filter: str = "",
) -> list[dict[str, Any]]:
    total_input = 0.0
    total_bad = 0.0
    has_col_filter = process_name in ("鍛壓", "固熔") and (batch_filter or line_filter)
    for record in records:
        if has_col_filter:
            cols = _matching_col_indices(record, process_name, batch_filter, line_filter)
            for idx in cols:
                total_input += _to_float(getattr(record, f"input_{idx}", None)) or 0.0
                total_bad += _to_float(getattr(record, f"bad_{idx}", None)) or 0.0
        else:
            total_input += _record_input_value(record)
            total_bad += _record_bad_value(record)
    latest_date = records[-1].production_date.isoformat() if records else "-"
    return [
        {"label": "记录数", "value": len(records)},
        {"label": "投入數合计", "value": _format_number(total_input)},
        {"label": "不良數合计", "value": _format_number(total_bad)},
        {"label": "最近日期", "value": latest_date},
        {"label": "製程", "value": process_name},
    ]


def _build_chart_specs(
    records: list[Any], process_name: str,
    batch_filter: str = "", line_filter: str = "",
) -> list[dict[str, Any]]:
    if process_name == "鍛壓":
        return _build_duanya_charts(records, batch_filter, line_filter)
    if process_name == "固熔":
        return _build_gurong_charts(records, line_filter=line_filter)
    return _build_generic_charts(records, process_name)


def _build_duanya_charts(
    records: list[Any],
    batch_filter: str = "", line_filter: str = "",
) -> list[dict[str, Any]]:
    labels = _sorted_labels(records)
    has_col_filter = batch_filter or line_filter
    total_input_by_date: dict[str, float] = defaultdict(float)
    total_bad_by_date: dict[str, float] = defaultdict(float)
    batch_series: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    line_series: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    defect_by_type_date: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for record in records:
        day = record.production_date.isoformat()
        cols = (
            _matching_col_indices(record, "鍛壓", batch_filter, line_filter)
            if has_col_filter else [1, 2, 3, 4]
        )
        if has_col_filter:
            for idx in cols:
                total_input_by_date[day] += _to_float(getattr(record, f"input_{idx}", None)) or 0.0
                total_bad_by_date[day] += _to_float(getattr(record, f"bad_{idx}", None)) or 0.0
        else:
            total_input_by_date[day] += _to_float(record.input_total) or 0.0
            total_bad_by_date[day] += _to_float(record.bad_total) or 0.0

        for idx in cols:
            batch = getattr(record, f"batch_{idx}", None)
            if batch:
                batch_series[batch][day] += _to_float(getattr(record, f"bad_{idx}", None)) or 0.0
            line = getattr(record, f"line_{idx}", None)
            if line:
                line_series[line][day] += _to_float(getattr(record, f"bad_{idx}", None)) or 0.0
            for prefix, defect_label in DUANYA_DEFECT_TYPES:
                val = _to_float(getattr(record, f"{prefix}_badnum_{idx}", None)) or 0.0
                defect_by_type_date[defect_label][day] += val

    defect_totals = {lb: sum(by_date.values()) for lb, by_date in defect_by_type_date.items()}
    top_defect_names = [
        lb for lb, total in sorted(defect_totals.items(), key=lambda x: x[1], reverse=True)
        if total > 0
    ][:5]

    return [
        _chart_spec(
            "metrics",
            "投入數 / 不良數趋势",
            labels,
            [
                {"label": "投入數", "data": [_format_chart_number(total_input_by_date[lb]) for lb in labels]},
                {"label": "不良數", "data": [_format_chart_number(total_bad_by_date[lb]) for lb in labels]},
            ],
        ),
        _chart_spec(
            "batch",
            "按原材批次不良數趋势",
            labels,
            [
                {"label": name, "data": [_format_chart_number(values[lb]) for lb in labels]}
                for name, values in sorted(batch_series.items())
            ],
        ),
        _chart_spec(
            "line",
            "按線別/號不良數趋势",
            labels,
            [
                {"label": name, "data": [_format_chart_number(values[lb]) for lb in labels]}
                for name, values in sorted(line_series.items())
            ],
        ),
        _chart_spec(
            "defect",
            "Top 不良類型趋势",
            labels,
            [
                {"label": name, "data": [_format_chart_number(defect_by_type_date[name][lb]) for lb in labels]}
                for name in top_defect_names
            ],
        ),
    ]


def _build_gurong_charts(
    records: list[Any],
    line_filter: str = "",
) -> list[dict[str, Any]]:
    """固熔：無原材批次圖，僅線體 + 指標 + 不良類型。"""
    labels = _sorted_labels(records)
    has_col_filter = bool(line_filter)
    total_input_by_date: dict[str, float] = defaultdict(float)
    total_bad_by_date: dict[str, float] = defaultdict(float)
    line_series: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    defect_by_type_date: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for record in records:
        day = record.production_date.isoformat()
        cols = (
            _matching_col_indices(record, "固熔", line_filter=line_filter)
            if has_col_filter else [1, 2, 3]
        )
        if has_col_filter:
            for idx in cols:
                total_input_by_date[day] += _to_float(getattr(record, f"input_{idx}", None)) or 0.0
                total_bad_by_date[day] += _to_float(getattr(record, f"bad_{idx}", None)) or 0.0
        else:
            total_input_by_date[day] += _to_float(record.input_total) or 0.0
            total_bad_by_date[day] += _to_float(record.bad_total) or 0.0

        for idx in cols:
            line = getattr(record, f"line_{idx}", None)
            if line:
                line_series[line][day] += _to_float(getattr(record, f"bad_{idx}", None)) or 0.0
            for prefix, defect_label in GURONG_DEFECT_TYPES:
                val = _to_float(getattr(record, f"{prefix}_badnum_{idx}", None)) or 0.0
                defect_by_type_date[defect_label][day] += val

    defect_totals = {lb: sum(by_date.values()) for lb, by_date in defect_by_type_date.items()}
    top_defect_names = [
        lb for lb, total in sorted(defect_totals.items(), key=lambda x: x[1], reverse=True)
        if total > 0
    ][:5]

    return [
        _chart_spec(
            "metrics",
            "投入數 / 不良數趋势",
            labels,
            [
                {"label": "投入數", "data": [_format_chart_number(total_input_by_date[lb]) for lb in labels]},
                {"label": "不良數", "data": [_format_chart_number(total_bad_by_date[lb]) for lb in labels]},
            ],
        ),
        _chart_spec(
            "line",
            "按線別不良數趋势",
            labels,
            [
                {"label": name, "data": [_format_chart_number(values[lb]) for lb in labels]}
                for name, values in sorted(line_series.items())
            ],
        ),
        _chart_spec(
            "defect",
            "Top 不良類型趋势",
            labels,
            [
                {"label": name, "data": [_format_chart_number(defect_by_type_date[name][lb]) for lb in labels]}
                for name in top_defect_names
            ],
        ),
    ]


def _build_generic_charts(records: list[Any], process_name: str) -> list[dict[str, Any]]:
    labels = _sorted_labels(records)
    input_by_date: dict[str, float] = defaultdict(float)
    bad_by_date: dict[str, float] = defaultdict(float)
    defect_by_type_date: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    defect_defs = PROCESS_DEFECT_MAP.get(process_name, [])
    is_cnc0 = process_name == "CNC0"

    for record in records:
        day = record.production_date.isoformat()
        input_by_date[day] += _record_input_value(record)
        bad_by_date[day] += _record_bad_value(record)

        for prefix, defect_label in defect_defs:
            if is_cnc0:
                rw = _to_float(getattr(record, f"{prefix}_badnum_reworkable", None)) or 0.0
                urw = _to_float(getattr(record, f"{prefix}_badnum_unreworkable", None)) or 0.0
                defect_by_type_date[defect_label][day] += rw + urw
            else:
                val = _to_float(getattr(record, f"{prefix}_badnum_total", None)) or 0.0
                defect_by_type_date[defect_label][day] += val

    defect_totals = {lb: sum(by_date.values()) for lb, by_date in defect_by_type_date.items()}
    top_defect_names = [
        lb for lb, total in sorted(defect_totals.items(), key=lambda x: x[1], reverse=True)
        if total > 0
    ][:5]

    return [
        _chart_spec(
            "metrics",
            f"{process_name} 投入數 / 不良數趋势",
            labels,
            [
                {"label": "投入數", "data": [_format_chart_number(input_by_date[lb]) for lb in labels]},
                {"label": "不良數", "data": [_format_chart_number(bad_by_date[lb]) for lb in labels]},
            ],
        ),
        _chart_spec(
            "defect",
            f"{process_name} Top 不良類型趋势",
            labels,
            [
                {"label": name, "data": [_format_chart_number(defect_by_type_date[name][lb]) for lb in labels]}
                for name in top_defect_names
            ],
        ),
    ]


def _build_table_data(
    records: list[Any], process_name: str,
    batch_filter: str = "", line_filter: str = "",
) -> tuple[list[str], list[list[str]]]:
    headers = ["生產日期", "班別", "品名", "製程", "投入數", "不良數"]
    has_col_filter = process_name in ("鍛壓", "固熔") and (batch_filter or line_filter)
    rows: list[list[str]] = []
    for record in records:
        if has_col_filter:
            cols = _matching_col_indices(record, process_name, batch_filter, line_filter)
            input_val = sum((_to_float(getattr(record, f"input_{idx}", None)) or 0.0) for idx in cols)
            bad_val = sum((_to_float(getattr(record, f"bad_{idx}", None)) or 0.0) for idx in cols)
            input_text = _format_number(input_val)
            bad_text = _format_number(bad_val)
        else:
            input_text = _record_primary_input_text(record)
            bad_text = _record_primary_bad_text(record)

        row = [
            record.production_date.isoformat(),
            record.shift or "-",
            record.product_name or "-",
            record.process_name,
            input_text,
            bad_text,
        ]
        if process_name == "鍛壓":
            if has_col_filter:
                matched_batches = [getattr(record, f"batch_{idx}", None) for idx in cols]
                matched_lines = [getattr(record, f"line_{idx}", None) for idx in cols]
                row.extend([
                    " / ".join([v for v in matched_batches if v]) or "-",
                    " / ".join([v for v in matched_lines if v]) or "-",
                ])
            else:
                row.extend([
                    " / ".join([v for v in [record.batch_1, record.batch_2] if v]) or "-",
                    " / ".join([v for v in [record.line_1, record.line_2] if v]) or "-",
                ])
        elif process_name == "固熔":
            if has_col_filter:
                matched_lines = [getattr(record, f"line_{idx}", None) for idx in cols]
                row.extend([
                    " / ".join([v for v in matched_lines if v]) or "-",
                ])
            else:
                row.extend(
                    [" / ".join([v for v in [record.line_1, record.line_2] if v]) or "-"],
                )
        elif process_name == "CNC0":
            row.extend([
                getattr(record, "inspection_location", None) or "-",
                record.sample if record.sample is not None else "-",
            ])
        rows.append(row)
    if records and process_name == "鍛壓":
        if has_col_filter:
            headers = headers + ["匹配批次", "匹配線別"]
        else:
            headers = headers + ["原材批次(前两组)", "線別/號(前两组)"]
    elif records and process_name == "固熔":
        if has_col_filter:
            headers = headers + ["匹配線別"]
        else:
            headers = headers + ["線別(前两组)"]
    elif records and process_name == "CNC0":
        headers = headers + ["抽檢位置", "抽檢數"]
    return headers, rows


def _is_summary_table(table: Tag) -> bool:
    rows = table.find_all("tr")
    if not rows:
        return False
    if len(rows) == 1:
        cells = rows[0].find_all(["td", "th"])
        if not cells:
            return False
        texts = [_compact_text(cell.get_text(" ", strip=True)) for cell in cells]
        return all((":" in text or "：" in text) for text in texts)
    # 多行摘要：与前端 isSummaryTable 一致，避免第二段摘要被误判为非摘要
    if len(rows) > 4:
        return False
    blob = _compact_text(table.get_text(" ", strip=True))
    if not re.search(r"(生產日期|班別|品名|製程|抽檢)", blob):
        return False
    for row in rows:
        cells = row.find_all(["td", "th"])
        if not cells:
            return False
        texts = [_compact_text(c.get_text(" ", strip=True)) for c in cells]
        if not any(":" in t or "：" in t for t in texts):
            return False
    return True


def _parse_summary_table(table: Tag) -> dict[str, str]:
    summary: dict[str, str] = {}
    for cell in table.find_all(["td", "th"]):
        text = _compact_text(cell.get_text(" ", strip=True))
        if "：" in text:
            key, value = text.split("：", 1)
        elif ":" in text:
            key, value = text.split(":", 1)
        else:
            continue
        summary[key.strip()] = value.strip()
    return summary


def _fill_summary_fallbacks(summary: dict[str, str], block_html: str) -> dict[str, str]:
    """摘要表缺字段时，从当前块文本兜底提取。"""
    result = dict(summary)
    block_text = BeautifulSoup(block_html, "html.parser").get_text(" ", strip=True)
    if not result.get("班別"):
        match = re.search(r"(白班|晚班)", block_text)
        if match:
            result["班別"] = match.group(1)
    return result


def _table_to_grid(table: Tag) -> list[list[str]]:
    rows = table.find_all("tr")
    grid: list[list[str | None]] = []
    for row_idx, row in enumerate(rows):
        cells = row.find_all(["td", "th"])
        if len(grid) <= row_idx:
            grid.append([])
        col_idx = 0
        for cell in cells:
            while col_idx < len(grid[row_idx]) and grid[row_idx][col_idx] is not None:
                col_idx += 1
            rowspan = int(cell.get("rowspan", 1))
            colspan = int(cell.get("colspan", 1))
            value = _compact_text(cell.get_text(" ", strip=True))
            for r in range(row_idx, min(row_idx + rowspan, len(rows))):
                if len(grid) <= r:
                    grid.append([])
                for c in range(col_idx, col_idx + colspan):
                    while len(grid[r]) <= c:
                        grid[r].append(None)
                    if grid[r][c] is None:
                        grid[r][c] = value
            col_idx += colspan
    return [[cell or "" for cell in row] for row in grid]




def _find_row_by_col2(grid: list[list[str]], labels: set[str]) -> int | None:
    normalized_labels = {_normalize_label(label) for label in labels}
    for idx, row in enumerate(grid, start=1):
        if len(row) >= 2 and _normalize_label(row[1]) in normalized_labels:
            return idx
    return None


def gird_extract_value(grid: list[list[str]], row_idx: int | None, col_idx: int) -> str | None:
    '''返回的要么是字符串，要么是None'''
    if row_idx is None or row_idx - 1 >= len(grid) or row_idx <= 0:
        return None
    row = grid[row_idx - 1]
    if col_idx - 1 >= len(row) or col_idx <= 0:
        return None
    value = row[col_idx - 1]
    return value if value else None


def _value_or_zero_text(value: Any) -> str:
    """把 OCR 缺失值统一归一到字符串 '0'。"""
    if value is None:
        return "0"
    text = str(value).strip()
    if not text or text in {"-", "—", "NULL", "None"}:
        return "0"
    return text


def infer_dashboard_key_from_markdown(markdown: str | None) -> str | None:
    """根据未验证 OCR 正文推断看板大类：沖壓 / 金加。无法判断时返回 None。"""
    if not markdown or not str(markdown).strip():
        return None
    text = str(markdown)
    chong_positions = [text.find(t) for t in ("沖壓", "冲压") if text.find(t) >= 0]
    idx_chong = min(chong_positions) if chong_positions else -1
    idx_jin = text.find("金加")
    if idx_chong >= 0 and idx_jin >= 0:
        return "沖壓" if idx_chong <= idx_jin else "金加"
    if idx_chong >= 0:
        return "沖壓"
    if idx_jin >= 0:
        return "金加"
    soup = BeautifulSoup(f"<div>{text}</div>", "html.parser")
    for table in soup.find_all("table"):
        if _is_summary_table(table):
            summary = _parse_summary_table(table)
            proc = (summary.get("製程") or "").strip()
            if proc:
                return _key_from_process(proc)
    return None


def delete_dashboard_records_for_ocr_result(db: Session, ocr_result_id: int) -> int:
    """删除某条 ocr_result 曾写入的全部看板行（五表）。"""
    deleted = 0
    for model in (
        BoardChongyaDuanya,
        BoardChongyaGurong,
        BoardChongyaShixiao,
        BoardJinjiaCnc0,
        BoardJinjiaCnc0Full,
    ):
        rows = db.scalars(select(model).where(model.ocr_result_id == ocr_result_id)).all()
        for row in rows:
            db.delete(row)
            deleted += 1
    return deleted


def delete_dashboard_records_for_task(db: Session, task_id: int) -> int:
    """删除某任务在五张看板上的全部行（同一 task 可能有多条 ocr_result，验证前需整任务清空）。"""
    deleted = 0
    for model in (
        BoardChongyaDuanya,
        BoardChongyaGurong,
        BoardChongyaShixiao,
        BoardJinjiaCnc0,
        BoardJinjiaCnc0Full,
    ):
        rows = db.scalars(select(model).where(model.task_id == task_id)).all()
        for row in rows:
            db.delete(row)
            deleted += 1
    return deleted


def list_board_records_for_stats(
    db: Session,
    *,
    key_name: str,
    process_name: str | None = None,
    shift_filter: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """按大类与可选条件查询看板记录列表（统计页已验证区）。"""
    if key_name not in KEY_PROCESS_OPTIONS:
        return []
    models = (
        (BoardChongyaDuanya, BoardChongyaGurong, BoardChongyaShixiao)
        if key_name == "沖壓"
        else (BoardJinjiaCnc0, BoardJinjiaCnc0Full)
    )
    process_ok = KEY_PROCESS_OPTIONS[key_name]
    if process_name and process_name not in process_ok:
        process_name = None
    out: list[dict[str, Any]] = []
    for model in models:
        stmt = select(model).where(model.key_name == key_name)
        if process_name:
            stmt = stmt.where(model.process_name == process_name)
        if shift_filter and shift_filter in ("白班", "晚班"):
            stmt = stmt.where(model.shift == shift_filter)
        if start_date is not None:
            stmt = stmt.where(model.production_date >= start_date)
        if end_date is not None:
            stmt = stmt.where(model.production_date <= end_date)
        stmt = stmt.order_by(model.production_date.desc(), model.id.desc())
        for record in db.scalars(stmt).all():
            out.append(
                {
                    "key_name": record.key_name,
                    "process_name": record.process_name,
                    "shift": record.shift,
                    "production_date": record.production_date,
                    "task_id": record.task_id,
                    "ocr_result_id": record.ocr_result_id,
                }
            )
    out.sort(key=lambda r: (r["production_date"], r["ocr_result_id"]), reverse=True)
    return out[:limit]


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _normalize_label(value: str) -> str:
    return _compact_text(value).replace(" ", "").replace("標號", "號")


def _key_from_process(process: str) -> str:
    if process in {"鍛壓", "固熔", "時效"}:
        return "沖壓"
    return "金加"


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "—", "NULL", "None"}:
        return None
    text = text.replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def _format_number(value: float) -> str:
    if abs(value - int(value)) < 1e-9:
        return str(int(value))
    return f"{value:.2f}"


def _format_chart_number(value: float) -> float | int:
    if abs(value - int(value)) < 1e-9:
        return int(value)
    return round(value, 2)


def _sorted_labels(records: list[Any]) -> list[str]:
    return sorted({record.production_date.isoformat() for record in records})


def _chart_spec(chart_id: str, title: str, labels: list[str], datasets: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": chart_id,
        "title": title,
        "labels": labels,
        "datasets": datasets,
    }


def _record_input_value(record: Any) -> float:
    if hasattr(record, "input_total") and record.input_total is not None:
        v = _to_float(record.input_total)
        if v is not None:
            return v
    v = getattr(record, "input", None)
    if v is not None:
        return _to_float(v) or 0.0
    return _to_float(getattr(record, "input_count", None)) or 0.0


def _record_bad_value(record: Any) -> float:
    if hasattr(record, "bad_total") and record.bad_total is not None:
        v = _to_float(record.bad_total)
        if v is not None:
            return v
    for attr in ("bad_count", "bad"):
        v = getattr(record, attr, None)
        if v is not None:
            return _to_float(v) or 0.0
    return 0.0


def _record_primary_input_text(record: Any) -> str:
    if hasattr(record, "input_total") and record.input_total is not None and str(record.input_total).strip() != "":
        return str(record.input_total)
    v = getattr(record, "input", None)
    if v is not None:
        fv = _to_float(v)
        return _format_number(fv) if fv is not None else str(v)
    return getattr(record, "input_count", None) or "-"


def _record_primary_bad_text(record: Any) -> str:
    if hasattr(record, "bad_total") and record.bad_total is not None and str(record.bad_total).strip() != "":
        return str(record.bad_total)
    for attr in ("bad_count", "bad"):
        v = getattr(record, attr, None)
        if v is not None:
            return str(v)
    return "-"
