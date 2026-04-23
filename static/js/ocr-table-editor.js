/**
 * OCR 右侧「识别表格」区：渲染 HTML+表格、摘要控件、主表可编辑格、校验提示事件。
 * 依赖：ocr-dom、ocr-utils-html、ocr-board-validation（上下文与制程规则）。
 */

import { getOcrResultMeta, getOcrResultTables } from "./ocr-dom.js";
import {
    appendTableFromHtml,
    escapeHtml,
    extractSegmentsFromRawString,
    formatMetaPrefixHtml,
    formatOcrHtmlHeadings,
    sanitizeBasicHtml,
    setOcrTablesMessage,
} from "./ocr-utils-html.js";
import {
    MAIN_TABLE_EDITABLE_SPECS,
    getMainTableEditableCellSet,
    getValidationTableContext,
    normalizeProcessName,
    setupSummaryTableControls,
} from "./ocr-board-validation.js";
import { state } from "./ocr-state.js";

/**
 * 绑定表格区：输入/切换按钮时清除单元格标红（避免重复绑定）。
 * @param {HTMLElement | null} container
 */
export function bindOcrTablesValidationHints(container) {
    if (!container || container.dataset.validationHintsBound === "1") return;
    container.dataset.validationHintsBound = "1";
    container.addEventListener("input", (e) => {
        const td = e.target.closest?.("td");
        if (!td) return;
        td.classList.remove("md-cell-invalid");
    });
    container.addEventListener("click", (e) => {
        const btn = e.target.closest?.(".summary-toggle-btn");
        if (!btn) return;
        const td = btn.closest("td, th");
        if (td) td.classList.remove("md-cell-invalid");
    });
}

/**
 * 按製程规则为主表 td 设置 contenteditable（只读时全部清除）。
 * @param {HTMLElement | null} container
 * @param {boolean} readOnly
 */
export function makeTableCellsEditable(container, readOnly) {
    if (!container) return;

    container.querySelectorAll("table td").forEach((td) => {
        td.removeAttribute("contenteditable");
        td.classList.remove("md-cell-editable");
    });

    if (readOnly) return;

    const ctx = getValidationTableContext();
    const mains = ctx.mainTables?.length ? ctx.mainTables : ctx.mainTable ? [ctx.mainTable] : [];
    if (!mains.length || !ctx.process) {
        console.warn("makeTableCellsEditable: 无法获取上下文", ctx);
        return;
    }

    if (!MAIN_TABLE_EDITABLE_SPECS[normalizeProcessName(ctx.process)]) {
        console.warn("没有找到可编辑配置 for process:", ctx.process);
        return;
    }

    const editableCells = getMainTableEditableCellSet(ctx);

    editableCells.forEach((td) => {
        td.setAttribute("contenteditable", "true");
        td.classList.add("md-cell-editable");
    });
}

/**
 * 右侧识别结果：仅摘要区 + 内嵌表格（可编辑 td），不再整页 Markdown 预览。
 * @param {unknown} raw 当前页 markdown 字符串或兼容对象
 */
export function renderOcrTableEditor(raw) {
    const meta = getOcrResultMeta();
    const tables = getOcrResultTables();
    if (!meta || !tables) return;
    if (!raw || !String(raw).trim()) {
        meta.innerHTML = "";
        setOcrTablesMessage('<p class="empty-tip">本页无内容</p>');
        return;
    }

    const segments = extractSegmentsFromRawString(String(raw));
    const hasTable = segments.some((s) => s.type === "table");

    meta.innerHTML = "";
    tables.innerHTML = "";

    let i = 0;
    if (segments[0]?.type === "html") {
        meta.innerHTML = formatMetaPrefixHtml(segments[0].html);
        i = 1;
    }

    if (!hasTable) {
        if (!meta.innerHTML.trim()) {
            const joinedHtml = segments
                .filter((s) => s.type === "html")
                .map((s) => s.html)
                .join("");
            meta.innerHTML = formatMetaPrefixHtml(
                joinedHtml || escapeHtml(String(raw)).replace(/\n/g, "<br>")
            );
        }
        setOcrTablesMessage('<p class="empty-tip">未识别到表格，请检查 OCR 原文</p>');
        return;
    }

    let appended = false;
    for (; i < segments.length; i++) {
        const seg = segments[i];
        if (seg.type === "table") {
            appendTableFromHtml(tables, seg.html);
            appended = true;
        } else if (seg.html.trim()) {
            const chunk = document.createElement("div");
            chunk.className = "ocr-inter-html";
            chunk.innerHTML = formatOcrHtmlHeadings(seg.html);
            tables.appendChild(chunk);
        }
    }

    if (!appended && tables.children.length === 0) {
        setOcrTablesMessage('<p class="empty-tip">未解析出表格结构</p>');
    }

    setupSummaryTableControls(getValidationTableContext(), false);
    makeTableCellsEditable(tables, false);
    bindOcrTablesValidationHints(tables);
    setupCnc0SecondBlockUi(tables);
}

/**
 * 金加 CNC0 且存在第二个「# 品質明細表」时：将第二段包入 .cnc0-second-block，标题旁加锁定开关。
 * 锁定时校验/可编辑仅第一段（见 getValidationTableContext）；提交时 collectVerifiedMarkdown 去掉第二段。
 * @param {HTMLElement} tables `#ocr-result-tables`
 */
function setupCnc0SecondBlockUi(tables) {
    if (!tables || tables.querySelector(".cnc0-second-block")) return;

    const prevLocked = state.cnc0SecondBlockLocked;
    state.cnc0SecondBlockLocked = false;
    const ctx = getValidationTableContext();
    state.cnc0SecondBlockLocked = prevLocked;

    const proc = normalizeProcessName(ctx.process || "");
    const isJinjiaCnc0Lock =
        ctx.keyName === "金加" && (proc === "CNC0" || proc === "CNC0 全檢");
    if (!isJinjiaCnc0Lock) return;

    const mains = ctx.mainTables?.length ? ctx.mainTables : [];
    if (mains.length < 2) return;

    const stList = ctx.summaryTables?.length ? ctx.summaryTables : [];
    const secondSummary = stList.length >= 2 ? stList[1] : null;
    const children = [...tables.children];
    let startIdx = -1;

    if (secondSummary) {
        for (let i = 0; i < children.length; i++) {
            if (children[i].contains(secondSummary)) {
                startIdx = i;
                if (
                    i > 0 &&
                    children[i - 1].classList?.contains("ocr-inter-html") &&
                    /品質/.test(children[i - 1].textContent || "")
                ) {
                    startIdx = i - 1;
                }
                break;
            }
        }
    }
    if (startIdx < 0) {
        const h1All = [...tables.querySelectorAll("h1.ocr-meta-title")];
        let anchor = h1All.length >= 2 ? h1All[1] : h1All.length === 1 ? h1All[0] : null;
        if (anchor && /品質/.test(anchor.textContent || "")) {
            for (let i = 0; i < children.length; i++) {
                if (children[i].contains(anchor)) {
                    startIdx = i;
                    break;
                }
            }
        }
    }
    if (startIdx < 0) return;

    const block = document.createElement("div");
    block.className = "cnc0-second-block";
    block.dataset.cnc0Second = "1";
    const toMove = children.slice(startIdx);
    toMove.forEach((el) => block.appendChild(el));
    tables.appendChild(block);

    const firstChild = block.firstElementChild;
    let secondTitle = null;
    if (firstChild?.classList?.contains("ocr-inter-html")) {
        secondTitle = firstChild.querySelector("h1.ocr-meta-title");
        if (secondTitle && !/品質/.test(secondTitle.textContent || "")) secondTitle = null;
    }

    const row = document.createElement("div");
    row.className = "cnc0-second-title-row";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn-cnc0-second-lock";

    if (secondTitle && secondTitle.parentNode) {
        secondTitle.parentNode.insertBefore(row, secondTitle);
        row.appendChild(secondTitle);
        row.appendChild(btn);
    } else {
        block.insertBefore(row, block.firstChild);
        row.appendChild(btn);
    }

    const sync = () => {
        if (state.cnc0SecondBlockLocked) {
            block.classList.add("is-locked");
            btn.setAttribute("aria-pressed", "true");
            btn.textContent = "恢复第二段";
        } else {
            block.classList.remove("is-locked");
            btn.setAttribute("aria-pressed", "false");
            btn.textContent = "仅保留第一段";
        }
        setupSummaryTableControls(getValidationTableContext(), false);
        makeTableCellsEditable(tables, false);
    };

    btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        state.cnc0SecondBlockLocked = !state.cnc0SecondBlockLocked;
        sync();
    });

    sync();
}
