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
INSPECTION_LOCATION_OPTIONS = ["製程抽檢", "入庫抽檢"]
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


def _stmt_match_product_name(model: type, stmt: Any, payload: dict[str, Any]) -> Any:
    """唯一键中的品名：与 DDL 一致，NULL 与具体值分列。"""
    pname = payload.get("product_name")
    if pname is None:
        return stmt.where(model.product_name.is_(None))
    return stmt.where(model.product_name == pname)


def find_existing_board_row(
    db: Session,
    model: type,
    payload: dict[str, Any],
) -> Any | None:
    """按业务唯一键查已有行（均含 production_date + shift + product_name；锻压另加 part；CNC0 另加 inspection_location）。"""
    d = payload["production_date"]
    shift_val = payload.get("shift")
    stmt = select(model).where(model.production_date == d)
    if shift_val is None:
        stmt = stmt.where(model.shift.is_(None))
    else:
        stmt = stmt.where(model.shift == shift_val)
    stmt = _stmt_match_product_name(model, stmt, payload)
    if model is BoardChongyaDuanya:
        stmt = stmt.where(model.part == payload.get("part", 1))
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
            row["product_name"] = p.get("product_name")
            if item.model is BoardJinjiaCnc0:
                row["inspection_location"] = p.get("inspection_location")
            if item.model is BoardChongyaDuanya:
                row["part"] = p.get("part", 1)
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
    end_value = parse_iso_date(end_date) or date.today()
    start_value = parse_iso_date(start_date) or (end_value - timedelta(days=29))

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

    production_date = parse_iso_date(summary.get("生產日期"))
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
        payload = build_duanya_payload(grid)
        payload["part"] = _summary_page_to_part(summary)
        unique_filter = {
            "key_name": key_name,
            "process_name": process,
            "production_date": production_date,
            "shift": summary.get("班別"),
            "product_name": summary.get("品名"),
            "part": payload["part"],
        }
    elif model is BoardChongyaGurong:
        payload = build_gurong_payload(grid)
        unique_filter = {
            "key_name": key_name,
            "process_name": process,
            "production_date": production_date,
            "shift": summary.get("班別"),
            "product_name": summary.get("品名"),
        }
    elif model is BoardChongyaShixiao:
        payload = build_shixiao_payload(grid)
        unique_filter = {
            "key_name": key_name,
            "process_name": process,
            "production_date": production_date,
            "shift": summary.get("班別"),
            "product_name": summary.get("品名"),
        }
    elif model is BoardJinjiaCnc0:
        payload = build_cnc0_payload(grid)
        unique_filter = {
            "key_name": key_name,
            "process_name": process,
            "production_date": production_date,
            "shift": summary.get("班別"),
            "product_name": summary.get("品名"),
            "inspection_location": summary.get("抽檢位置"),
        }
    else:
        payload = build_cnc0_full_payload(grid)
        unique_filter = {
            "key_name": key_name,
            "process_name": process,
            "production_date": production_date,
            "shift": summary.get("班別"),
            "product_name": summary.get("品名"),
        }

    return ParsedDashboardRecord(
        model=model,
        unique_filter=unique_filter,
        payload={**common_payload, **payload},
    )


def build_duanya_payload(grid: list[list[str]]) -> dict[str, Any]:
    """锻压数据解析函数：提取批次/线别/投入/良品/不良 与 9 类不良数。"""

    data_cols = [3, 5, 7, 9]  # 对应 _1, _2, _3, _4

    batch_vals = [gird_extract_value(grid, 1, col) for col in data_cols]
    # 線別/模號；前面 _table_to_grid 拼接首列后会带"線 模"占位，剔除
    line_vals = [
        gird_extract_value(grid, 2, col) if gird_extract_value(grid, 2, col) != "線 模" else None
        for col in data_cols
    ]

    input_vals = [
        int(gird_extract_value(grid, 3, col)) if gird_extract_value(grid, 3, col) is not None else None
        for col in data_cols
    ]
    input_total = sum(val for val in input_vals if val is not None)
    good_vals = [
        int(gird_extract_value(grid, 4, col)) if gird_extract_value(grid, 4, col) is not None else None
        for col in data_cols
    ]
    good_total = sum(val for val in good_vals if val is not None)
    bad_vals = [
        int(gird_extract_value(grid, 5, col)) if gird_extract_value(grid, 5, col) is not None else None
        for col in data_cols
    ]
    bad_total = sum(val for val in bad_vals if val is not None)
    actual_yield_total = round((good_total / input_total) * 100, 2) if input_total else None

    # 9 类不良数据：数据行从 grid 第 9 行开始，依次对应 DUANYA_DEFECT_TYPES 顺序
    defect_rows = [9, 10, 11, 12, 13, 14, 15, 16, 17]
    defect_keys = [prefix for prefix, _ in DUANYA_DEFECT_TYPES]

    payload: dict[str, Any] = {
        "batch_1": batch_vals[0], "batch_2": batch_vals[1], "batch_3": batch_vals[2], "batch_4": batch_vals[3],
        "line_1": line_vals[0], "line_2": line_vals[1], "line_3": line_vals[2], "line_4": line_vals[3],
        "input_1": input_vals[0], "input_2": input_vals[1], "input_3": input_vals[2], "input_4": input_vals[3],
        "input_total": input_total,
        "good_1": good_vals[0], "good_2": good_vals[1], "good_3": good_vals[2], "good_4": good_vals[3],
        "good_total": good_total,
        "bad_1": bad_vals[0], "bad_2": bad_vals[1], "bad_3": bad_vals[2], "bad_4": bad_vals[3],
        "bad_total": bad_total,
        "actual_yield_total": actual_yield_total,
        "target_yield_total": 99.80,
    }

    for prefix, row_idx in zip(defect_keys, defect_rows):
        col_nums: list[int | None] = []
        for i in range(4):
            cell = gird_extract_value(grid, row_idx, data_cols[i])
            if input_vals[i] is None:
                col_nums.append(None)
            else:
                col_nums.append(int(cell) if cell is not None else 0)
        total_num = sum(v for v in col_nums if v is not None)
        payload[f"{prefix}_badnum_1"] = col_nums[0]
        payload[f"{prefix}_badnum_2"] = col_nums[1]
        payload[f"{prefix}_badnum_3"] = col_nums[2]
        payload[f"{prefix}_badnum_4"] = col_nums[3]
        payload[f"{prefix}_badnum_total"] = total_num

    return payload


def build_gurong_payload(grid: list[list[str]]) -> dict[str, Any]:
    """固熔数据解析函数：3 线体 + 汇总，无原材批次。"""
    data_cols = [3, 5, 7]

    line_vals: list[str | None] = []
    for col in data_cols:
        val = gird_extract_value(grid, 1, col)
        line_vals.append(val if val is not None and val.strip() != "線" else None)

    input_vals = [
        int(gird_extract_value(grid, 2, col)) if gird_extract_value(grid, 2, col) is not None else None
        for col in data_cols
    ]
    input_total = sum(val for val in input_vals if val is not None)
    good_vals = [
        int(gird_extract_value(grid, 3, col)) if gird_extract_value(grid, 3, col) is not None else None
        for col in data_cols
    ]
    good_total = sum(val for val in good_vals if val is not None)
    bad_vals = [
        int(gird_extract_value(grid, 4, col)) if gird_extract_value(grid, 4, col) is not None else None
        for col in data_cols
    ]
    bad_total = sum(val for val in bad_vals if val is not None)
    actual_yield_total = round((good_total / input_total) * 100, 2) if input_total else None

    defect_rows = [8, 9, 10]
    defect_keys = [prefix for prefix, _ in GURONG_DEFECT_TYPES]

    payload: dict[str, Any] = {
        "line_1": line_vals[0], "line_2": line_vals[1], "line_3": line_vals[2],
        "input_1": input_vals[0], "input_2": input_vals[1], "input_3": input_vals[2],
        "input_total": input_total,
        "good_1": good_vals[0], "good_2": good_vals[1], "good_3": good_vals[2],
        "good_total": good_total,
        "bad_1": bad_vals[0], "bad_2": bad_vals[1], "bad_3": bad_vals[2],
        "bad_total": bad_total,
        "actual_yield_total": actual_yield_total,
        "target_yield_total": 100.00,
    }

    for prefix, row_idx in zip(defect_keys, defect_rows):
        col_nums: list[int | None] = []
        for i in range(3):
            cell = gird_extract_value(grid, row_idx, data_cols[i])
            if input_vals[i] is None:
                col_nums.append(None)
            else:
                col_nums.append(int(cell) if cell is not None else 0)
        total_num = sum(v for v in col_nums if v is not None)
        payload[f"{prefix}_badnum_1"] = col_nums[0]
        payload[f"{prefix}_badnum_2"] = col_nums[1]
        payload[f"{prefix}_badnum_3"] = col_nums[2]
        payload[f"{prefix}_badnum_total"] = total_num

    return payload


def build_shixiao_payload(grid: list[list[str]]) -> dict[str, Any]:
    """时效数据解析函数：单列（投入/良品/不良 + 4 类不良数）。"""
    input_total = _grid_extract_int(grid, 1, 3, default=0)
    good_total = _grid_extract_int(grid, 2, 3, default=0)
    bad_total = _grid_extract_int(grid, 3, 3, default=0)
    actual_yield_total = round((good_total / input_total) * 100, 2) if input_total else None

    # 4 类不良：行号 7..10 对应 SHIXIAO_DEFECT_TYPES
    defect_rows = [7, 8, 9, 10]
    defect_keys = [prefix for prefix, _ in SHIXIAO_DEFECT_TYPES]

    payload: dict[str, Any] = {
        "input_total": input_total,
        "good_total": good_total,
        "bad_total": bad_total,
        "actual_yield_total": actual_yield_total,
        "target_yield_total": 100.00,
    }
    for prefix, row_idx in zip(defect_keys, defect_rows):
        cell = gird_extract_value(grid, row_idx, 3)
        payload[f"{prefix}_badnum_total"] = int(cell) if cell is not None else 0
    return payload

def build_cnc0_payload(grid: list[list[str]]) -> dict[str, Any]:
    """CNC0 数据解析函数：单列基础指标 + 8 类不良（可重工/不可重工 两列）。"""
    input_total = _grid_extract_int(grid, 1, 3, default=0)
    sample = _grid_extract_int(grid, 2, 3, default=0)
    first_good = _grid_extract_int(grid, 3, 3, default=0)
    bad_total = _grid_extract_int(grid, 4, 3, default=0)
    reworkable_bad = _grid_extract_int(grid, 5, 3, default=0)
    unreworkable_bad = _grid_extract_int(grid, 6, 3, default=0)
    first_yield = round((first_good / input_total) * 100, 2) if input_total else None
    second_yield = (
        round(((input_total - unreworkable_bad) / input_total) * 100, 2) if input_total else None
    )

    defect_rows = [12, 13, 14, 15, 16, 17, 18, 19]
    defect_keys = [prefix for prefix, _ in CNC0_DEFECT_TYPES]

    payload: dict[str, Any] = {
        "input_total": input_total,
        "sample": sample,
        "first_good": first_good,
        "bad_total": bad_total,
        "reworkable_bad": reworkable_bad,
        "unreworkable_bad": unreworkable_bad,
        "first_yield": first_yield,
        "second_yield": second_yield,
        "first_target_yield": 99.70,
        "second_target_yield": 100.00,
    }

    for prefix, row_idx in zip(defect_keys, defect_rows):
        rw_cell = gird_extract_value(grid, row_idx, 3)
        urw_cell = gird_extract_value(grid, row_idx, 4)
        payload[f"{prefix}_badnum_reworkable"] = int(rw_cell) if rw_cell is not None else 0
        payload[f"{prefix}_badnum_unreworkable"] = int(urw_cell) if urw_cell is not None else 0

    return payload


def build_cnc0_full_payload(grid: list[list[str]]) -> dict[str, Any]:
    """CNC0 全检 数据解析函数：单列基础指标 + 3 类不良数。"""
    input_total = _grid_extract_int(grid, 1, 3, default=0)
    first_good = _grid_extract_int(grid, 2, 3, default=0)
    bad_total = _grid_extract_int(grid, 3, 3, default=0)
    reworkable_bad = _grid_extract_int(grid, 4, 3, default=0)
    unreworkable_bad = _grid_extract_int(grid, 5, 3, default=0)
    first_yield = round((first_good / input_total) * 100, 2) if input_total else None
    second_yield = (
        round(((input_total - unreworkable_bad) / input_total) * 100, 2) if input_total else None
    )

    defect_rows = [11, 12, 13]
    defect_keys = [prefix for prefix, _ in CNC0_FULL_DEFECT_TYPES]

    payload: dict[str, Any] = {
        "input_total": input_total,
        "first_good": first_good,
        "bad_total": bad_total,
        "reworkable_bad": reworkable_bad,
        "unreworkable_bad": unreworkable_bad,
        "first_yield": first_yield,
        "second_yield": second_yield,
        "first_target_yield": 99.90,
        "second_target_yield": 100.00,
    }

    for prefix, row_idx in zip(defect_keys, defect_rows):
        cell = gird_extract_value(grid, row_idx, 3)
        payload[f"{prefix}_badnum_total"] = int(cell) if cell is not None else 0

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
            total_input += record_input_value(record)
            total_bad += record_bad_value(record)
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
        input_by_date[day] += record_input_value(record)
        bad_by_date[day] += record_bad_value(record)

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
            input_text = record_primary_input_text(record)
            bad_text = record_primary_bad_text(record)

        row = [
            record.production_date.isoformat(),
            record.shift or "-",
            record.product_name or "-",
            record.process_name,
            input_text,
            bad_text,
        ]
        if process_name == "鍛壓":
            row.append(str(getattr(record, "part", 1) or 1))
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
        headers = headers + ["页码"]
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
    if not re.search(r"(生產日期|班別|品名|製程|抽檢|页码|頁碼)", blob):
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


def _summary_page_to_part(summary: dict[str, str]) -> int:
    """摘要 页码/頁碼 → 锻压表 part（1 或 2），与 UNIQUE 键一致；缺省或无法解析为 1。"""
    for k in ("页码", "頁碼"):
        raw = (summary.get(k) or "").strip()
        if not raw:
            continue
        if raw in ("1", "2"):
            return int(raw)
        m = re.search(r"[12]", raw)
        if m:
            return int(m.group(0))
    return 1


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


def _grid_extract_int(grid: list[list[str]], row_idx: int | None, col_idx: int, *, default: int = 0) -> int:
    """从表格网格安全取整型：空值或非法值返回 default，避免 int(None) 导致验证失败。"""
    value = gird_extract_value(grid, row_idx, col_idx)
    if value is None:
        return default
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "—", "NULL", "None"}:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default




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
            item: dict[str, Any] = {
                "key_name": record.key_name,
                "process_name": record.process_name,
                "shift": record.shift,
                "production_date": record.production_date,
                "task_id": record.task_id,
                "ocr_result_id": record.ocr_result_id,
            }
            if model is BoardChongyaDuanya:
                item["part"] = getattr(record, "part", None)
            out.append(item)
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


def parse_iso_date(value: str | None) -> date | None:
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


def record_input_value(record: Any) -> float:
    """从 board_* ORM 行取 input_total 数值（不存在或非法时返回 0）。"""
    return _to_float(getattr(record, "input_total", None)) or 0.0


def record_bad_value(record: Any) -> float:
    """从 board_* ORM 行取 bad_total 数值（不存在或非法时返回 0）。"""
    return _to_float(getattr(record, "bad_total", None)) or 0.0


def record_primary_input_text(record: Any) -> str:
    """input_total 文本展示：None 或空串显示为 '-'。"""
    val = getattr(record, "input_total", None)
    if val is None or str(val).strip() == "":
        return "-"
    return str(val)


def record_primary_bad_text(record: Any) -> str:
    """bad_total 文本展示：None 或空串显示为 '-'。"""
    val = getattr(record, "bad_total", None)
    if val is None or str(val).strip() == "":
        return "-"
    return str(val)
