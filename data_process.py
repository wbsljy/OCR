import sys
import json
import re
from html import escape

import requests
from bs4 import BeautifulSoup

#region ==================== 配置部分 ====================
API_KEY = "sk-f45d900830544c33980b5b4ac1dbdeb4"
BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-chat"

SYSTEM_PROMPT_1 = """你是一個信息提取助手。下面是從 OCR 識別得到的 Markdown 文本，其中可能包含生產記錄信息。請從中提取以下四個字段，並以嚴格的 JSON 格式輸出，不要添加任何解釋或額外文字。

**字段定義**：
- `生產日期`：格式爲 yyyy-mm-dd（例如 2026-03-24）。如果文本中沒有明確日期，嘗試從上下文推斷；若完全無法確定，輸出 null。
- `班別`：只能是以下兩種之一："白班" 或 "晚班"。如果文本中沒有明確，輸出 null。
- `品名`：只能是 "Y20 Housing" 或 "X3784 Housing"。如果文本中出現類似但拼寫略有差異的名稱，請根據最接近的匹配輸出標準名稱；若無法識別，輸出 null。
- `製程`：只能是 "時效"、"鍛壓"、"固熔" 之一。若文本中出現其他工藝名稱，請根據含義匹配到最接近的類別；若無法匹配，輸出 null。

**輸出格式（中文為繁體）**（只輸出 JSON）：
{
 "生產日期": "yyyy-mm-dd",
 "班別": "白班" | "晚班" | null,
 "品名": "Y20 Housing" | "X3784 Housing" | null,
 "製程": "時效" | "鍛壓" | "固熔" | null
}"""

SYSTEM_PROMPT_2 = """你是一個信息提取助手。下面是從 OCR 識別得到的 Markdown 文本，其中可能包含生產質量抽檢記錄。請從中提取以下五個字段，並以嚴格的 JSON 格式輸出，不要添加任何解釋或額外文字。

**字段定義**：
- `生產日期`：格式爲 yyyy-mm-dd（例如 2026-03-24）。如果文本中沒有明確日期，嘗試從上下文推斷；若完全無法確定，輸出 null。
- `班別`：只能是以下兩種之一："白班" 或 "晚班"。如果文本中沒有明確，輸出 null。
- `品名`：只能是 "Y20 Housing" 或 "X3784 Housing"。如果文本中出現類似但拼寫略有差異的名稱，請根據最接近的匹配輸出標準名稱；若無法識別，輸出 null。
- `製程`：只能是 "CNC0" 或 "CNC0 全檢" 之一。如果文本中出現其他夾位描述，請匹配到最接近的類別；若無法匹配，輸出 null。
- `抽檢位置`：只能是 "製程抽檢" 或 "入庫抽檢" 之一。若文本中出現其他位置描述，請根據含義匹配到最接近的類別；若無法匹配，輸出 null。
（注意：当製程为CNC0 全檢时，没有抽檢位置字段，无需提取和输出）
**輸出格式（中文為繁體）**（只輸出 JSON）：
{
 "生產日期": "yyyy-mm-dd",
 "班別": "白班" | "晚班" | null,
 "品名": "Y20 Housing" | "X3784 Housing" | null,
 "製程": "CNC0" | "CNC0 全檢" | null,
 "抽檢位置": "製程抽檢" | "入庫抽檢" | null 
}
"""
SYSTEM_PROMPT_鍛壓 = """你是一個信息提取助手。下面是從 OCR 識別得到的 Markdown 文本，其中可能包含生產記錄信息。請從中提取以下四個字段，並以嚴格的 JSON 格式輸出，不要添加任何解釋或額外文字。

**字段定義**：
- `生產日期`：格式爲 yyyy-mm-dd（例如 2026-03-24）。如果文本中沒有明確日期，嘗試從上下文推斷；若完全無法確定，輸出 null。
- `班別`：只能是以下兩種之一："白班" 或 "晚班"。如果文本中沒有明確，輸出 null。
- `品名`：只能是 "Y20 Housing" 或 "X3784 Housing"。如果文本中出現類似但拼寫略有差異的名稱，請根據最接近的匹配輸出標準名稱；若無法識別，輸出 null。
- `製程`：只能是 "時效"、"鍛壓"、"固熔" 之一。若文本中出現其他工藝名稱，請根據含義匹配到最接近的類別；若無法匹配，輸出 null。
- `页码`: 要么第1页，要么第2页，无法判断则填"1"
**輸出格式（中文為繁體）**（只輸出 JSON）：
{
 "生產日期": "yyyy-mm-dd",
 "班別": "白班" | "晚班" | null,
 "品名": "Y20 Housing" | "X3784 Housing" | null,
 "製程": "時效" | "鍛壓" | "固熔" | null,
 "页码": "1" | "2" ,
}"""
#endregion


def _chat_completions_http_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def _message_content_from_chat_response(resp) -> str | None:
    if isinstance(resp, dict):
        choices = resp.get("choices") or []
        if not choices:
            return None
        msg = choices[0].get("message") or {}
        return msg.get("content")
    try:
        return resp.choices[0].message.content
    except (AttributeError, IndexError, KeyError, TypeError):
        return None


def _chat_complete(system_prompt: str, user_input: str) -> str | None:
    """兼容 openai>=1 客户端、0.x 的 ChatCompletion，以及仅有旧版 openai 时走 HTTP。"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_input},
    ]
    err_parts: list[str] = []

    try:
        from openai import OpenAI

        client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.1,
        )
        text = _message_content_from_chat_response(response)
        if text is not None:
            return text
        err_parts.append("OpenAI 客户端返回空 content")
    except ImportError:
        pass
    except Exception as e:
        err_parts.append(f"openai.OpenAI: {e}")

    try:
        import openai as openai_legacy

        if getattr(openai_legacy, "ChatCompletion", None):
            openai_legacy.api_key = API_KEY
            base = BASE_URL.rstrip("/")
            openai_legacy.api_base = base if base.endswith("/v1") else f"{base}/v1"
            resp = openai_legacy.ChatCompletion.create(
                model=MODEL,
                messages=messages,
                temperature=0.1,
            )
            text = _message_content_from_chat_response(resp)
            if text is not None:
                return text
            err_parts.append("ChatCompletion 返回空 content")
    except Exception as e:
        err_parts.append(f"ChatCompletion.create: {e}")

    try:
        url = _chat_completions_http_url(BASE_URL)
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": MODEL, "messages": messages, "temperature": 0.1},
            timeout=120,
        )
        r.raise_for_status()
        text = _message_content_from_chat_response(r.json())
        if text is not None:
            return text
        err_parts.append(f"HTTP 响应无可用 content: {r.text[:500]!r}")
    except Exception as e:
        err_parts.append(f"HTTP chat/completions: {e}")

    for line in err_parts:
        print(line, file=sys.stderr)
    return None


# ==================== 封装函数 ====================
def extract_info(key, user_input):
    """
    根据 key 选择提示词，调用大模型提取信息，返回 JSON 字典。
    
    Args:
        key (str): 表格类型，可选 "沖壓" 或 "金加"
        user_input (str): OCR 识别出的 Markdown 文本
    
    Returns:
        dict: 提取出的信息字典，失败时返回 None
    """
    # 1. 选择系统提示词：冲压默认 SYSTEM_PROMPT_1（时效/固熔）；仅製程为鍛壓时再走 SYSTEM_PROMPT_鍛壓 取页码
    if key == "沖壓":
        system_prompt = SYSTEM_PROMPT_1
    elif key == "金加":
        system_prompt = SYSTEM_PROMPT_2
    else:
        print(f"错误：未知的 key 值 '{key}'，仅支持 '沖壓' 或 '金加'。", file=sys.stderr)
        return None

    try:
        result_text = _chat_complete(system_prompt, user_input)
        if not result_text:
            return None

        # 尝试解析 JSON
        try:
            result_json = json.loads(result_text)
            if key == "金加" and not result_json.get("製程"):
                result_json["製程"] = "CNC0"
            if key == "金加" and result_json.get("製程") == "CNC0 全檢":
                result_json.pop("抽檢位置", None)
            if key == "沖壓" and result_json.get("製程") == "鍛壓":
                text_page = _chat_complete(SYSTEM_PROMPT_鍛壓, user_input)
                if text_page:
                    try:
                        page_json = json.loads(text_page)
                        page_val = page_json.get("页码") or page_json.get("頁碼")
                        if page_val is not None and str(page_val).strip():
                            result_json["页码"] = str(page_val).strip()
                        else:
                            result_json["页码"] = "1"
                    except json.JSONDecodeError:
                        result_json["页码"] = "1"
                else:
                    result_json["页码"] = "1"
            return result_json
        except json.JSONDecodeError as e:
            print(f"模型返回内容不是有效 JSON：{result_text}", file=sys.stderr)
            print(f"JSON 解析错误：{e}", file=sys.stderr)
            return None
    
    except Exception as e:
        print(f"API 调用失败: {e}", file=sys.stderr)
        return None

def extract_single_table(markdown_text: str) -> dict:
    """
    提取Markdown文本中唯一的表格内容及其上下文
    
    Args:
        markdown_text: 包含Markdown的字符串
        context_chars: 前后保留的字符数
        
    Returns:
        包含表格内容和上下文的字典
    """
    # 查找<table>开始位置
    start_pos = markdown_text.find('<table>')
    
    # 查找</table>结束位置
    end_pos = markdown_text.find('</table>')
    
    # 包含结束标签
    end_pos += len('</table>')
    
    # 提取内容
    table_content = markdown_text[start_pos:end_pos]
    before_context = markdown_text[0:start_pos]
    after_context = markdown_text[end_pos:-1]

    return {
        'table': table_content,
        'before': before_context,
        'after': after_context
    }

def clean_table_rows(html_content: str) -> str:
    """
    清理 HTML 表格中的多余空行
    
    Args:
        html_content: 包含 HTML 表格的字符串
        
    Returns:
        清理后的 HTML 字符串
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 查找所有表格
    tables = soup.find_all('table')
    
    for table in tables:
        rows = table.find_all('tr')
        
        # 统计实际有内容的行数（从下往上找最后一行有数据的行）
        last_valid_row_index = 0
        for i, row in enumerate(rows):
            cells = row.find_all(['td', 'th'])
            # 检查这一行是否有非空内容
            has_content = any(cell.get_text(strip=True) for cell in cells)
            if has_content:
                last_valid_row_index = i
        
        # 移除最后的有效行之后的所有空行
        rows_to_remove = []
        for i in range(last_valid_row_index + 1, len(rows)):
            rows_to_remove.append(rows[i])
        
        for row in rows_to_remove:
            row.decompose()
        
        # 更新 rowspan 属性，确保不超过实际行数
        actual_row_count = last_valid_row_index + 1
        all_cells = table.find_all(['td', 'th'])
        
        for cell in all_cells:
            if cell.has_attr('rowspan'):
                rowspan_val = int(cell['rowspan'])
                # 如果 rowspan 超过实际行数，调整它
                if rowspan_val > actual_row_count:
                    cell['rowspan'] = str(actual_row_count)
    
    return str(soup)

def default_processor(value: str) -> str:
    """只保留数字，移除其他字符。"""
    return re.sub(r'[^0-9]', '', value)


def dy_processor(row: int, value: str) -> str:
    """鍛壓：第 1 行批次号只保留数字与减号；第 2 行线别提取前两个数段；其余同 default。"""
    if row == 1:
        value = re.sub(r'[^0-9\-]', '', value)          # 移除非数字和非短横线
        if re.match(r'^\d{5}-\d$', value):              # 匹配 5位数字-1位数字
            value = f"{value[:4]} {value[4]}-{value[6]}" # 重组：前4位 + 空格 + 第5位 + 短横 + 最后1位
        return value
    if row == 2:
        nums = re.findall(r'\d+(?:\.\d+)?', value)
        if len(nums) >= 2:
            return f"{nums[0]}線{nums[1]}模"
        else:
            return " 線 模" 
    return default_processor(value)


def gurong_line_processor(value: str) -> str:
    """固熔第一行線別：仅保留 A–Z、a–z 与「線」。"""
    return re.sub(r"[^A-Za-z線]", "", (value or "").strip())

def extract_handwritten_data(table_html: str, key: str, header_info: dict) -> list:
    """
    根据配置提取表格中的手写数据
    
    Args:
        table_html: HTML 表格内容
        key: 表格类型，"沖壓" 或 "金加"
        header_info: 表头提取的信息字典
        
    Returns:
        包含 (row, col, value) 的列表
    """
    soup = BeautifulSoup(table_html, 'html.parser')
    table = soup.find('table')
    
    if not table:
        print("错误：未找到表格", file=sys.stderr)
        return []
    
    rows = table.find_all('tr')
    
    # 构建完整的表格矩阵（处理 rowspan 和 colspan）
    grid = []
    for row_idx, row in enumerate(rows):
        cells = row.find_all(['td', 'th'])
        if len(grid) <= row_idx:
            grid.append([])
        
        col_idx = 0
        for cell in cells:
            # 找到下一个可用的列位置
            while col_idx < len(grid[row_idx]) and grid[row_idx][col_idx] is not None:
                col_idx += 1
            
            # 获取 rowspan 和 colspan
            rowspan = int(cell.get('rowspan', 1))
            colspan = int(cell.get('colspan', 1))
            cell_text = cell.get_text(strip=True)
            
            # 填充网格
            for r in range(row_idx, min(row_idx + rowspan, len(rows))):
                if len(grid) <= r:
                    grid.append([])
                for c in range(col_idx, col_idx + colspan):
                    while len(grid[r]) <= c:
                        grid[r].append(None)
                    if r == row_idx and c == col_idx:
                        grid[r][c] = cell_text
                    elif grid[r][c] is None:
                        grid[r][c] = cell_text  # rowspan/colspan 的延续单元格
            
            col_idx += colspan
    
    # 提取规则配置
    extraction_rules = get_extraction_rules(key, header_info)
    
    # 根据规则提取数据
    results = []
    for rule in extraction_rules:
        start_row, end_row = rule['row_range']
        if 'col_list' in rule:
            target_cols = rule['col_list']
        else:
            start_col, end_col = rule['col_range']
            target_cols = list(range(start_col, end_col + 1))
        
        proc_fn = rule.get('processor', default_processor)
        for r in range(start_row - 1, min(end_row, len(grid))):  # 转换为 0-based 索引
            if len(grid[r]) <= 0:
                continue
            for visual_col in target_cols:
                c = visual_col - 1
                if c >= len(grid[r]):
                    continue
                value = grid[r][c] if c < len(grid[r]) else None
                if not value or not str(value).strip():
                    continue
                raw_s = str(value).strip()
                row_1based = r + 1
                if proc_fn is dy_processor:
                    normalized = proc_fn(row_1based, raw_s)
                else:
                    normalized = proc_fn(raw_s)
                if normalized and str(normalized).strip():
                    results.append({
                        'row': row_1based,
                        'col': c + 1,
                        'value': normalized
                    })
    
    return results

def get_extraction_rules(key: str, header_info: dict) -> list:
    """
    根据 key 和表头信息获取提取规则
    
    Args:
        key: 表格类型，"沖壓" 或 "金加"
        header_info: 表头提取的信息字典
        
    Returns:
        提取规则列表，每个规则包含 row_range 和 col_range/col_list
    """
    rules = []
    
    if key == "沖壓":
        process = header_info.get('製程')
        
        if process == "鍛壓":
            # 按视觉列抓：
            # row 1-2 的批次/线别位于每组合并单元格左侧锚点列 3/5/7/9
            rules.append({'row_range': (1, 2), 'col_list': [3, 5, 7, 9], 'processor': dy_processor})
            # row 3-5 的投入/良品/不良/實際良率位于 4 组数据 + 匯總 的左侧锚点列
            rules.append({'row_range': (3, 5), 'col_list': [3, 5, 7, 9], 'processor': default_processor})
            # row 9-17 的不良項目區，數量/不良率是独立视觉列，按整段 3-12 抓
            rules.append({'row_range': (9, 17), 'col_list': [3, 5, 7, 9], 'processor': default_processor})
        
        elif process == "固熔":
            # 線別
            rules.append({'row_range': (1, 1), 'col_list': [3, 5, 7], 'processor':gurong_line_processor})
            # 投入数，不良数
            rules.append({'row_range': (2, 3), 'col_list': [3, 5, 7], 'processor': default_processor})
            # 不良項目區
            rules.append({'row_range': (7, 9), 'col_list': [3, 5, 7], 'processor': default_processor})
        
        elif process == "時效":
            # 按视觉列抓：上方统计区为合并单元格左侧锚点列 3
            rules.append({'row_range': (1, 3), 'col_list': [3], 'processor': default_processor})
            # 不良項目區按视觉列 3、4 抓（不良數 / 不良率）
            rules.append({'row_range': (7, 10), 'col_list': [3], 'processor': default_processor})
    
    elif key == "金加":
        process = header_info.get('製程')
        
        if process == "CNC0":
            # 按视觉列抓：上方统计区为合并单元格左侧锚点列 3
            rules.append({'row_range': (1, 6), 'col_list': [3], 'processor': default_processor})
            # 不良項目區按视觉列 3、4 抓（保持现有抓取语义）
            rules.append({'row_range': (12, 19), 'col_list': [3, 4], 'processor': default_processor})
        
        elif process == "CNC0 全檢":
            # 按视觉列抓：上方统计区为合并单元格左侧锚点列 3
            rules.append({'row_range': (1, 5), 'col_list': [3], 'processor': default_processor})
            # 不良項目區按视觉列 3、4 抓（不良數 / 不良率）
            rules.append({'row_range': (11, 13), 'col_list': [3, 4], 'processor': default_processor})
    
    return rules

def insert_handwritten_data_to_base_table(handwritten_data: list, key: str, process: str) -> str:
    """
    将手写数据插入到基础表格中
    
    Args:
        handwritten_data: 提取的手写数据列表，每个元素包含 {'row': int, 'col': int, 'value': str}
        key: 表格类型 ("沖壓" 或 "金加")
        process: 工艺类型 ("鍛壓", "固熔", "時效", "CNC0", "CNC0 全檢")
        
    Returns:
        插入手写数据后的表格内容
    """
    
    # 导入基础表格模板
    from base_table import base_table_1, base_table_2, base_table_3, base_table_4, base_table_5
    
    # 根据key和process选择对应的表格
    target_table_content = ""
    if key == "沖壓":
        if process == "鍛壓":
            target_table_content = base_table_1
        elif process == "固熔":
            target_table_content = base_table_2
        elif process == "時效":
            target_table_content = base_table_3
    elif key == "金加":
        if process == "CNC0" or  process == None: # # 防止LLM任务失败，识别不出来，目前只有cnc0会识别不到制程
            target_table_content = base_table_4
        elif process == "CNC0 全檢":
            target_table_content = base_table_5
 
    # 解析目标表格内容
    soup = BeautifulSoup(target_table_content, 'html.parser')
    target_table = soup.find('table')
    
    if not target_table:
        print(f"错误：未找到对应的基础表格 (key: {key}, process: {process})", file=sys.stderr)
        return target_table_content
    
    rows = target_table.find_all('tr')
    
    # 构建表格矩阵以便定位单元格
    grid = []
    for row_idx, row in enumerate(rows):
        cells = row.find_all(['td', 'th'])
        if len(grid) <= row_idx:
            grid.append([])
        
        col_idx = 0
        for cell in cells:
            # 找到下一个可用的列位置
            while col_idx < len(grid[row_idx]) and grid[row_idx][col_idx] is not None:
                col_idx += 1
            
            # 获取 rowspan 和 colspan
            rowspan = int(cell.get('rowspan', 1))
            colspan = int(cell.get('colspan', 1))
            
            # 填充网格
            for r in range(row_idx, min(row_idx + rowspan, len(rows))):
                if len(grid) <= r:
                    grid.append([])
                for c in range(col_idx, col_idx + colspan):
                    while len(grid[r]) <= c:
                        grid[r].append(None)
                    if r == row_idx and c == col_idx:
                        grid[r][c] = cell  # 存储实际的标签对象
                    elif grid[r][c] is None:
                        grid[r][c] = cell  # rowspan/colspan 的延续单元格
            
            col_idx += colspan
    
    # 根据提取的handwritten_data更新表格
    for data_item in handwritten_data:
        row = data_item['row'] - 1  # 转换为0-based索引
        col = data_item['col'] - 1  # 转换为0-based索引
        value = data_item['value']
        
        # 确保行列在范围内
        if 0 <= row < len(grid) and 0 <= col < len(grid[row]):
            cell = grid[row][col]
            if hasattr(cell, 'string'):
                cell.string = value
    
    return str(soup)

def main(content:str) -> str:
    """
    主处理函数
    """
    content_dict = extract_single_table(content)
    # 提取表头信息
    user_input_example = content_dict["before"]
    # 提取表格类型 key
    no_blank_table = content_dict["table"].replace(" ", "") # 先去掉所有空格，避免干扰
    if "沖壓" in no_blank_table or "冲壓" in no_blank_table : 
        key = "沖壓"
    elif "金加" in no_blank_table:
        key = "金加"
    else:
        key = "NULL"
    print(f"表格类型：{key}")    
    # 调用LLM-api解析表头信息
    table_info = extract_info(key, user_input_example)
    if table_info:
        print("表头提取结果：")
        print(json.dumps(table_info, ensure_ascii=False, indent=2))
    else:
        print("表头提取失败")
        table_info = {}

    table = clean_table_rows(content_dict["table"]) # 去掉多余的空白行

    handwritten_data = extract_handwritten_data(table, key, table_info)

    processed_md = insert_handwritten_data_to_base_table(handwritten_data, key, table_info["製程"])
    summary_cells = []
    for k, v in table_info.items():
        value_text = "" if v is None else str(v)
        summary_cells.append(f"<td>{escape(k)}: {escape(value_text)}</td>")
    summary_table = ""
    if summary_cells:
        summary_table = "<table><tr>" + "".join(summary_cells) + "</tr></table>"
    processed_md = "# 品質明細表" + summary_table + processed_md
    return processed_md

def md_process(content:str) -> str:
    if content.count('<table>') >= 2: # 金加CNC0俩个表格情况
        # 找到第一个 <table> 标签的位置
        split_location = content.find('</table>') + len('</table>')
        content_1 = content[:split_location]  
        content_2 = content[split_location:] 
        processed_md = []
        processed_md_1 = main(content_1)
        processed_md_2 = main(content_2)
        return processed_md_1 + processed_md_2
    else: # 其他情况
        processed_md = main(content)   
        return processed_md
    

