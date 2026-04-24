from __future__ import annotations

"""数据看板结构化业务表。"""

from sqlalchemy import Column, Date, DECIMAL, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import declared_attr

from extensions import Base


class DashboardRecordMixin:
    """五类看板业务表的公共字段。"""

    id = Column(Integer, primary_key=True)

    @declared_attr
    def task_id(cls):
        return Column(Integer, ForeignKey("ocr_task.id"), nullable=False, index=True)

    @declared_attr
    def ocr_result_id(cls):
        return Column(Integer, ForeignKey("ocr_result.id"), nullable=False, index=True)
    key_name = Column(String(16), nullable=False, index=True)
    production_date = Column(Date, nullable=False, index=True)
    shift = Column(String(16), nullable=True)
    product_name = Column(String(64), index=True, nullable=True)
    process_name = Column(String(32), nullable=False, index=True)


class BoardChongyaDuanya(DashboardRecordMixin, Base):
    __tablename__ = "board_chongya_duanya"
    __table_args__ = (
        UniqueConstraint(
            "production_date", "shift", "product_name", "part",
            name="uq_board_chongya_duanya_biz",
        ),
    )

    part = Column(Integer, nullable=False, default=1, server_default="1")

    batch_1 = Column(String(64), nullable=True)
    batch_2 = Column(String(64), nullable=True)
    batch_3 = Column(String(64), nullable=True)
    batch_4 = Column(String(64), nullable=True)
    line_1 = Column(String(64), nullable=True)
    line_2 = Column(String(64), nullable=True)
    line_3 = Column(String(64), nullable=True)
    line_4 = Column(String(64), nullable=True)
    input_1 = Column(Integer, nullable=True)
    input_2 = Column(Integer, nullable=True)
    input_3 = Column(Integer, nullable=True)
    input_4 = Column(Integer, nullable=True)
    input_total = Column(Integer, nullable=True)
    good_1 = Column(Integer, nullable=True)
    good_2 = Column(Integer, nullable=True)
    good_3 = Column(Integer, nullable=True)
    good_4 = Column(Integer, nullable=True)
    good_total = Column(Integer, nullable=True)
    bad_1 = Column(Integer, nullable=True)
    bad_2 = Column(Integer, nullable=True)
    bad_3 = Column(Integer, nullable=True)
    bad_4 = Column(Integer, nullable=True)
    bad_total = Column(Integer, nullable=True)
    actual_yield_total = Column(DECIMAL(5, 2), nullable=True)
    target_yield_total = Column(DECIMAL(5, 2), nullable=True)

    # 5.0+1.0/-0.3 偏小
    _5_0_1_0_0_3_pian_xiao_badnum_1 = Column(Integer, nullable=True)
    _5_0_1_0_0_3_pian_xiao_badnum_2 = Column(Integer, nullable=True)
    _5_0_1_0_0_3_pian_xiao_badnum_3 = Column(Integer, nullable=True)
    _5_0_1_0_0_3_pian_xiao_badnum_4 = Column(Integer, nullable=True)
    _5_0_1_0_0_3_pian_xiao_badnum_total = Column(Integer, nullable=True)

    # 50+12/-3 偏小
    _50_12_3_pian_xiao_badnum_1 = Column(Integer, nullable=True)
    _50_12_3_pian_xiao_badnum_2 = Column(Integer, nullable=True)
    _50_12_3_pian_xiao_badnum_3 = Column(Integer, nullable=True)
    _50_12_3_pian_xiao_badnum_4 = Column(Integer, nullable=True)
    _50_12_3_pian_xiao_badnum_total = Column(Integer, nullable=True)

    # 50+12/-3 偏大
    _50_12_3_pian_da_badnum_1 = Column(Integer, nullable=True)
    _50_12_3_pian_da_badnum_2 = Column(Integer, nullable=True)
    _50_12_3_pian_da_badnum_3 = Column(Integer, nullable=True)
    _50_12_3_pian_da_badnum_4 = Column(Integer, nullable=True)
    _50_12_3_pian_da_badnum_total = Column(Integer, nullable=True)

    # 垂直度 0.40 偏大
    chui_zhi_du_0_40_pian_da_badnum_1 = Column(Integer, nullable=True)
    chui_zhi_du_0_40_pian_da_badnum_2 = Column(Integer, nullable=True)
    chui_zhi_du_0_40_pian_da_badnum_3 = Column(Integer, nullable=True)
    chui_zhi_du_0_40_pian_da_badnum_4 = Column(Integer, nullable=True)
    chui_zhi_du_0_40_pian_da_badnum_total = Column(Integer, nullable=True)

    # 垂直度 0.70 偏大
    chui_zhi_du_0_70_pian_da_badnum_1 = Column(Integer, nullable=True)
    chui_zhi_du_0_70_pian_da_badnum_2 = Column(Integer, nullable=True)
    chui_zhi_du_0_70_pian_da_badnum_3 = Column(Integer, nullable=True)
    chui_zhi_du_0_70_pian_da_badnum_4 = Column(Integer, nullable=True)
    chui_zhi_du_0_70_pian_da_badnum_total = Column(Integer, nullable=True)

    # 4.20+/-0.30∣P1-P3∣＜0.2 偏大
    _4_20_0_30_P1_P3_0_2_pian_da_badnum_1 = Column(Integer, nullable=True)
    _4_20_0_30_P1_P3_0_2_pian_da_badnum_2 = Column(Integer, nullable=True)
    _4_20_0_30_P1_P3_0_2_pian_da_badnum_3 = Column(Integer, nullable=True)
    _4_20_0_30_P1_P3_0_2_pian_da_badnum_4 = Column(Integer, nullable=True)
    _4_20_0_30_P1_P3_0_2_pian_da_badnum_total = Column(Integer, nullable=True)

    # 4.20+/-0.30∣P2-P4∣＜0.2 偏大
    _4_20_0_30_P2_P4_0_2_pian_da_badnum_1 = Column(Integer, nullable=True)
    _4_20_0_30_P2_P4_0_2_pian_da_badnum_2 = Column(Integer, nullable=True)
    _4_20_0_30_P2_P4_0_2_pian_da_badnum_3 = Column(Integer, nullable=True)
    _4_20_0_30_P2_P4_0_2_pian_da_badnum_4 = Column(Integer, nullable=True)
    _4_20_0_30_P2_P4_0_2_pian_da_badnum_total = Column(Integer, nullable=True)

    # 2D 碼偏位
    _2D_ma_pian_wei_badnum_1 = Column(Integer, nullable=True)
    _2D_ma_pian_wei_badnum_2 = Column(Integer, nullable=True)
    _2D_ma_pian_wei_badnum_3 = Column(Integer, nullable=True)
    _2D_ma_pian_wei_badnum_4 = Column(Integer, nullable=True)
    _2D_ma_pian_wei_badnum_total = Column(Integer, nullable=True)

    # DDS
    DDS_badnum_1 = Column(Integer, nullable=True)
    DDS_badnum_2 = Column(Integer, nullable=True)
    DDS_badnum_3 = Column(Integer, nullable=True)
    DDS_badnum_4 = Column(Integer, nullable=True)
    DDS_badnum_total = Column(Integer, nullable=True)


class BoardChongyaGurong(DashboardRecordMixin, Base):
    """沖壓-固熔：三組線體 + 匯總；無原材批次。"""

    __tablename__ = "board_chongya_gurong"
    __table_args__ = (
        UniqueConstraint("production_date", "shift", "product_name", name="uq_board_chongya_gurong_biz"),
    )

    line_1 = Column(String(64), nullable=True)
    line_2 = Column(String(64), nullable=True)
    line_3 = Column(String(64), nullable=True)
    input_1 = Column(Integer, nullable=True)
    input_2 = Column(Integer, nullable=True)
    input_3 = Column(Integer, nullable=True)
    input_total = Column(Integer, nullable=True)
    good_1 = Column(Integer, nullable=True)
    good_2 = Column(Integer, nullable=True)
    good_3 = Column(Integer, nullable=True)
    good_total = Column(Integer, nullable=True)
    bad_1 = Column(Integer, nullable=True)
    bad_2 = Column(Integer, nullable=True)
    bad_3 = Column(Integer, nullable=True)
    bad_total = Column(Integer, nullable=True)
    actual_yield_total = Column(DECIMAL(5, 2), nullable=True)
    target_yield_total = Column(DECIMAL(5, 2), nullable=True)

    # 硬度 40≤Hba≤60 偏大
    ying_du_40_Hba_60_pian_da_badnum_1 = Column(Integer, nullable=True)
    ying_du_40_Hba_60_pian_da_badnum_2 = Column(Integer, nullable=True)
    ying_du_40_Hba_60_pian_da_badnum_3 = Column(Integer, nullable=True)
    ying_du_40_Hba_60_pian_da_badnum_total = Column(Integer, nullable=True)

    # 變形
    bian_xing_badnum_1 = Column(Integer, nullable=True)
    bian_xing_badnum_2 = Column(Integer, nullable=True)
    bian_xing_badnum_3 = Column(Integer, nullable=True)
    bian_xing_badnum_total = Column(Integer, nullable=True)

    # DDS
    DDS_badnum_1 = Column(Integer, nullable=True)
    DDS_badnum_2 = Column(Integer, nullable=True)
    DDS_badnum_3 = Column(Integer, nullable=True)
    DDS_badnum_total = Column(Integer, nullable=True)


class BoardChongyaShixiao(DashboardRecordMixin, Base):
    __tablename__ = "board_chongya_shixiao"
    __table_args__ = (
        UniqueConstraint("production_date", "shift", "product_name", name="uq_board_chongya_shixiao_biz"),
    )

    input_total = Column(Integer, nullable=True)
    good_total = Column(Integer, nullable=True)
    bad_total = Column(Integer, nullable=True)
    actual_yield_total = Column(DECIMAL(5, 2), nullable=True)
    target_yield_total = Column(DECIMAL(5, 2), nullable=True)

    # 變形
    bian_xing_badnum_total = Column(Integer, nullable=True)

    # 機械性能送檢
    ji_xie_xing_neng_song_jian_badnum_total = Column(Integer, nullable=True)

    # 硬度 Hba≥74 偏小
    ying_du_Hba_74_pian_xiao_badnum_total = Column(Integer, nullable=True)

    # DDS
    DDS_badnum_total = Column(Integer, nullable=True)


class BoardJinjiaCnc0(DashboardRecordMixin, Base):
    __tablename__ = "board_jinjia_cnc0"
    __table_args__ = (
        UniqueConstraint(
            "production_date",
            "shift",
            "product_name",
            "inspection_location",
            name="uq_board_jinjia_cnc0_biz",
        ),
    )

    inspection_location = Column(String(32), nullable=True)
    input_total = Column(Integer, nullable=True)
    sample = Column(Integer, nullable=True)
    first_good = Column(Integer, nullable=True)
    bad_total = Column(Integer, nullable=True)
    reworkable_bad = Column(Integer, nullable=True)
    unreworkable_bad = Column(Integer, nullable=True)
    first_yield = Column(DECIMAL(5, 2), nullable=True)
    second_yield = Column(DECIMAL(5, 2), nullable=True)
    first_target_yield = Column(DECIMAL(5, 2), nullable=True)
    second_target_yield = Column(DECIMAL(5, 2), nullable=True)

    # DDS
    DDS_badnum_reworkable = Column(Integer, nullable=True)
    DDS_badnum_unreworkable = Column(Integer, nullable=True)

    # 臺階/過切
    tai_jie_guo_qie_badnum_reworkable = Column(Integer, nullable=True)
    tai_jie_guo_qie_badnum_unreworkable = Column(Integer, nullable=True)

    # 毛邊/毛刺
    mao_bian_mao_ci_badnum_reworkable = Column(Integer, nullable=True)
    mao_bian_mao_ci_badnum_unreworkable = Column(Integer, nullable=True)

    # 大平面未見光
    da_ping_mian_wei_jian_guang_badnum_reworkable = Column(Integer, nullable=True)
    da_ping_mian_wei_jian_guang_badnum_unreworkable = Column(Integer, nullable=True)

    # 大平面刀紋/刀痕
    da_ping_mian_dao_wen_dao_hen_badnum_reworkable = Column(Integer, nullable=True)
    da_ping_mian_dao_wen_dao_hen_badnum_unreworkable = Column(Integer, nullable=True)

    # 平面度 0.10 偏大
    ping_mian_du_0_10_pian_da_badnum_reworkable = Column(Integer, nullable=True)
    ping_mian_du_0_10_pian_da_badnum_unreworkable = Column(Integer, nullable=True)

    # 4.70+/-0.10 偏大
    _4_70_0_10_pian_da_badnum_reworkable = Column(Integer, nullable=True)
    _4_70_0_10_pian_da_badnum_unreworkable = Column(Integer, nullable=True)

    # 4.70+/-0.10 偏小
    _4_70_0_10_pian_xiao_badnum_reworkable = Column(Integer, nullable=True)
    _4_70_0_10_pian_xiao_badnum_unreworkable = Column(Integer, nullable=True)


class BoardJinjiaCnc0Full(DashboardRecordMixin, Base):
    __tablename__ = "board_jinjia_cnc0_full"
    __table_args__ = (
        UniqueConstraint("production_date", "shift", "product_name", name="uq_board_jinjia_cnc0_full_biz"),
    )

    input_total = Column(Integer, nullable=True)
    first_good = Column(Integer, nullable=True)
    bad_total = Column(Integer, nullable=True)
    reworkable_bad = Column(Integer, nullable=True)
    unreworkable_bad = Column(Integer, nullable=True)
    first_yield = Column(DECIMAL(5, 2), nullable=True)
    second_yield = Column(DECIMAL(5, 2), nullable=True)
    first_target_yield = Column(DECIMAL(5, 2), nullable=True)
    second_target_yield = Column(DECIMAL(5, 2), nullable=True)

    # 大平面刀紋/刀痕
    da_ping_mian_dao_wen_dao_hen_badnum_total = Column(Integer, nullable=True)

    # 毛邊/毛刺
    mao_bian_mao_ci_badnum_total = Column(Integer, nullable=True)

    # 大平面未見光
    da_ping_mian_wei_jian_guang_badnum_total = Column(Integer, nullable=True)
