"""
命令行：读取 Markdown/HTML 文本文件，执行与 Web 端一致的 data_process.md_process。

示例（在项目根目录）:
  python run_md_process.py 鍛壓.md
  python run_md_process.py 鍛壓.md -o 鍛壓_out.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def normalize_mineru_escapes(text: str) -> str:
    """MinerU 导出偶见 rowspan=\\\"2\\\"，先规范为 HTML 双引号再交给 md_process。"""
    return text.replace('\\"', '"')


def main() -> None:
    parser = argparse.ArgumentParser(description="对文件执行 md_process")
    parser.add_argument("input", type=Path, help="输入文件路径（.md 等）")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="输出文件路径；省略则打印到标准输出",
    )
    parser.add_argument(
        "--no-normalize-quotes",
        action="store_true",
        help="跳过 \\\" → \" 的预处理",
    )
    args = parser.parse_args()

    path = args.input.expanduser().resolve()
    if not path.is_file():
        print(f"文件不存在: {path}", file=sys.stderr)
        sys.exit(1)

    text = path.read_text(encoding="utf-8")
    if not args.no_normalize_quotes:
        text = normalize_mineru_escapes(text)

    from data_process import md_process

    out = md_process(text)

    if args.output:
        out_path = args.output.expanduser().resolve()
        out_path.write_text(out, encoding="utf-8")
        print(out_path, file=sys.stderr)
    else:
        sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
        print(out)


if __name__ == "__main__":
    main()
