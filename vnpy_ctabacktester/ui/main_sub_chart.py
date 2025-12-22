"""
主图 + 多副图布局（雪球图风格）：
  - 主图控制栏：K线 / MA5~60 / BOLL / VP / 回测下拉框；右侧显示当前光标 MA/BOLL 数值
  - OHLCV 信息栏：日期、开/高/低/收/量；悬停交易时追加交易详情
  - 主图：CandleItem + 按需叠加均线/布林通道/VP（量价分布）/回测开平仓标记
  - 多副图：每个副图由"标题栏 + ChartWidget"组成
  - 副图选择栏：底部横向按钮

回测交易叠加：
  - 回测下拉框选择 隐藏/全部/做多/做空
  - 多头开仓：绿色实心向上三角（K线低点下方）
  - 多头平仓：绿色空心向下三角（K线高点上方）
  - 空头开仓：红色实心向下三角（K线高点上方）
  - 空头平仓：红色空心向上三角（K线低点下方）
  - 连线：盈利红色虚线，亏损绿色虚线
  - 悬停详情：在 OHLCV 栏下方显示该 bar 的开平仓信息

颜色可通过文件顶部 TRADE_COLORS 字典统一配置。
"""
from __future__ import annotations

from copy import copy

import pyqtgraph as pg

from vnpy.trader.ui import QtWidgets, QtCore, QtGui
from vnpy.trader.object import BarData, TradeData
from vnpy.trader.constant import Direction

from vnpy.chart import (
    ChartWidget,
    CandleItem,
    VolumeItem,
    VolumePriceItem,
    BollingerItem,
    RSIItem,
    KDJItem,
    MACDItem,
    MAItem,
    WRItem,
    PSYItem,
    ATRItem,
    BIASItem,
    OBVItem,
    CCIItem,
    DMIItem,
    ADXItem,
)
from vnpy.chart.base import color_rgb_to_hex

# ── 主题色板 ──────────────────────────────────────────────────────
BG_APP      = "#0d1117"
BG_TOOLBAR  = "#161b22"
BG_INFOBAR  = "#161b22"
BG_TITLEBAR = "#1c2128"
BG_BTNBAR   = "#161b22"
BTN_NORMAL  = "#21262d"
BTN_CHECKED = "#1f6feb"
TEXT_NORMAL = "#8b949e"
TEXT_INFO   = "#c9d1d9"
TEXT_WHITE  = "#ffffff"
BORDER      = "#30363d"

# 均线颜色
MA_COLORS: dict[int, str] = {
    5:  "#ff9800",
    10: "#ce93d8",
    20: "#42a5f5",
    30: "#26c6da",
    60: "#66bb6a",
}
BOLL_COLOR = "#ef9a9a"

# ── 回测交易颜色（可配置）────────────────────────────────────────
TRADE_COLORS: dict[str, str] = {
    "long_open":   "#00c853",   # 多头开仓 实心向上三角
    "long_close":  "#00c853",   # 多头平仓 空心向下三角
    "short_open":  "#ff1744",   # 空头开仓 实心向下三角
    "short_close": "#ff1744",   # 空头平仓 空心向上三角
    "pnl_profit":  "#ff1744",   # 盈利连线（红）
    "pnl_loss":    "#00c853",   # 亏损连线（绿）
}

# ── 副图指标配置 ──────────────────────────────────────────────────
# 同时显示的最大副图个数（超过时自动挤掉最早选中的副图）
MAX_VISIBLE_SUB_CHARTS: int = 3

SUB_INDICATOR_CONFIGS: list[tuple] = [
    ("成交量", "",          "volume", {"maximum_height": 200, "hide_x_axis": True}, VolumeItem, "volume", {}),
    ("RSI",   "(6,12,24)", "rsi",    {"maximum_height": 120, "hide_x_axis": True}, RSIItem,    "rsi",    {"n_short": 6, "n_mid": 12, "n_long": 24}),
    ("KDJ",   "(9,3,3)",   "kdj",    {"maximum_height": 120, "hide_x_axis": True}, KDJItem,    "kdj",    {"fastk_period": 9, "slowk_period": 3, "slowd_period": 3}),
    ("MACD",  "(12,26,9)", "macd",   {"maximum_height": 120, "hide_x_axis": True}, MACDItem,   "macd",   {"fast_period": 12, "slow_period": 26, "signal_period": 9}),
    ("WR",    "(14)",      "wr",     {"maximum_height": 120, "hide_x_axis": True}, WRItem,     "wr",     {"n": 14}),
    ("PSY",   "(12,6)",    "psy",    {"maximum_height": 120, "hide_x_axis": True}, PSYItem,    "psy",    {"n": 12, "m": 6}),
    ("ATR",   "(14)",      "atr",    {"maximum_height": 120, "hide_x_axis": True}, ATRItem,    "atr",    {"n": 14}),
    ("BIAS",  "(6)",       "bias",   {"maximum_height": 120, "hide_x_axis": True}, BIASItem,   "bias",   {"n": 6}),
    ("OBV",   "",          "obv",    {"maximum_height": 120, "hide_x_axis": True}, OBVItem,    "obv",    {}),
    ("CCI",   "(14)",      "cci",    {"maximum_height": 120, "hide_x_axis": True}, CCIItem,    "cci",    {"n": 14}),
    ("DMI",   "(14)",      "dmi",    {"maximum_height": 120, "hide_x_axis": True}, DMIItem,    "dmi",    {"n": 14}),
    ("ADX",   "(14)",      "adx",    {"maximum_height": 120, "hide_x_axis": True}, ADXItem,    "adx",    {"n": 14}),
]

# ── 动态指标参数 schema ────────────────────────────────────────────
# 格式：指标名 → {"item_class": ..., "params": [(参数名, 类型, 默认值), ...]}
INDICATOR_SCHEMAS: dict[str, dict] = {
    "ADX":  {"item_class": ADXItem,  "params": [("n", int, 14), ("adx_level", int, 25)]},
    "RSI":  {"item_class": RSIItem,  "params": [("n_short", int, 6), ("n_mid", int, 12), ("n_long", int, 24)]},
    "KDJ":  {"item_class": KDJItem,  "params": [("fastk_period", int, 9), ("slowk_period", int, 3), ("slowd_period", int, 3)]},
    "MACD": {"item_class": MACDItem, "params": [("fast_period", int, 12), ("slow_period", int, 26), ("signal_period", int, 9)]},
    "WR":   {"item_class": WRItem,   "params": [("n", int, 14)]},
    "PSY":  {"item_class": PSYItem,  "params": [("n", int, 12), ("m", int, 6)]},
    "ATR":  {"item_class": ATRItem,  "params": [("n", int, 14)]},
    "BIAS": {"item_class": BIASItem, "params": [("n", int, 6)]},
    "CCI":  {"item_class": CCIItem,  "params": [("n", int, 14)]},
    "DMI":  {"item_class": DMIItem,  "params": [("n", int, 14)]},
}


# ── 通用工具 ──────────────────────────────────────────────────────

def _make_vsep() -> QtWidgets.QFrame:
    sep = QtWidgets.QFrame()
    sep.setFrameShape(QtWidgets.QFrame.Shape.VLine)
    sep.setFixedWidth(1)
    sep.setStyleSheet(f"background-color: {BORDER}; border: none;")
    return sep


# ── 按钮样式 ──────────────────────────────────────────────────────

_TOGGLE_CHECKED_STYLE = (
    f"QPushButton {{"
    f"  background: {BTN_CHECKED};"
    f"  color: {TEXT_WHITE};"
    f"  border: 1px solid transparent;"
    f"  border-radius: 3px;"
    f"  padding: 0 10px;"
    f"  font-size: 12px;"
    f"  min-width: 44px;"
    f"}}"
)
_TOGGLE_NORMAL_STYLE = (
    f"QPushButton {{"
    f"  background: {BTN_NORMAL};"
    f"  color: {TEXT_NORMAL};"
    f"  border: 1px solid {BORDER};"
    f"  border-radius: 3px;"
    f"  padding: 0 10px;"
    f"  font-size: 12px;"
    f"  min-width: 44px;"
    f"}}"
    f"QPushButton:hover {{"
    f"  background: #2d333b;"
    f"  color: {TEXT_INFO};"
    f"}}"
)

_COMBO_STYLE = (
    f"QComboBox {{"
    f"  background: {BTN_NORMAL};"
    f"  color: {TEXT_NORMAL};"
    f"  border: 1px solid {BORDER};"
    f"  border-radius: 3px;"
    f"  padding: 0 6px;"
    f"  font-size: 12px;"
    f"  min-width: 52px;"
    f"  min-height: 20px;"
    f"  max-height: 20px;"
    f"}}"
    f"QComboBox:hover {{"
    f"  background: #2d333b;"
    f"  color: {TEXT_INFO};"
    f"}}"
    f"QComboBox::drop-down {{"
    f"  border: none;"
    f"  width: 14px;"
    f"}}"
    f"QComboBox QAbstractItemView {{"
    f"  background: #1c2128;"
    f"  color: {TEXT_INFO};"
    f"  border: 1px solid {BORDER};"
    f"  selection-background-color: {BTN_CHECKED}33;"
    f"  outline: none;"
    f"}}"
)


class _ToggleButton(QtWidgets.QPushButton):
    """统一蓝色选中样式的 checkable 按钮（主图叠加指标用）。"""

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setCheckable(True)
        self.setChecked(False)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(22)
        self._refresh_style(False)
        self.toggled.connect(self._refresh_style)

    def _refresh_style(self, checked: bool) -> None:
        self.setStyleSheet(
            _TOGGLE_CHECKED_STYLE if checked else _TOGGLE_NORMAL_STYLE
        )


class _IndicatorButton(QtWidgets.QPushButton):
    """副图选择栏按钮：选中时高亮边框。"""

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setCheckable(True)
        self.setChecked(False)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(28)
        self._refresh_style(False)
        self.toggled.connect(self._refresh_style)

    def _refresh_style(self, checked: bool) -> None:
        if checked:
            self.setStyleSheet(
                f"QPushButton {{"
                f"  background: {BTN_CHECKED}22;"
                f"  color: {TEXT_INFO};"
                f"  border: 1px solid {BTN_CHECKED}66;"
                f"  border-radius: 3px;"
                f"  padding: 0 10px;"
                f"  font-size: 12px;"
                f"}}"
            )
        else:
            self.setStyleSheet(
                f"QPushButton {{"
                f"  background: transparent;"
                f"  color: {TEXT_NORMAL};"
                f"  border: none;"
                f"  border-radius: 3px;"
                f"  padding: 0 10px;"
                f"  font-size: 12px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background: {BTN_NORMAL};"
                f"  color: {TEXT_INFO};"
                f"}}"
            )


# ── 动态指标配置对话框 ────────────────────────────────────────────

class _IndicatorConfigDialog(QtWidgets.QDialog):
    """弹出对话框：选择指标类型 + 填写参数，返回与 SUB_INDICATOR_CONFIGS 兼容的 tuple。"""

    def __init__(
        self,
        schemas: dict,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._schemas = schemas
        self._spinboxes: dict[str, QtWidgets.QSpinBox] = {}
        self._result_config: tuple | None = None

        self.setWindowTitle("添加副图指标")
        self.setMinimumWidth(320)
        self.setStyleSheet(
            f"background-color: {BG_APP};"
            f"color: {TEXT_INFO};"
        )

        root = QtWidgets.QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 16, 16, 16)

        # 指标类型选择
        type_row = QtWidgets.QHBoxLayout()
        type_label = QtWidgets.QLabel("指标类型:")
        type_label.setStyleSheet(f"color: {TEXT_INFO}; font-size: 12px;")
        self._type_combo = QtWidgets.QComboBox()
        self._type_combo.addItems(list(schemas.keys()))
        self._type_combo.setStyleSheet(_COMBO_STYLE)
        self._type_combo.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        type_row.addWidget(type_label)
        type_row.addWidget(self._type_combo, stretch=1)
        root.addLayout(type_row)

        # 动态参数区域
        self._param_group = QtWidgets.QGroupBox("参数")
        self._param_group.setStyleSheet(
            f"QGroupBox {{"
            f"  color: {TEXT_NORMAL};"
            f"  border: 1px solid {BORDER};"
            f"  border-radius: 4px;"
            f"  margin-top: 6px;"
            f"  font-size: 12px;"
            f"}}"
            f"QGroupBox::title {{"
            f"  subcontrol-origin: margin;"
            f"  left: 8px;"
            f"  padding: 0 4px;"
            f"}}"
        )
        self._param_form = QtWidgets.QFormLayout(self._param_group)
        self._param_form.setSpacing(6)
        root.addWidget(self._param_group)

        # OK / Cancel
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QtWidgets.QPushButton("确认")
        ok_btn.setFixedHeight(26)
        ok_btn.setStyleSheet(_TOGGLE_CHECKED_STYLE)
        ok_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QtWidgets.QPushButton("取消")
        cancel_btn.setFixedHeight(26)
        cancel_btn.setStyleSheet(_TOGGLE_NORMAL_STYLE)
        cancel_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        root.addLayout(btn_row)

        self._type_combo.currentTextChanged.connect(self._rebuild_params)
        self._rebuild_params(self._type_combo.currentText())

    def _rebuild_params(self, indicator_name: str) -> None:
        """切换指标类型时，重新渲染参数输入行。"""
        while self._param_form.rowCount():
            self._param_form.removeRow(0)
        self._spinboxes.clear()

        schema = self._schemas.get(indicator_name, {})
        for param_name, param_type, default in schema.get("params", []):
            spin = QtWidgets.QSpinBox()
            spin.setRange(1, 9999)
            spin.setValue(default)
            spin.setFixedHeight(24)
            spin.setStyleSheet(
                f"QSpinBox {{"
                f"  background: {BTN_NORMAL};"
                f"  color: {TEXT_INFO};"
                f"  border: 1px solid {BORDER};"
                f"  border-radius: 3px;"
                f"  padding: 0 4px;"
                f"  font-size: 12px;"
                f"}}"
            )
            lbl = QtWidgets.QLabel(param_name)
            lbl.setStyleSheet(f"color: {TEXT_NORMAL}; font-size: 12px;")
            self._param_form.addRow(lbl, spin)
            self._spinboxes[param_name] = spin

    def _on_ok(self) -> None:
        self._result_config = self._build_config()
        self.accept()

    def _build_config(self) -> tuple:
        """构造与 SUB_INDICATOR_CONFIGS 条目格式完全相同的 tuple。"""
        indicator_name = self._type_combo.currentText()
        schema = self._schemas[indicator_name]
        item_class = schema["item_class"]

        item_kwargs = {k: spin.value() for k, spin in self._spinboxes.items()}
        param_values = [str(spin.value()) for spin in self._spinboxes.values()]
        param_str = f"({','.join(param_values)})" if param_values else ""

        # 按钮 + 标题显示名，例如 "ADX(10)"
        display_label = f"{indicator_name}{param_str}"
        plot_name = indicator_name.lower()
        item_name = indicator_name.lower()
        plot_kwargs = {"maximum_height": 120, "hide_x_axis": True}

        return (display_label, "", plot_name, plot_kwargs, item_class, item_name, item_kwargs)

    def get_config(self) -> tuple | None:
        return self._result_config


# ── 副图槽位 ──────────────────────────────────────────────────────

class _SubSlot(QtWidgets.QWidget):
    """单个副图槽位：标题栏（参数 + 当前值）+ ChartWidget（仅竖线光标）。"""

    def __init__(self, config: tuple, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        label, param, plot_name, plot_kwargs, item_class, item_name, item_kwargs = config
        self._label_str = label
        self._param_str = param
        self._full_param = f"{label}{param}" if param else label

        self.target_height: int = plot_kwargs.get("maximum_height", 120) + 22

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._title = QtWidgets.QLabel(self._full_param)
        self._title.setFixedHeight(22)
        self._title.setTextFormat(getattr(QtCore.Qt.TextFormat, "RichText", QtCore.Qt.RichText))
        self._title.setStyleSheet(
            f"background-color: {BG_TITLEBAR};"
            f"color: {TEXT_INFO};"
            f"font-family: Consolas, 'Courier New', monospace;"
            f"font-size: 11px;"
            f"padding: 0 10px;"
            f"border-top: 1px solid {BORDER};"
        )
        layout.addWidget(self._title)

        self.chart = ChartWidget(self)
        self.chart.add_plot(plot_name, **plot_kwargs)
        self.chart.add_item(item_class, item_name, plot_name, **item_kwargs)
        self.chart.add_cursor()
        if self.chart._cursor:
            self.chart._cursor.set_overlay_visible(False)
        self.chart.setMinimumHeight(80)
        layout.addWidget(self.chart)

    def set_cursor_x(self, ix: int) -> None:
        self.chart.set_cursor_index(ix)

    def refresh_info(self, ix: int) -> None:
        html = self.chart.get_info_html_at(ix)
        if html:
            self._title.setText(f"{self._full_param}    {html}")
        else:
            self._title.setText(self._full_param)


# ── 交易配对辅助 ──────────────────────────────────────────────────

def generate_trade_pairs(trades: list) -> list:
    """FIFO 配对，将开仓和平仓成交合并为交易对。"""
    long_trades: list = []
    short_trades: list = []
    trade_pairs: list = []

    for trade in trades:
        trade = copy(trade)

        if trade.direction == Direction.LONG:
            same_direction: list = long_trades
            opposite_direction: list = short_trades
        else:
            same_direction = short_trades
            opposite_direction = long_trades

        while trade.volume and opposite_direction:
            open_trade: TradeData = opposite_direction[0]

            close_volume = min(open_trade.volume, trade.volume)
            d: dict = {
                "open_dt":     open_trade.datetime,
                "open_price":  open_trade.price,
                "close_dt":    trade.datetime,
                "close_price": trade.price,
                "direction":   open_trade.direction,
                "volume":      close_volume,
            }
            trade_pairs.append(d)

            open_trade.volume -= close_volume
            if not open_trade.volume:
                opposite_direction.pop(0)

            trade.volume -= close_volume

        if trade.volume:
            same_direction.append(trade)

    return trade_pairs


# ── 主控件 ───────────────────────────────────────────────────────

class MainSubChartWidget(QtWidgets.QWidget):
    """
    主图（K线 + 按需叠加均线/布林通道/回测信号）+ 多副图。

    公开接口（与 CandleChartDialog 兼容）：
        update_history(history)  ─ 传入 BarData 列表
        update_trades(trades)    ─ 传入 TradeData 列表，叠加开平仓标记
        clear_data()             ─ 清空图表和交易标记
        is_updated() -> bool     ─ 是否已加载数据
    """

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        # 图表状态
        self._main_widget: ChartWidget | None = None
        self._sub_slots: list[_SubSlot] = []
        self._sub_btns: list[_IndicatorButton] = []
        self._syncing: bool = False
        self._selected_order: list[int] = []
        self._updated: bool = False
        self._ohlcv_base_text: str = ""   # OHLCV 基础文字，供交易信息追加用

        # 回测交易状态
        self._dt_ix_map: dict = {}          # datetime → bar index
        self._ix_bar_map: dict = {}         # bar index → BarData
        self._price_range: float = 0.0
        self._trade_pairs: list[dict] = []
        self._trade_items: list = []        # 已绘到 candle_plot 的 pyqtgraph items
        self._bar_trade_map: dict[int, list] = {}   # ix → [{pair, role}, ...]
        self._trade_filter: str = "隐藏"

        self.setStyleSheet(f"background-color: {BG_APP};")
        self._init_ui()
        self._connect_signals()
        self._relink_x_axes()

    # ── UI 构建 ───────────────────────────────────────────────────

    def _init_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_main_toolbar())
        root.addWidget(self._build_ohlcv_bar())

        self._main_widget = self._build_main_chart()
        root.addWidget(self._main_widget, stretch=3)

        self._sub_area = QtWidgets.QWidget()
        self._sub_area.setStyleSheet(f"background-color: {BG_APP};")
        self._sub_layout = QtWidgets.QVBoxLayout(self._sub_area)
        self._sub_layout.setContentsMargins(0, 0, 0, 0)
        self._sub_layout.setSpacing(0)
        for config in SUB_INDICATOR_CONFIGS:
            slot = _SubSlot(config, self._sub_area)
            slot.setVisible(False)
            self._sub_slots.append(slot)
            self._sub_layout.addWidget(slot, stretch=1)
        root.addWidget(self._sub_area, stretch=2)

        root.addWidget(self._build_sub_selector())

    def _build_main_toolbar(self) -> QtWidgets.QWidget:
        bar = QtWidgets.QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet(
            f"background-color: {BG_TOOLBAR};"
            f"border-bottom: 1px solid {BORDER};"
        )
        outer = QtWidgets.QVBoxLayout(bar)
        outer.setContentsMargins(10, 2, 10, 2)
        outer.setSpacing(2)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setSpacing(5)

        self._ma_btns: dict[int, _ToggleButton] = {}
        for period in (5, 10, 20, 30, 60):
            btn = _ToggleButton(f"MA{period}")
            btn.toggled.connect(
                lambda checked, p=period: self._on_ma_toggled(p, checked)
            )
            btn.setChecked(True)
            self._ma_btns[period] = btn
            btn_row.addWidget(btn)

        btn_row.addWidget(_make_vsep())

        self._boll_btn = _ToggleButton("BOLL")
        self._boll_btn.toggled.connect(
            lambda checked: self._on_overlay_toggled("boll", checked)
        )
        self._boll_btn.setChecked(True)
        btn_row.addWidget(self._boll_btn)

        self._vp_btn = _ToggleButton("VP")
        self._vp_btn.toggled.connect(
            lambda checked: self._on_overlay_toggled("vp", checked)
        )
        self._vp_btn.setChecked(False)
        btn_row.addWidget(self._vp_btn)

        btn_row.addWidget(_make_vsep())

        # 回测下拉框（BOLL / VP 后）
        _trade_label = QtWidgets.QLabel("回测:")
        _trade_label.setFixedHeight(20)
        _trade_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        _trade_label.setStyleSheet(
            f"color: {TEXT_NORMAL}; font-size: 12px; padding: 0 2px 0 4px;"
        )
        btn_row.addWidget(_trade_label, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)

        self._trade_combo = QtWidgets.QComboBox()
        self._trade_combo.setFixedHeight(20)
        self._trade_combo.addItems(["隐藏", "全部", "做多", "做空", "盈利", "亏损"])
        self._trade_combo.setStyleSheet(_COMBO_STYLE)
        self._trade_combo.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._trade_combo.currentTextChanged.connect(self._on_trade_filter_changed)
        btn_row.addWidget(self._trade_combo, alignment=QtCore.Qt.AlignmentFlag.AlignVCenter)

        btn_row.addStretch()
        outer.addLayout(btn_row)

        self._ma_values_label = QtWidgets.QLabel("")
        self._ma_values_label.setStyleSheet(
            f"color: {TEXT_NORMAL};"
            f"font-family: Consolas, 'Courier New', monospace;"
            f"font-size: 11px;"
        )
        outer.addWidget(self._ma_values_label)
        return bar

    def _build_ohlcv_bar(self) -> QtWidgets.QWidget:
        bar = QtWidgets.QWidget()
        bar.setFixedHeight(24)
        bar.setStyleSheet(
            f"background-color: {BG_INFOBAR};"
            f"border-bottom: 1px solid {BORDER};"
        )
        layout = QtWidgets.QHBoxLayout(bar)
        layout.setContentsMargins(10, 0, 10, 0)
        self._ohlcv_label = QtWidgets.QLabel("")
        self._ohlcv_label.setStyleSheet(
            f"color: {TEXT_INFO};"
            f"font-family: Consolas, 'Courier New', monospace;"
            f"font-size: 11px;"
        )
        layout.addWidget(self._ohlcv_label)
        layout.addStretch()

        # 交易信息区：靠右锚定、宽度随内容，右对齐
        self._trade_info_label = QtWidgets.QLabel("")
        self._trade_info_label.setStyleSheet(
            f"color: {TEXT_INFO};"
            f"font-family: Consolas, 'Courier New', monospace;"
            f"font-size: 11px;"
        )
        self._trade_info_label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._trade_info_label)
        return bar

    def _build_main_chart(self) -> ChartWidget:
        w = ChartWidget(self)
        w.add_plot("candle", hide_x_axis=False)
        w.add_item(CandleItem, "candle", "candle")
        for period in (5, 10, 20, 30, 60):
            w.add_item(MAItem, f"ma{period}", "candle", period=period)
        w.add_item(BollingerItem, "boll", "candle", n=20, dev=2.0)
        w.add_item(VolumePriceItem, "vp", "candle")
        vp_item = w.get_item("vp")
        if vp_item:
            vp_item.setVisible(False)
        w.add_cursor()
        if w._cursor:
            w._cursor.set_overlay_visible(False)
        w.setMinimumHeight(320)
        return w

    def _build_sub_selector(self) -> QtWidgets.QWidget:
        bar = QtWidgets.QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet(
            f"background-color: {BG_BTNBAR};"
            f"border-top: 1px solid {BORDER};"
        )
        layout = QtWidgets.QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        for i, config in enumerate(SUB_INDICATOR_CONFIGS):
            label, *_ = config
            btn = _IndicatorButton(label)
            btn.toggled.connect(
                lambda checked, idx=i: self._on_sub_toggled(idx, checked)
            )
            btn.setChecked(i == 0)
            self._sub_btns.append(btn)
            layout.addWidget(btn)

        layout.addWidget(_make_vsep())

        add_btn = QtWidgets.QPushButton("+")
        add_btn.setFixedSize(24, 24)
        add_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        add_btn.setToolTip("添加自定义指标副图")
        add_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {BTN_NORMAL};"
            f"  color: {TEXT_INFO};"
            f"  border: 1px solid {BORDER};"
            f"  border-radius: 3px;"
            f"  font-size: 16px;"
            f"  font-weight: bold;"
            f"  padding: 0;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {BTN_CHECKED};"
            f"  color: {TEXT_WHITE};"
            f"}}"
        )
        add_btn.clicked.connect(self._on_add_indicator_clicked)
        layout.addWidget(add_btn)

        self._sub_selector_layout = layout
        layout.addStretch()
        return bar

    # ── 信号连接 ──────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        if not self._main_widget:
            return
        self._main_widget.cursor_index_changed.connect(self._on_cursor_changed)
        for slot in self._sub_slots:
            slot.chart.cursor_index_changed.connect(
                lambda ix, s=slot: self._on_sub_cursor_changed(ix, s)
            )

    # ── 事件处理 ──────────────────────────────────────────────────

    def _on_cursor_changed(self, ix: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            self._refresh_ohlcv(ix)
            self._refresh_ma_values(ix)
            self._refresh_trade_info(ix)
            for slot in self._sub_slots:
                if slot.isVisible():
                    slot.set_cursor_x(ix)
                    slot.refresh_info(ix)
        finally:
            self._syncing = False

    def _on_sub_cursor_changed(self, ix: int, source_slot: "_SubSlot") -> None:
        if self._syncing or not self._main_widget:
            return
        self._syncing = True
        try:
            self._main_widget.set_cursor_index(ix)
            self._refresh_ohlcv(ix)
            self._refresh_ma_values(ix)
            self._refresh_trade_info(ix)
            for slot in self._sub_slots:
                if slot.isVisible() and slot is not source_slot:
                    slot.set_cursor_x(ix)
                    slot.refresh_info(ix)
            source_slot.refresh_info(ix)
        finally:
            self._syncing = False

    def _on_ma_toggled(self, period: int, checked: bool) -> None:
        if not self._main_widget:
            return
        item = self._main_widget.get_item(f"ma{period}")
        if item:
            item.setVisible(checked)
            self._main_widget.update()
        self._refresh_ma_values(
            self._main_widget.get_cursor_index() if self._main_widget else 0
        )

    def _on_overlay_toggled(self, item_name: str, checked: bool) -> None:
        if not self._main_widget:
            return
        item = self._main_widget.get_item(item_name)
        if item:
            item.setVisible(checked)
            self._main_widget.update()
        self._refresh_ma_values(
            self._main_widget.get_cursor_index() if self._main_widget else 0
        )

    def _on_sub_toggled(self, index: int, checked: bool) -> None:
        if self._syncing:
            return
        if checked:
            if index not in self._selected_order:
                if len(self._selected_order) >= MAX_VISIBLE_SUB_CHARTS:
                    to_remove = self._selected_order[MAX_VISIBLE_SUB_CHARTS - 1]
                    self._selected_order.pop(MAX_VISIBLE_SUB_CHARTS - 1)
                    self._syncing = True
                    self._sub_btns[to_remove].setChecked(False)
                    self._sub_slots[to_remove].setVisible(False)
                    self._syncing = False
                self._selected_order.append(index)
            if 0 <= index < len(self._sub_slots):
                self._sub_slots[index].setVisible(True)
        else:
            if index in self._selected_order:
                self._selected_order.remove(index)
            if 0 <= index < len(self._sub_slots):
                self._sub_slots[index].setVisible(False)
        self._update_sub_area_height()
        self._relink_x_axes()
        if self._main_widget:
            ix = self._main_widget.get_cursor_index()
            slot = self._sub_slots[index] if 0 <= index < len(self._sub_slots) else None
            if slot and checked:
                slot.set_cursor_x(ix)
                slot.refresh_info(ix)

    def _on_trade_filter_changed(self, text: str) -> None:
        """下拉框切换时更新过滤条件并重绘交易标记。"""
        self._trade_filter = text if text in ("全部", "做多", "做空", "盈利", "亏损") else "隐藏"
        self._draw_trades()

    def _on_add_indicator_clicked(self) -> None:
        """点击 '+' 按钮弹出指标配置对话框，确认后动态添加副图槽位。"""
        dlg = _IndicatorConfigDialog(INDICATOR_SCHEMAS, self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        config = dlg.get_config()
        if config:
            self._add_dynamic_slot(config)

    def _add_dynamic_slot(self, config: tuple) -> None:
        """动态创建副图槽位并追加按钮到底部选择栏。"""
        idx = len(self._sub_slots)

        slot = _SubSlot(config, self._sub_area)
        slot.setVisible(False)
        self._sub_slots.append(slot)
        self._sub_layout.addWidget(slot, stretch=1)

        if self._updated and hasattr(self, "_history"):
            slot.chart.update_history(self._history)

        self._relink_x_axes()

        slot.chart.cursor_index_changed.connect(
            lambda ix, s=slot: self._on_sub_cursor_changed(ix, s)
        )

        display_label, *_ = config
        btn = _IndicatorButton(display_label)
        btn.toggled.connect(lambda checked, i=idx: self._on_sub_toggled(i, checked))
        btn.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(
            lambda pos, b=btn: self._show_dynamic_slot_menu(b, pos)
        )
        self._sub_btns.append(btn)

        layout = self._sub_selector_layout
        layout.takeAt(layout.count() - 1)
        layout.addWidget(btn)
        layout.addStretch()

        btn.setChecked(True)

    def _show_dynamic_slot_menu(self, btn: "_IndicatorButton", pos: QtCore.QPoint) -> None:
        """右键点击动态指标按钮时显示删除菜单。"""
        try:
            idx = self._sub_btns.index(btn)
        except ValueError:
            return
        if idx < len(SUB_INDICATOR_CONFIGS):
            return
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{"
            f"  background: {BG_TOOLBAR};"
            f"  color: {TEXT_INFO};"
            f"  border: 1px solid {BORDER};"
            f"  font-size: 12px;"
            f"}}"
            f"QMenu::item:selected {{"
            f"  background: {BTN_CHECKED};"
            f"  color: {TEXT_WHITE};"
            f"}}"
        )
        delete_action = menu.addAction("删除副图")
        if menu.exec(btn.mapToGlobal(pos)) == delete_action:
            self._remove_dynamic_slot(idx)

    def _remove_dynamic_slot(self, idx: int) -> None:
        """删除动态添加的副图槽位及对应按钮，并修正后续槽位的索引绑定。"""
        if idx < len(SUB_INDICATOR_CONFIGS):
            return

        # 从 selected_order 移除，并将后续索引减一
        if idx in self._selected_order:
            self._selected_order.remove(idx)
        self._selected_order = [
            (i - 1 if i > idx else i) for i in self._selected_order
        ]

        # 移除槽位 widget
        slot = self._sub_slots.pop(idx)
        slot.setVisible(False)
        self._sub_layout.removeWidget(slot)
        slot.deleteLater()

        # 移除按钮 widget
        btn = self._sub_btns.pop(idx)
        self._sub_selector_layout.removeWidget(btn)
        btn.deleteLater()

        # 重新连接从 idx 开始的所有动态按钮的 toggled 信号（索引已移位）
        for i in range(idx, len(self._sub_btns)):
            self._sub_btns[i].toggled.disconnect()
            self._sub_btns[i].toggled.connect(
                lambda checked, ii=i: self._on_sub_toggled(ii, checked)
            )

        self._update_sub_area_height()
        self._relink_x_axes()

    # ── 辅助方法 ──────────────────────────────────────────────────

    def _update_sub_area_height(self) -> None:
        """根据当前选中的副图（_selected_order）累加目标高度，约束 _sub_area 最大高度。

        不能用 slot.isVisible()：顶层窗口尚未 show 时，子控件即使已 setVisible(True)，
        isVisible() 仍可能为 False，会导致 total_h=0、setMaximumHeight(0)，副图区被压没。"""
        total_h = sum(
            self._sub_slots[i].target_height
            for i in self._selected_order
            if 0 <= i < len(self._sub_slots)
        )
        self._sub_area.setMaximumHeight(total_h if total_h > 0 else 0)

    def _relink_x_axes(self) -> None:
        if not self._main_widget:
            return
        main_plot = self._main_widget.get_plot("candle")
        if not main_plot:
            return
        for slot in self._sub_slots:
            plots = slot.chart.get_all_plots()
            if plots:
                plots[0].setXLink(main_plot)

    def _refresh_ohlcv(self, ix: int) -> None:
        if not self._main_widget or not self._ohlcv_label:
            return
        bar: BarData | None = self._main_widget.get_bar(ix)
        if not bar:
            return
        vol = bar.volume
        if vol >= 1e8:
            vol_str = f"{vol/1e8:.2f}亿"
        elif vol >= 1e4:
            vol_str = f"{vol/1e4:.1f}万"
        else:
            vol_str = f"{vol:.0f}"
        self._ohlcv_base_text = (
            f"{bar.datetime:%Y-%m-%d %H:%M}"
            f"  开盘:{bar.open_price}"
            f"  最高:{bar.high_price}"
            f"  最低:{bar.low_price}"
            f"  收盘:{bar.close_price}"
            f"  成交量:{vol_str}"
        )
        self._ohlcv_label.setText(self._ohlcv_base_text)

    def _refresh_ma_values(self, ix: int) -> None:
        if not self._main_widget or not self._ma_values_label:
            return
        parts: list[str] = []
        for period in (5, 10, 20, 30, 60):
            item = self._main_widget.get_item(f"ma{period}")
            if item and item.isVisible():
                text = item.get_info_text(ix)
                if text and ":" in text:
                    val = text.split(":", 1)[1].strip()
                    color = MA_COLORS.get(period, TEXT_NORMAL)
                    parts.append(
                        f'<span style="color:{color};">MA{period}:{val}</span>'
                    )
        boll = self._main_widget.get_item("boll")
        if boll and boll.isVisible():
            segs = getattr(boll, "get_info_text_segments", None)
            segment_list = segs(ix) if segs is not None else None
            if segment_list:
                boll_html = "  ".join(
                    f'<span style="color:{color_rgb_to_hex(c)}">{t}</span>'
                    for t, c in segment_list
                )
                parts.append(boll_html)
            else:
                text = boll.get_info_text(ix)
                if text:
                    flat = "  ".join(t for t in text.split("\n") if t.strip())
                    parts.append(
                        f'<span style="color:{BOLL_COLOR};">BOLL  {flat}</span>'
                    )
        self._ma_values_label.setText("  ".join(parts))

    def _refresh_trade_info(self, ix: int) -> None:
        """将当前 bar 所在持仓区间的完整交易对信息显示在固定宽度的交易信息区。"""
        if not hasattr(self, "_trade_info_label") or not self._trade_info_label:
            return
        pairs = self._bar_trade_map.get(ix, [])
        if not pairs or self._trade_filter == "隐藏":
            self._trade_info_label.setText("")
            return

        # 按 trade_filter 过滤方向/盈亏
        if self._trade_filter == "做多":
            pairs = [p for p in pairs if p["direction"] == Direction.LONG]
        elif self._trade_filter == "做空":
            pairs = [p for p in pairs if p["direction"] == Direction.SHORT]
        elif self._trade_filter == "盈利":
            pairs = [p for p in pairs if self._is_pair_profit(p)]
        elif self._trade_filter == "亏损":
            pairs = [p for p in pairs if not self._is_pair_profit(p)]

        if not pairs:
            self._trade_info_label.setText("")
            return

        parts: list[str] = []
        for pair in pairs:
            direction = pair["direction"]
            open_price = pair["open_price"]
            close_price = pair["close_price"]
            volume = pair["volume"]

            if direction == Direction.LONG:
                dir_color = TRADE_COLORS["long_open"]
                dir_str = "多头"
                pnl = (close_price - open_price) * volume
            else:
                dir_color = TRADE_COLORS["short_open"]
                dir_str = "空头"
                pnl = (open_price - close_price) * volume

            pnl_color = TRADE_COLORS["pnl_profit"] if pnl >= 0 else TRADE_COLORS["pnl_loss"]
            sign = "+" if pnl >= 0 else ""
            parts.append(
                f'<span style="color:{dir_color};">{dir_str}</span>'
                f'  开:{open_price} → 平:{close_price}'
                f'  手数:{volume}'
                f'  <span style="color:{pnl_color};">盈亏:{sign}{pnl:.2f}</span>'
            )

        self._trade_info_label.setText("  |  ".join(parts))

    # ── 回测交易绘制 ──────────────────────────────────────────────

    def _is_pair_profit(self, pair: dict) -> bool:
        """判断交易对是否盈利。"""
        if pair["direction"] == Direction.LONG:
            return pair["close_price"] >= pair["open_price"]
        else:
            return pair["close_price"] <= pair["open_price"]

    def _clear_trade_items(self) -> None:
        """清除主图上的所有回测交易图元。"""
        if not self._main_widget:
            return
        candle_plot: pg.PlotItem = self._main_widget.get_plot("candle")
        if candle_plot:
            for item in self._trade_items:
                candle_plot.removeItem(item)
        self._trade_items.clear()

    def _draw_trades(self) -> None:
        """根据当前过滤条件重绘回测交易标记。"""
        self._clear_trade_items()

        if self._trade_filter == "隐藏" or not self._trade_pairs:
            return

        if not self._main_widget:
            return

        candle_plot: pg.PlotItem = self._main_widget.get_plot("candle")
        if not candle_plot:
            return

        # 按过滤条件筛选交易对
        if self._trade_filter == "做多":
            pairs = [p for p in self._trade_pairs if p["direction"] == Direction.LONG]
        elif self._trade_filter == "做空":
            pairs = [p for p in self._trade_pairs if p["direction"] == Direction.SHORT]
        elif self._trade_filter == "盈利":
            pairs = [p for p in self._trade_pairs if self._is_pair_profit(p)]
        elif self._trade_filter == "亏损":
            pairs = [p for p in self._trade_pairs if not self._is_pair_profit(p)]
        else:
            pairs = self._trade_pairs

        # 偏移量：至少 0.3% 价格幅度，确保箭头明显离开 K 线上下影线
        y_adj: float = max(self._price_range * 0.003, 1.0) if self._price_range else 1.0

        scatter_data: list = []

        for pair in pairs:
            open_ix = self._dt_ix_map.get(pair["open_dt"])
            close_ix = self._dt_ix_map.get(pair["close_dt"])
            if open_ix is None or close_ix is None:
                continue

            open_bar: BarData = self._ix_bar_map.get(open_ix)
            close_bar: BarData = self._ix_bar_map.get(close_ix)
            if not open_bar or not close_bar:
                continue

            open_price = pair["open_price"]
            close_price = pair["close_price"]
            direction = pair["direction"]
            volume = pair["volume"]

            # ── 连线（盈亏色虚线）──────────────────────────────────
            if direction == Direction.LONG:
                is_profit = close_price >= open_price
            else:
                is_profit = close_price <= open_price
            line_color = TRADE_COLORS["pnl_profit"] if is_profit else TRADE_COLORS["pnl_loss"]
            pen = pg.mkPen(
                QtGui.QColor(line_color),
                width=1.5,
                style=QtCore.Qt.PenStyle.DashLine,
            )
            curve = pg.PlotCurveItem(
                [open_ix, close_ix],
                [open_price, close_price],
                pen=pen,
            )
            self._trade_items.append(curve)
            candle_plot.addItem(curve)

            # ── 箭头 ──────────────────────────────────────────────
            if direction == Direction.LONG:
                open_color = TRADE_COLORS["long_open"]
                close_color = TRADE_COLORS["long_close"]
                # 开仓：实心向上三角，低点下方
                open_y = open_bar.low_price - y_adj
                open_symbol = "t1"
                # 平仓：向下三角，高点上方
                close_y = close_bar.high_price + y_adj
                close_symbol = "t"
            else:
                open_color = TRADE_COLORS["short_open"]
                close_color = TRADE_COLORS["short_close"]
                # 开仓：实心向下三角，高点上方
                open_y = open_bar.high_price + y_adj
                open_symbol = "t"
                # 平仓：向上三角，低点下方
                close_y = close_bar.low_price - y_adj
                close_symbol = "t1"

            # 开仓：实心三角，去掉描边，颜色纯粹
            open_pen = pg.mkPen(None)
            open_brush = pg.mkBrush(QtGui.QColor(open_color))
            # 平仓：空心三角，加粗描边 width=2，无填充
            close_pen = pg.mkPen(QtGui.QColor(close_color), width=2)
            close_brush = pg.mkBrush(QtGui.QColor(0, 0, 0, 0))

            scatter_data.append({
                "pos": (open_ix, open_y),
                "size": 14,
                "pen": open_pen,
                "brush": open_brush,
                "symbol": open_symbol,
            })
            scatter_data.append({
                "pos": (close_ix, close_y),
                "size": 14,
                "pen": close_pen,
                "brush": close_brush,
                "symbol": close_symbol,
            })


        if scatter_data:
            scatter = pg.ScatterPlotItem(scatter_data)
            self._trade_items.append(scatter)
            candle_plot.addItem(scatter)

    # ── 公开接口 ──────────────────────────────────────────────────

    def update_history(self, history: list[BarData]) -> None:
        """加载 K 线历史数据。"""
        self._updated = True
        self._history: list[BarData] = history

        # 自建 dt→ix 和 ix→bar 映射（用于回测交易定位）
        self._dt_ix_map.clear()
        self._ix_bar_map.clear()
        high_price = 0.0
        low_price = 0.0
        for ix, bar in enumerate(history):
            self._dt_ix_map[bar.datetime] = ix
            self._ix_bar_map[ix] = bar
            if not high_price:
                high_price = bar.high_price
                low_price = bar.low_price
            else:
                high_price = max(high_price, bar.high_price)
                low_price = min(low_price, bar.low_price)
        self._price_range = high_price - low_price

        if self._main_widget:
            self._main_widget.update_history(history)
        for slot in self._sub_slots:
            slot.chart.update_history(history)
        self._relink_x_axes()

        if self._main_widget:
            ix = self._main_widget.get_cursor_index()
            self._refresh_ohlcv(ix)
            self._refresh_ma_values(ix)
            for slot in self._sub_slots:
                if slot.isVisible():
                    slot.refresh_info(ix)

    def update_bar(self, bar: BarData) -> None:
        """实时追加单根 K 线。"""
        if self._main_widget:
            self._main_widget.update_bar(bar)
        for slot in self._sub_slots:
            slot.chart.update_bar(bar)
        if self._main_widget:
            ix = self._main_widget.get_cursor_index()
            self._refresh_ohlcv(ix)
            self._refresh_ma_values(ix)
            for slot in self._sub_slots:
                if slot.isVisible():
                    slot.refresh_info(ix)

    def update_trades(self, trades: list) -> None:
        """传入 TradeData 列表，配对后在主图叠加开平仓标记。"""
        self._trade_pairs = generate_trade_pairs(trades)

        # 构建 bar index → trade_pair 列表（持仓区间内每根 bar 都记录完整 pair）
        self._bar_trade_map.clear()
        for pair in self._trade_pairs:
            open_ix = self._dt_ix_map.get(pair["open_dt"])
            close_ix = self._dt_ix_map.get(pair["close_dt"])
            if open_ix is None or close_ix is None:
                continue
            for ix in range(open_ix, close_ix + 1):
                self._bar_trade_map.setdefault(ix, []).append(pair)

        self._draw_trades()

    def clear_data(self) -> None:
        """清空图表数据和交易标记。"""
        self._updated = False
        self._clear_trade_items()
        self._trade_pairs.clear()
        self._bar_trade_map.clear()
        self._dt_ix_map.clear()
        self._ix_bar_map.clear()
        self._price_range = 0.0
        if self._main_widget:
            self._main_widget.clear_all()

    def is_updated(self) -> bool:
        """是否已通过 update_history() 加载过数据。"""
        return self._updated
