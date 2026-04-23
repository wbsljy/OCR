/**
 * OCR 右侧 HTML 片段处理：消毒、转义、按 table 切段、摘要区格式化、表格区提示文案。
 * 依赖：getOcrResultTables（ocr-dom）。
 */

import { getOcrResultTables } from "./ocr-dom.js";

/**
 * 去除危险标签（script/iframe 等），保留其余 HTML 供 innerHTML 使用。
 * @param {unknown} value
 * @returns {string}
 */
export function sanitizeBasicHtml(value) {
    const template = document.createElement("template");
    template.innerHTML = value == null ? "" : String(value);
    template.content.querySelectorAll("script,iframe,object,embed").forEach((el) => el.remove());
    return template.innerHTML;
}

/**
 * 纯文本转义，用于无表格时的降级展示。
 * @param {string} value
 * @returns {string}
 */
export function escapeHtml(value) {
    return value
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

/**
 * 按顺序切分原文中的 HTML 片段与 &lt;table&gt;…&lt;/table&gt;，保留多表之间的正文顺序。
 * @param {string} [raw]
 * @returns {{ type: "html"|"table", html: string }[]}
 */
export function extractSegmentsFromRawString(raw) {
    const s = raw || "";
    const re = /<table\b[\s\S]*?<\/table>/gi;
    const segments = [];
    let last = 0;
    let m = re.exec(s);
    while (m !== null) {
        if (m.index > last) {
            segments.push({ type: "html", html: s.slice(last, m.index) });
        }
        segments.push({ type: "table", html: m[0] });
        last = re.lastIndex;
        m = re.exec(s);
    }
    if (last < s.length) {
        segments.push({ type: "html", html: s.slice(last) });
    }
    if (segments.length === 0 && s.trim()) {
        segments.push({ type: "html", html: s });
    }
    return segments;
}

/**
 * 将片段中独立成行的 Markdown 风格 `# 标题` 转为 h1（首行、`<br>` 后、或 `<p>#` 段落）。
 * 用于摘要首段及多表之间的小标题（如金加 CNC0 第二段「# 品質明細表」）。
 * @param {string} fragment
 * @returns {string}
 */
export function formatOcrHtmlHeadings(fragment) {
    let html = sanitizeBasicHtml((fragment || "").trim());
    if (!html) return "";
    // 整段包在 <p># xxx</p> 内时先拆成标题
    html = html.replace(/<p[^>]*>\s*#\s+([^<]+)<\/p>/gi, '<h1 class="ocr-meta-title">$1</h1>');
    // 行首或 <br> 后的 # 标题（可重复匹配多段）；允许后接 <table> 等同一段（lookahead 含 `<`）
    html = html.replace(/(^|<br\s*\/?>)\s*#\s+([^<\n]+?)(?=<br\s*\/?>|<|$)/gi, (_, pre, title) => {
        return `${pre}<h1 class="ocr-meta-title">${title.trim()}</h1>`;
    });
    return html;
}

/**
 * 摘要区等与 {@link formatOcrHtmlHeadings} 相同（兼容旧名）。
 * @param {string} fragment
 * @returns {string}
 */
export function formatMetaPrefixHtml(fragment) {
    return formatOcrHtmlHeadings(fragment);
}

/**
 * 将 HTML 字符串中的第一个 table 解析后追加到容器。
 * @param {HTMLElement | null} container
 * @param {string} tableHtml
 */
export function appendTableFromHtml(container, tableHtml) {
    if (!container) return;
    const tpl = document.createElement("template");
    tpl.innerHTML = sanitizeBasicHtml(tableHtml);
    const tbl = tpl.content.querySelector("table");
    if (tbl) {
        container.appendChild(tbl);
    }
}

/**
 * 仅设置表格区域占位/提示（innerHTML）。
 * @param {string} messageHtml
 */
export function setOcrTablesMessage(messageHtml) {
    const tables = getOcrResultTables();
    if (!tables) return;
    tables.innerHTML = messageHtml;
}
