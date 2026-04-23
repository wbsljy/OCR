"""统一导出 ORM 模型，便于应用启动时一次性注册表结构。"""

from extensions import Base

from .dashboard_board import (
    BoardChongyaDuanya,
    BoardChongyaGurong,
    BoardChongyaShixiao,
    BoardJinjiaCnc0,
    BoardJinjiaCnc0Full,
)
from .ocr_result import OcrResult
from .ocr_task import OcrTask

__all__ = [
    "Base",
    "OcrTask",
    "OcrResult",
    "BoardChongyaDuanya",
    "BoardChongyaGurong",
    "BoardChongyaShixiao",
    "BoardJinjiaCnc0",
    "BoardJinjiaCnc0Full",
]
