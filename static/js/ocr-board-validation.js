/**
 * 看板 OCR：摘要表与五种主表的前端校验、可编辑格范围、提交前校验与拼稿（与后端入库顺序一致）。
 * 依赖：ocr-dom（getOcrResultMeta、getOcrResultTables）、ocr-utils-html（sanitizeBasicHtml）。
 *
 * 行为：不在输入阶段限制或清洗字符；用户点击「通过」时按 MAIN_TABLE_RULES 等规则判定，不通过则提交失败并标红。
 */

import { getOcrResultMeta, getOcrResultTables } from "./ocr-dom.js";
import { sanitizeBasicHtml } from "./ocr-utils-html.js";
import { state } from "./ocr-state.js";

// ---------- 提交前表格校验（摘要表 + 五种主表） ----------

const BOARD_TEMPLATE_PROCESSES = ["CNC0 全檢", "CNC0", "鍛壓", "固熔", "時效"];
const SUMMARY_REQUIRED_FIELDS = ["生產日期", "班別", "品名", "製程"];
const SUMMARY_ALLOWED_PRODUCTS = new Set(["Y20 Housing", "X3784 Housing"]);
const SUMMARY_ALLOWED_SHIFTS = new Set(["白班", "晚班"]);
const SUMMARY_ALLOWED_CHONGYA_PROCESSES = new Set(["鍛壓", "固熔", "時效"]);
const SUMMARY_ALLOWED_JINJIA_PROCESSES = new Set(["CNC0", "CNC0 全檢"]);
const SUMMARY_ALLOWED_INSPECTION_LOCATIONS = new Set(["製程抽檢", "入庫抽檢"]);
const SUMMARY_DIRECT_EDIT_FIELDS = new Set(["生產日期"]);
const SUMMARY_TOGGLE_OPTIONS = {
    班別: ["白班", "晚班"],
    品名: ["Y20 Housing", "X3784 Housing"],
    抽檢位置: ["製程抽檢", "入庫抽檢"],
};

/**
 * 固熔第一行線別：空为通过；非空则仅允许 A–Z、a–z 与「線」（与后端 gurong_line_processor 一致）。
 */
const gurongLineValidator = (text) => {
    const normalized = String(text ?? "").trim();
    if (normalized === "") return true;
    return /^[A-Za-z線]+$/.test(normalized);
};

const strictIntValidator = (text) => {
    const normalized = String(text ?? "").trim();
    return normalized === "" || /^\d+$/.test(normalized);
};
/** 鍛壓 row1：五个数字-一个数字，中间可穿插空格（去空格后校验） */
const batchValidator = (text) => {
    const raw = String(text ?? "").trim();
    if (raw === "") return true;
    const compact = raw.replace(/\s/g, "");
    return /^\d{5}-\d$/.test(compact);
};
/** 鍛壓 row2：「一位数字+線+三位数字+模」或「空格+線+空格+模」占位 */
const lineModelValidator = (text) => {
    const s = String(text ?? "");
    if (s.trim() === "") return true;
    const okLine = /^\s*\d\s*線\s*\d{3}\s*模\s*$/.test(s);
    const okPlaceholder = /^\s+線\s+模\s*$/.test(s);
    return okLine || okPlaceholder;
};
const MAIN_TABLE_RULES = {
    鍛壓: [
        { rowRange: [1, 1], colList: [3, 5, 7, 9], validate: batchValidator, label: "五数字-一数字(可含空格)" },
        { rowRange: [2, 2], colList: [3, 5, 7, 9], validate: lineModelValidator,label: "一数字+線+三数字+模 或 空格+線+空格+模" },
        { rowRange: [3, 5], colList: [3, 5, 7, 9], validate: strictIntValidator, label: "纯数字 int" },
        { rowRange: [9, 17], colList: [3, 5, 7, 9], validate: strictIntValidator, label: "纯数字 int" },
    ],
    固熔: [
        { rowRange: [1, 1], colList: [3, 5, 7], validate: gurongLineValidator, label: "線別（仅英文字母与「線」）" },
        { rowRange: [2, 4], colList: [3, 5, 7], validate: strictIntValidator, label: "纯数字 int" },
        { rowRange: [8, 10], colList: [3, 5, 7], validate: strictIntValidator, label: "纯数字 int" },
    ],
    時效: [
        { rowRange: [1, 3], colList: [3], validate: strictIntValidator, label: "纯数字 int" },
        { rowRange: [7, 10], colList: [3], validate: strictIntValidator, label: "纯数字 int" },
    ],
    CNC0: [
        { rowRange: [1, 6], colList: [3], validate: strictIntValidator, label: "纯数字 int" },
        { rowRange: [12, 19], colList: [3, 4], validate: strictIntValidator, label: "纯数字 int" },
    ],
    "CNC0 全檢": [
        { rowRange: [1, 5], colList: [3], validate: strictIntValidator, label: "纯数字 int" },
        { rowRange: [11, 13], colList: [3, 4], validate: strictIntValidator, label: "纯数字 int" },
    ],
};

/** 仅划定可编辑单元格（contenteditable=true）；提交时与 MAIN_TABLE_RULES 联合校验 */
export const MAIN_TABLE_EDITABLE_SPECS = {
    鍛壓: [
        { rowRange: [1, 1], colList: [3, 5, 7, 9] },
        { rowRange: [2, 2], colList: [3, 5, 7, 9] },
        { rowRange: [3, 5], colList: [3, 5, 7, 9] },
        { rowRange: [9, 17], colList: [3, 5, 7, 9] },
    ],
    固熔: [
        { rowRange: [1, 1], colList: [3, 5, 7] },     // 第一行：三条線別
        { rowRange: [2, 4], colList: [3, 5, 7] }, // 投入數、良品數、不良數（含匯總）
        { rowRange: [8, 10], colList: [3, 5, 7] }, // 不良項目下的不良數
    ],
    時效: [
        { rowRange: [1, 3], colList: [3] },
        { rowRange: [7, 10], colList: [3] },
    ],
    CNC0: [
        { rowRange: [1, 6], colList: [3] },
        { rowRange: [12, 19], colList: [3, 4] },
    ],
    "CNC0 全檢": [
        { rowRange: [1, 5], colList: [3] },
        { rowRange: [11, 13], colList: [3, 4] },
    ],
};

/** 与 makeTableCellsEditable 相同：当前製程下允许编辑的 td 集合（用于提交校验范围；多主表合并） */
export function getMainTableEditableCellSet(ctx) {
    const tableList = ctx?.mainTables?.length
        ? ctx.mainTables
        : ctx?.mainTable
          ? [ctx.mainTable]
          : [];
    const process = normalizeProcessName(ctx?.process || ctx?.summary?.["製程"] || "");
    if (!tableList.length || !process) return new Set();
    const editableSpecs = MAIN_TABLE_EDITABLE_SPECS[process];
    if (!editableSpecs) return new Set();
    const editableCells = new Set();
    for (const table of tableList) {
        const grid = buildGridDomRefs(table);
        for (const spec of editableSpecs) {
            const [startRow, endRow] = specRowRangeEnds(spec);
            const cols = expandRuleCols(spec);
            for (let r = startRow - 1; r < Math.min(endRow, grid.length); r++) {
                for (const visualCol of cols) {
                    const cell = grid[r]?.[visualCol - 1];
                    if (!cell || cell.tagName?.toLowerCase() === "th") continue;
                    editableCells.add(cell);
                }
            }
        }
    }
    return editableCells;
}

export function normalizeProcessName(value) {
    const compact = (value || "").replace(/\s+/g, " ").trim();
    if (!compact) return "";
    if (compact === "CNC0全檢" || compact === "CNC0 全檢") return "CNC0 全檢";
    return compact;
}

function inferKeyFromProcess(process) {
    const normalized = normalizeProcessName(process);
    if (SUMMARY_ALLOWED_JINJIA_PROCESSES.has(normalized)) return "金加";
    if (SUMMARY_ALLOWED_CHONGYA_PROCESSES.has(normalized)) return "沖壓";
    return null;
}

function detectProcessFromText(text) {
    if (!text) return null;
    const compact = text.replace(/\s+/g, " ");
    const labeled = compact.match(/製程[：:\s]*\s*(CNC0\s*全檢|CNC0|鍛壓|固熔|時效)/);
    if (labeled) {
        const raw = labeled[1].replace(/\s+/g, " ").trim();
        if (raw.includes("全檢")) return "CNC0 全檢";
        return raw;
    }
    for (const p of BOARD_TEMPLATE_PROCESSES) {
        if (compact.includes(p)) return p;
    }
    return null;
}

function isSummaryTable(table) {
    const rows = table.querySelectorAll("tr");
    if (rows.length < 1) return false;
    if (rows.length === 1) {
        const cells = rows[0].querySelectorAll("td, th");
        if (!cells.length) return false;
        return [...cells].every((td) => /[：:]/.test((td.textContent || "").trim()));
    }
    // 多行摘要（OCR 常把第二段摘要拆成多行）：行数少且含摘要字段，每行至少一格「字段：值」
    if (rows.length > 4) return false;
    const blob = (table.innerText || "").replace(/\s+/g, " ");
    if (!/(生產日期|班別|品名|製程|抽檢)/.test(blob)) return false;
    for (const tr of rows) {
        const cells = tr.querySelectorAll("td, th");
        if (!cells.length) return false;
        const rowOk = [...cells].some((td) => /[：:]/.test((td.textContent || "").trim()));
        if (!rowOk) return false;
    }
    return true;
}

/**
 * 在 isSummaryTable 之上：第二段单行摘要偶发少一格「：」时仍视为摘要，避免只收集到一张主表、锁定按钮不出现。
 */
function isSummaryTableRelaxed(table) {
    if (isSummaryTable(table)) return true;
    const rows = table.querySelectorAll("tr");
    if (rows.length !== 1) return false;
    const blob = (table.innerText || "").replace(/\s+/g, " ");
    return (
        /製程\s*[：:]/.test(blob) &&
        /生產日期\s*[：:]/.test(blob) &&
        /(班別|品名|抽檢)/.test(blob)
    );
}

function parseSummaryTable(table) {
    const summary = {};
    table.querySelectorAll("td, th").forEach((td) => {
        const pair = readSummaryCellPair(td);
        if (pair?.key) summary[pair.key] = pair.value;
    });
    return summary;
}

function parseSummaryTableEntries(table) {
    const entries = {};
    const malformedCells = [];
    table?.querySelectorAll("td, th").forEach((td) => {
        const pair = readSummaryCellPair(td);
        if (!pair) {
            malformedCells.push(td);
            return;
        }
        if (pair.key) {
            entries[pair.key] = { value: pair.value, cell: td };
        }
    });
    return { entries, malformedCells };
}

function readSummaryCellPair(cell) {
    const labelEl = cell.querySelector(".summary-field-label");
    const valueEl = cell.querySelector(".summary-field-value");
    if (labelEl) {
        return {
            key: (labelEl.textContent || "").trim(),
            value: (valueEl?.textContent || "").trim(),
        };
    }
    const t = (cell.textContent || "").replace(/\s+/g, " ").trim();
    const sep = t.includes("：") ? "：" : t.includes(":") ? ":" : null;
    if (!sep) return null;
    const i = t.indexOf(sep);
    return {
        key: t.slice(0, i).trim(),
        value: t.slice(i + 1).trim(),
    };
}

function renderSummaryCellContent(cell, key, value, readOnly) {
    const toggleOptions = SUMMARY_TOGGLE_OPTIONS[key];
    cell.innerHTML = "";
    cell.dataset.summaryKey = key;

    const textWrap = document.createElement("span");
    textWrap.className = "summary-field-text";

    const labelSpan = document.createElement("span");
    labelSpan.className = "summary-field-label";
    labelSpan.textContent = key;

    const sepSpan = document.createElement("span");
    sepSpan.className = "summary-field-sep";
    sepSpan.textContent = "：";

    const valueSpan = document.createElement("span");
    valueSpan.className = "summary-field-value";
    valueSpan.textContent = value || "";
    if (!readOnly && SUMMARY_DIRECT_EDIT_FIELDS.has(key)) {
        valueSpan.setAttribute("contenteditable", "true");
        valueSpan.classList.add("summary-field-value-editable");
    }

    textWrap.appendChild(labelSpan);
    textWrap.appendChild(sepSpan);
    textWrap.appendChild(valueSpan);
    cell.appendChild(textWrap);

    if (!readOnly && Array.isArray(toggleOptions)) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "summary-toggle-btn";
        btn.dataset.summaryKey = key;
        btn.textContent = "↻";
        btn.title = `切换${key}`;
        btn.setAttribute("aria-label", `切换${key}`);
        btn.addEventListener("click", (event) => {
            event.preventDefault();
            const currentValue = valueSpan.textContent || "";
            const idx = toggleOptions.indexOf(currentValue);
            const nextValue = toggleOptions[(idx + 1 + toggleOptions.length) % toggleOptions.length];
            valueSpan.textContent = nextValue;
            cell.classList.remove("md-cell-invalid");
        });
        cell.appendChild(btn);
    }
}

export function setupSummaryTableControls(ctx, readOnly) {
    const list = ctx.summaryTables?.length
        ? ctx.summaryTables
        : ctx.summaryTable
          ? [ctx.summaryTable]
          : [];
    for (const table of list) {
        table.querySelectorAll("td, th").forEach((cell) => {
            const pair = readSummaryCellPair(cell);
            if (!pair?.key) return;
            renderSummaryCellContent(cell, pair.key, pair.value, readOnly);
        });
    }
}

/**
 * 金加 CNC0 / CNC0 全檢：收集主数据表。
 * - 多段「摘要+主表」（S1,M1,S2,M2,…）：每张摘要后紧跟的一张非摘要表。
 * - 单摘要后连续多张主表（S1,M1,M2）：第一张摘要之后直到下一张摘要之前的所有非摘要表。
 */
function collectJinjiaCnc0MainTables(tables) {
    const summaryIdxs = [];
    for (let k = 0; k < tables.length; k++) {
        if (isSummaryTableRelaxed(tables[k])) summaryIdxs.push(k);
    }
    if (summaryIdxs.length >= 2) {
        const mains = [];
        for (const si of summaryIdxs) {
            if (si + 1 < tables.length && !isSummaryTableRelaxed(tables[si + 1])) {
                mains.push(tables[si + 1]);
            }
        }
        return mains;
    }
    const si = summaryIdxs[0];
    if (si === undefined) return [];
    const mains = [];
    let j = si + 1;
    while (j < tables.length && !isSummaryTableRelaxed(tables[j])) {
        mains.push(tables[j]);
        j += 1;
    }
    return mains;
}

/**
 * 金加 CNC0 且用户锁定第二段时：校验/可编辑范围只保留第一张摘要 + 第一张主表。
 * @param {Record<string, unknown>} ctx getValidationTableContext 未截断前的对象
 */
function applyCnc0SecondBlockLock(ctx) {
    if (!ctx || ctx.error || !state.cnc0SecondBlockLocked) return ctx;
    if (ctx.keyName !== "金加") return ctx;
    const procLock = normalizeProcessName(ctx.process || "");
    if (procLock !== "CNC0" && procLock !== "CNC0 全檢") return ctx;
    const mains = ctx.mainTables || [];
    if (mains.length <= 1) return ctx;
    const stList = ctx.summaryTables || [];
    const firstSummary = ctx.summaryTable && stList.includes(ctx.summaryTable) ? ctx.summaryTable : stList[0] || null;
    const newMains = mains[0] ? [mains[0]] : [];
    const newSummaryTables = firstSummary ? [firstSummary] : [];
    const newSummary = firstSummary ? parseSummaryTable(firstSummary) : ctx.summary;
    return {
        ...ctx,
        summaryTable: firstSummary ?? ctx.summaryTable,
        summaryTables: newSummaryTables,
        mainTable: newMains[0] ?? null,
        mainTables: newMains,
        summary: newSummary,
    };
}

/**
 * 定位主数据表 + 製程名（优先摘要单行表 + 下一张主表；金加 CNC0 支持多主表）。
 */
export function getValidationTableContext() {
    const wrap = getOcrResultTables();
    const meta = getOcrResultMeta();
    if (!wrap) {
        return {
            mainTable: null,
            mainTables: [],
            summaryTable: null,
            summaryTables: [],
            process: null,
            error: "表格容器不存在",
        };
    }
    const blob = `${meta?.innerText || ""}\n${wrap.innerText || ""}`;
    const tables = [...wrap.querySelectorAll("table")];
    const summaryTables = tables.filter(isSummaryTableRelaxed);

    for (let i = 0; i < tables.length; i++) {
        if (isSummaryTableRelaxed(tables[i]) && tables[i + 1]) {
            const summary = parseSummaryTable(tables[i]);
            let process = normalizeProcessName(summary["製程"] || "");
            if (!process) process = detectProcessFromText(tables[i].innerText);
            if (!process) process = detectProcessFromText(blob);
            const keyName = inferKeyFromProcess(process);
            const procNorm = normalizeProcessName(process);
            const mainTables =
                keyName === "金加" && (procNorm === "CNC0" || procNorm === "CNC0 全檢")
                    ? collectJinjiaCnc0MainTables(tables)
                    : [tables[i + 1]];
            const mainTable = mainTables[0] ?? null;
            return applyCnc0SecondBlockLock({
                summaryTable: tables[i],
                summaryTables,
                mainTable,
                mainTables,
                process,
                keyName,
                summary,
            });
        }
    }

    let process = detectProcessFromText(blob);
    const mainTable = tables[0] || null;
    if (!process && mainTable) process = detectProcessFromText(mainTable.innerText);
    const np = normalizeProcessName(process || "");
    return applyCnc0SecondBlockLock({
        summaryTable: null,
        summaryTables: [],
        mainTable,
        mainTables: mainTable ? [mainTable] : [],
        process: np,
        keyName: inferKeyFromProcess(process || ""),
        summary: {},
    });
}

/**
 * 与 extract_handwritten_data 一致：逻辑网格，cell 为覆盖该格的 td/th DOM。
 */
function buildGridDomRefs(table) {
    const rowEls = [...table.querySelectorAll("tr")];
    const numRows = rowEls.length;
    const grid = [];

    rowEls.forEach((tr, rowIdx) => {
        if (!grid[rowIdx]) grid[rowIdx] = [];
        const cells = [...tr.querySelectorAll("td, th")];
        let colIdx = 0;
        for (const cell of cells) {
            while (colIdx < grid[rowIdx].length && grid[rowIdx][colIdx] != null) {
                colIdx++;
            }
            const rowspan = parseInt(cell.getAttribute("rowspan"), 10) || 1;
            const colspan = parseInt(cell.getAttribute("colspan"), 10) || 1;
            const rEnd = Math.min(rowIdx + rowspan, numRows);
            for (let r = rowIdx; r < rEnd; r++) {
                if (!grid[r]) grid[r] = [];
                for (let c = colIdx; c < colIdx + colspan; c++) {
                    while (grid[r].length <= c) grid[r].push(null);
                    if (grid[r][c] == null) grid[r][c] = cell;
                }
            }
            colIdx += colspan;
        }
    });
    return grid;
}

function expandRuleCols(spec) {
    if (spec.colRange) {
        const [a, b] = spec.colRange;
        const cols = [];
        for (let c = a; c <= b; c++) cols.push(c);
        return cols;
    }
    const cl = spec.colList;
    if (Array.isArray(cl)) return cl;
    if (cl != null && typeof cl[Symbol.iterator] === "function") return [...cl];
    return [];
}

/** rowRange 仅写 [n] 时表示单行 n（与 [n, n] 等价） */
function specRowRangeEnds(spec) {
    const rr = spec.rowRange;
    const start = rr[0];
    const end = rr.length >= 2 ? rr[1] : rr[0];
    return [start, end];
}

function findVisualPositionByCell(table, targetCell) {
    if (!table || !targetCell) return null;
    const grid = buildGridDomRefs(table);
    for (let r = 0; r < grid.length; r++) {
        for (let c = 0; c < grid[r].length; c++) {
            if (grid[r][c] === targetCell) {
                return { row: r + 1, col: c + 1 };
            }
        }
    }
    return null;
}

function getMainRuleForCell(ctx, targetCell) {
    if (!ctx?.process || !targetCell) return null;
    const specs = MAIN_TABLE_RULES[ctx.process];
    if (!specs) return null;
    const mains = ctx.mainTables?.length ? ctx.mainTables : ctx.mainTable ? [ctx.mainTable] : [];
    for (const table of mains) {
        const pos = findVisualPositionByCell(table, targetCell);
        if (!pos) continue;
        for (const spec of specs) {
            const [startRow, endRow] = specRowRangeEnds(spec);
            if (pos.row < startRow || pos.row > endRow) continue;
            if (expandRuleCols(spec).includes(pos.col)) {
                return { spec, row: pos.row, col: pos.col };
            }
        }
    }
    return null;
}

function fillEmptyIntCellsWithZero(holder) {
    // 用户诉求：不再做任何“空数字格补 0”
    // （避免把 OCR 的空白值强行变成 0，提交后看板也能保持空值语义）
    return;
}

/** 鍛壓 row1 批次：提交入库前统一为「前四位 + 空格 + 第五位 + - + 末位」，如 03033-1 → 0303 3-1 */
function formatDuanyaBatchForSubmit(text) {
    const raw = String(text ?? "").trim();
    if (raw === "") return "";
    const compact = raw.replace(/\s/g, "");
    const m = compact.match(/^(\d{5})-(\d)$/);
    if (!m) return raw;
    const five = m[1];
    const tail = m[2];
    return `${five.slice(0, 4)} ${five.slice(4)}-${tail}`;
}

function normalizeDuanyaRow1BatchCells(holder) {
    const liveTablesWrap = getOcrResultTables();
    const liveCtx = getValidationTableContext();
    if (!holder || !liveTablesWrap || !liveCtx.mainTable) return;
    if (normalizeProcessName(liveCtx.process || "") !== "鍛壓") return;

    const liveTables = [...liveTablesWrap.querySelectorAll("table")];
    const mainIndex = liveTables.indexOf(liveCtx.mainTable);
    if (mainIndex < 0) return;

    const cloneTables = [...holder.querySelectorAll("table")];
    const cloneMainTable = cloneTables[mainIndex];
    if (!cloneMainTable) return;

    const cloneGrid = buildGridDomRefs(cloneMainTable);
    const cols = [3, 5, 7, 9];
    const r = 0;
    if (r >= cloneGrid.length) return;
    for (const visualCol of cols) {
        const cell = cloneGrid[r]?.[visualCol - 1];
        if (!cell || cell.tagName?.toLowerCase() === "th") continue;
        cell.textContent = formatDuanyaBatchForSubmit(cell.innerText ?? "");
    }
}

function clearOcrCellInvalidMarks() {
    const wrap = getOcrResultTables();
    if (!wrap) return;
    wrap.querySelectorAll("td.md-cell-invalid, th.md-cell-invalid").forEach((cell) => {
        cell.classList.remove("md-cell-invalid");
    });
}

/**
 * @returns {{ ok: boolean, errorCount: number, message: string | null, focusTarget: HTMLElement | null }}
 */
export function runBoardValidationBeforeSubmit() {
    clearOcrCellInvalidMarks();
    const ctx = getValidationTableContext();

    const summaryResult = validateSummaryTable(ctx);
    const mainResult = validateMainTable(ctx);
    const totalErrors = summaryResult.errorCount + mainResult.errorCount;
    const firstMessage = summaryResult.message || mainResult.message;

    return {
        ok: summaryResult.ok && mainResult.ok,
        errorCount: totalErrors,
        message:
            firstMessage ||
            (totalErrors > 0 ? `校验未通过：有 ${totalErrors} 个单元格格式不符，已标红。` : null),
        focusTarget:
            summaryResult.focusTarget ||
            mainResult.focusTarget ||
            ctx.summaryTables?.[0] ||
            ctx.summaryTable ||
            ctx.mainTable ||
            ctx.mainTables?.[0],
    };
}

/** 校验单张摘要表（标红单元格） */
function validateOneSummaryTable(summaryTable) {
    const firstCell = summaryTable.querySelector("td, th");
    const { entries, malformedCells } = parseSummaryTableEntries(summaryTable);
    const invalidCells = new Set();
    const missingFields = [];

    malformedCells.forEach((cell) => invalidCells.add(cell));

    const markInvalid = (cell) => {
        if (cell) invalidCells.add(cell);
    };

    const getValue = (key) => (entries[key]?.value || "").trim();

    for (const key of SUMMARY_REQUIRED_FIELDS) {
        const entry = entries[key];
        if (!entry || !entry.value.trim()) {
            missingFields.push(key);
            markInvalid(entry?.cell || firstCell);
        }
    }

    const dateValue = getValue("生產日期");
    if (dateValue && !/^\d{4}-\d{2}-\d{2}$/.test(dateValue)) {
        markInvalid(entries["生產日期"]?.cell);
    }

    const shiftValue = getValue("班別");
    if (shiftValue && !SUMMARY_ALLOWED_SHIFTS.has(shiftValue)) {
        markInvalid(entries["班別"]?.cell);
    }

    const productValue = getValue("品名");
    if (productValue && !SUMMARY_ALLOWED_PRODUCTS.has(productValue)) {
        markInvalid(entries["品名"]?.cell);
    }

    const processValue = normalizeProcessName(getValue("製程"));
    const keyName = inferKeyFromProcess(processValue);
    if (!processValue || !keyName) {
        markInvalid(entries["製程"]?.cell || firstCell);
    } else if (
        (keyName === "沖壓" && !SUMMARY_ALLOWED_CHONGYA_PROCESSES.has(processValue)) ||
        (keyName === "金加" && !SUMMARY_ALLOWED_JINJIA_PROCESSES.has(processValue))
    ) {
        markInvalid(entries["製程"]?.cell || firstCell);
    }

    const inspectionEntry = entries["抽檢位置"];
    const inspectionValue = (inspectionEntry?.value || "").trim();
    if (keyName === "金加" && processValue !== "CNC0 全檢") {
        if (!inspectionValue || !SUMMARY_ALLOWED_INSPECTION_LOCATIONS.has(inspectionValue)) {
            markInvalid(inspectionEntry?.cell || firstCell);
        }
    } else if (inspectionValue && !SUMMARY_ALLOWED_INSPECTION_LOCATIONS.has(inspectionValue)) {
        markInvalid(inspectionEntry?.cell);
    }

    invalidCells.forEach((cell) => cell.classList.add("md-cell-invalid"));
    const errorCount = invalidCells.size;
    if (errorCount === 0) {
        return {
            ok: true,
            errorCount: 0,
            message: null,
            focusTarget: null,
            malformedCells,
            missingFields,
        };
    }

    const malformedHint = malformedCells.length > 0 ? "摘要表单元格需保持“字段：值”格式。" : "";
    const missingHint = missingFields.length > 0 ? `缺少或为空：${missingFields.join("、")}。` : "";
    return {
        ok: false,
        errorCount,
        message: `摘要表校验未通过。${missingHint}${malformedHint}`.trim(),
        focusTarget: invalidCells.values().next().value || summaryTable,
        malformedCells,
        missingFields,
    };
}

function validateSummaryTable(ctx) {
    const tableList = ctx.summaryTables?.length
        ? ctx.summaryTables
        : ctx.summaryTable
          ? [ctx.summaryTable]
          : [];
    const fallbackMain = ctx.mainTable || ctx.mainTables?.[0] || null;
    if (!tableList.length) {
        return {
            ok: false,
            errorCount: 0,
            message: "未找到摘要表，无法提交校验。",
            focusTarget: fallbackMain,
        };
    }

    let totalErrors = 0;
    let firstMsg = null;
    let firstFocus = null;
    for (const st of tableList) {
        const r = validateOneSummaryTable(st);
        totalErrors += r.errorCount;
        if (!firstMsg && r.message) firstMsg = r.message;
        if (!firstFocus && r.focusTarget) firstFocus = r.focusTarget;
    }
    if (totalErrors === 0) {
        return {
            ok: true,
            errorCount: 0,
            message: null,
            focusTarget: null,
        };
    }
    return {
        ok: false,
        errorCount: totalErrors,
        message: firstMsg || "摘要表校验未通过。",
        focusTarget: firstFocus || tableList[0],
    };
}

/**
 * 提交时按 MAIN_TABLE_RULES 校验可编辑格（不修改 row/col 配置）；标红并阻止提交。
 * @returns {{ ok: boolean, errorCount: number, message: string | null, focusTarget: HTMLElement | null }}
 */
function validateMainTable(ctx) {
    const mains = ctx.mainTables?.length ? ctx.mainTables : ctx.mainTable ? [ctx.mainTable] : [];
    if (!mains.length) {
        return {
            ok: false,
            errorCount: 0,
            message: "未找到主数据表，无法校验。",
            focusTarget: null,
        };
    }

    const process = normalizeProcessName(ctx.process || ctx.summary?.["製程"] || "");
    if (!process || !MAIN_TABLE_EDITABLE_SPECS[process]) {
        return {
            ok: false,
            errorCount: 0,
            message: "无法识别製程，主表规则未匹配。",
            focusTarget: ctx.summaryTables?.[0] || ctx.summaryTable || mains[0],
        };
    }

    const editableCells = getMainTableEditableCellSet(ctx);
    const invalidCells = new Set();
    let firstFocus = null;
    let firstMessage = null;

    for (const cell of editableCells) {
        const hit = getMainRuleForCell(ctx, cell);
        if (!hit?.spec?.validate) continue;
        const text = cell.innerText ?? "";
        if (!hit.spec.validate(text)) {
            invalidCells.add(cell);
            cell.classList.add("md-cell-invalid");
            if (!firstFocus) firstFocus = cell;
            if (!firstMessage) {
                firstMessage = `主表校验未通过：${hit.spec.label || "格式不符"}。`;
            }
        }
    }

    if (invalidCells.size === 0) {
        return {
            ok: true,
            errorCount: 0,
            message: null,
            focusTarget: null,
        };
    }
    return {
        ok: false,
        errorCount: invalidCells.size,
        message:
            firstMessage ||
            `主表校验未通过：有 ${invalidCells.size} 个单元格格式不符，已标红。`,
        focusTarget: firstFocus || mains[0],
    };
}
/** 拼回与后端一致的顺序：摘要 HTML + 表格区 innerHTML（无额外包装 div）。 */
export function collectVerifiedMarkdown() {
    const meta = getOcrResultMeta();
    const tables = getOcrResultTables();
    const holder = document.createElement("div");
    holder.innerHTML =
        (meta ? meta.innerHTML : "") +
        (tables ? tables.innerHTML : "");
    if (state.cnc0SecondBlockLocked) {
        holder.querySelectorAll(".cnc0-second-block").forEach((el) => el.remove());
    }
    fillEmptyIntCellsWithZero(holder);
    normalizeDuanyaRow1BatchCells(holder);
    holder.querySelectorAll(".empty-tip").forEach((el) => el.remove());
    holder.querySelectorAll("[contenteditable]").forEach((el) => el.removeAttribute("contenteditable"));
    holder.querySelectorAll(".md-cell-editable").forEach((el) => el.classList.remove("md-cell-editable"));
    holder.querySelectorAll(".summary-toggle-btn").forEach((el) => el.remove());
    return sanitizeBasicHtml(holder.innerHTML);
}
