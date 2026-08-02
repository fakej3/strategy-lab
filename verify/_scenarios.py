"""Hand-calculated golden scenarios for the Verification Framework.

Every scenario has explicitly computed expected values derived from the
engine's documented fill formulas.  No production code is referenced here.

Fill formulas (from engine/executor.py docstrings):
  entry_fill  = raw_open  * (1 + slippage_pct)
  exit_fill   = raw_exit  * (1 - slippage_pct)
  entry_fee   = entry_fill * size * fee_rate
  exit_fee    = exit_fill  * size * fee_rate
  gross_pnl   = (exit_fill - entry_fill) * size
  net_pnl     = gross_pnl - entry_fee - exit_fee
  holding_period = exit_bar - entry_bar

Equity curve (bars are 0-indexed):
  flat bar  i           : starting_capital + cumulative_realized
  in-pos bar i (entry ≤ i < exit): starting_capital + realized + (close_i - entry_fill)*size
  exit bar  i           : starting_capital + realized + net_pnl   [then realized += net_pnl]
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ExpectedTrade:
    entry_bar     : int
    exit_bar      : int
    entry_price   : float   # fill price after slippage
    exit_price    : float   # fill price after slippage
    gross_pnl     : float
    net_pnl       : float
    entry_fee     : float
    exit_fee      : float
    holding_period: int
    exit_reason   : str     # "signal" | "stop_loss" | "take_profit" | "end_of_data"


@dataclass
class GoldenScenario:
    name          : str
    description   : str
    bars          : list[tuple[float, float, float, float]]  # (open, high, low, close)
    signals       : list[str]
    fee_rate      : float        = 0.0
    slippage_pct  : float        = 0.0
    position_size : float        = 1.0
    stop_loss_pct : float | None = None
    take_profit_pct: float | None = None
    starting_capital: float      = 10_000.0
    expected_trades : list[ExpectedTrade] = field(default_factory=list)
    expected_equity : list[float]         = field(default_factory=list)


# ── Scenario definitions ───────────────────────────────────────────────────────

S01_WINNER_NO_COSTS = GoldenScenario(
    name        = "S01_winner_no_costs",
    description = "Single winning trade; zero fees and slippage; verifies basic fill and equity.",
    bars = [
        (100, 102, 99, 100),   # bar0: open=100 → BUY signal
        (100, 108, 98, 102),   # bar1: raw_open=100 → entry fill=100; close=102
        (102, 112, 100, 107),  # bar2: hold; close=107
        (115, 118, 112, 116),  # bar3: raw_open=115 → exit fill=115
        (116, 119, 114, 117),  # bar4: flat
    ],
    signals = ["BUY", "HOLD", "EXIT", "HOLD", "HOLD"],
    # entry_fill=100, exit_fill=115, gross=15, net=15
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=3,
        entry_price=100.0, exit_price=115.0,
        gross_pnl=15.0, net_pnl=15.0,
        entry_fee=0.0, exit_fee=0.0,
        holding_period=2, exit_reason="signal",
    )],
    # equity: 10000, 10002, 10007, 10015, 10015
    expected_equity = [10000.0, 10002.0, 10007.0, 10015.0, 10015.0],
)


S02_LOSER_NO_COSTS = GoldenScenario(
    name        = "S02_loser_no_costs",
    description = "Single losing trade; zero costs; verifies negative PnL and drawdown.",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 106, 98, 103),   # bar1: entry=100; close=103
        (103, 110, 101, 108),  # bar2: hold; close=108
        (108, 112, 105, 110),  # bar3: EXIT signal
        (90,  94,  87,  92),   # bar4: raw_open=90 → exit fill=90
        (90,  93,  88,  91),   # bar5: flat
    ],
    signals = ["BUY", "HOLD", "HOLD", "EXIT", "HOLD", "HOLD"],
    # gross=(90-100)*1=-10, net=-10
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=4,
        entry_price=100.0, exit_price=90.0,
        gross_pnl=-10.0, net_pnl=-10.0,
        entry_fee=0.0, exit_fee=0.0,
        holding_period=3, exit_reason="signal",
    )],
    # equity: 10000, 10003, 10008, 10010, 9990, 9990
    expected_equity = [10000.0, 10003.0, 10008.0, 10010.0, 9990.0, 9990.0],
)


S03_FEES_ONLY = GoldenScenario(
    name        = "S03_fees_only",
    description = "Entry and exit fees applied; no slippage; verifies fee deduction formula.",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 108, 98, 105),   # bar1: entry raw=100
        (110, 115, 108, 112),  # bar2: EXIT signal
        (110, 115, 108, 113),  # bar3: exit raw=110
    ],
    signals     = ["BUY", "HOLD", "EXIT", "HOLD"],
    fee_rate    = 0.001,
    # entry_fill=100, entry_fee=100*1*0.001=0.1
    # exit_fill=110,  exit_fee=110*1*0.001=0.11
    # gross=10, net=10-0.1-0.11=9.79
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=3,
        entry_price=100.0, exit_price=110.0,
        gross_pnl=10.0, net_pnl=9.79,
        entry_fee=0.1, exit_fee=0.11,
        holding_period=2, exit_reason="signal",
    )],
    expected_equity = [10000.0, 10005.0, 10012.0, 10009.79],
)


S04_SLIPPAGE_ONLY = GoldenScenario(
    name        = "S04_slippage_only",
    description = "Slippage on both sides; no fees; verifies slippage-adjusted fill prices.",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 108, 98, 105),   # bar1: entry raw=100
        (110, 115, 108, 112),  # bar2: EXIT signal
        (110, 115, 108, 113),  # bar3: exit raw=110
    ],
    signals      = ["BUY", "HOLD", "EXIT", "HOLD"],
    slippage_pct = 0.001,
    # entry_fill=100*1.001=100.1
    # exit_fill=110*0.999=109.89
    # gross=(109.89-100.1)*1=9.79, net=9.79
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=3,
        entry_price=100.1, exit_price=109.89,
        gross_pnl=9.79, net_pnl=9.79,
        entry_fee=0.0, exit_fee=0.0,
        holding_period=2, exit_reason="signal",
    )],
    # bar1 unrealized: (105-100.1)*1=4.9 → equity=10004.9
    # bar2 unrealized: (112-100.1)*1=11.9 → equity=10011.9
    # bar3 exit: equity=10000+9.79=10009.79
    expected_equity = [10000.0, 10004.9, 10011.9, 10009.79],
)


S05_SL_ENTRY_BAR = GoldenScenario(
    name        = "S05_sl_entry_bar",
    description = "SL fires on entry bar (holding_period=0); verifies same-bar SL exit.",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 108, 80,  90),   # bar1: entry=100; SL=95; bar1.low=80≤95 → SL fires!
        (95,  100, 93,  98),   # bar2: flat
    ],
    signals         = ["BUY", "HOLD", "HOLD"],
    stop_loss_pct   = 0.05,
    # entry_fill=100, SL=100*0.95=95
    # bar1.low=80 ≤ 95 → SL fires; raw=min(95,bar1.open=100)=95
    # exit_fill=95, gross=-5, net=-5, holding_period=0
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=1,
        entry_price=100.0, exit_price=95.0,
        gross_pnl=-5.0, net_pnl=-5.0,
        entry_fee=0.0, exit_fee=0.0,
        holding_period=0, exit_reason="stop_loss",
    )],
    # bar0: flat=10000
    # bar1: exit_bar=1=entry_bar → unrealized block skipped; equity=10000+(-5)=9995
    # bar2: flat=9995
    expected_equity = [10000.0, 9995.0, 9995.0],
)


S06_SL_GAP_DOWN = GoldenScenario(
    name        = "S06_sl_gap_down",
    description = "Bar opens below SL; fill at bar_open (gap-down semantics).",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 106, 97, 103),   # bar1: entry=100; SL=95; bar1.low=97>95 → no trigger
        (90,  95,  85,  92),   # bar2: bar2.open=90<95; bar2.low=85≤95 → gap-down SL!
        (92,  96,  89,  93),   # bar3: flat
    ],
    signals       = ["BUY", "HOLD", "HOLD", "HOLD"],
    stop_loss_pct = 0.05,
    # entry_fill=100, SL=95
    # bar2: sl fires; raw=min(95,90)=90; exit_fill=90
    # gross=-10, net=-10, holding_period=1
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=2,
        entry_price=100.0, exit_price=90.0,
        gross_pnl=-10.0, net_pnl=-10.0,
        entry_fee=0.0, exit_fee=0.0,
        holding_period=1, exit_reason="stop_loss",
    )],
    # bar0: 10000
    # bar1: unrealized=(103-100)*1=3 → 10003
    # bar2: exit → 10000-10=9990
    # bar3: 9990
    expected_equity = [10000.0, 10003.0, 9990.0, 9990.0],
)


S07_TP_EXACT = GoldenScenario(
    name        = "S07_tp_exact",
    description = "TP fires at exact level (bar open below TP); fill at TP price.",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 106, 97, 103),   # bar1: entry=100; TP=110; bar1.high=106<110 → no trigger
        (105, 118, 103, 115),  # bar2: bar2.high=118≥110; open=105<110 → fill=max(110,105)=110
        (111, 115, 109, 113),  # bar3: flat
    ],
    signals          = ["BUY", "HOLD", "HOLD", "HOLD"],
    take_profit_pct  = 0.10,
    # entry_fill=100, TP=110
    # bar2: tp fires; raw=max(110,105)=110; exit_fill=110
    # gross=10, net=10, holding_period=1
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=2,
        entry_price=100.0, exit_price=110.0,
        gross_pnl=10.0, net_pnl=10.0,
        entry_fee=0.0, exit_fee=0.0,
        holding_period=1, exit_reason="take_profit",
    )],
    # bar0: 10000
    # bar1: unrealized=(103-100)*1=3 → 10003
    # bar2: exit → 10000+10=10010
    # bar3: 10010
    expected_equity = [10000.0, 10003.0, 10010.0, 10010.0],
)


S08_TP_GAP_UP = GoldenScenario(
    name        = "S08_tp_gap_up",
    description = "Bar opens above TP (gap-up); fill at bar_open (better price for seller).",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 106, 97, 103),   # bar1: entry=100; TP=110
        (125, 132, 122, 128),  # bar2: open=125>110; bar2.high=132≥110 → gap-up TP!
        (126, 130, 124, 128),  # bar3: flat
    ],
    signals          = ["BUY", "HOLD", "HOLD", "HOLD"],
    take_profit_pct  = 0.10,
    # bar2: tp fires; raw=max(110,125)=125; exit_fill=125
    # gross=25, net=25, holding_period=1
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=2,
        entry_price=100.0, exit_price=125.0,
        gross_pnl=25.0, net_pnl=25.0,
        entry_fee=0.0, exit_fee=0.0,
        holding_period=1, exit_reason="take_profit",
    )],
    expected_equity = [10000.0, 10003.0, 10025.0, 10025.0],
)


S09_END_OF_DATA = GoldenScenario(
    name        = "S09_end_of_data",
    description = "Position open at last bar; liquidated at last bar close.",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 106, 97, 103),   # bar1: entry=100; HOLD
        (103, 110, 101, 108),  # bar2: HOLD (last bar) → exit at close=108
    ],
    signals = ["BUY", "HOLD", "HOLD"],
    # end-of-data: raw_exit=bar2.close=108, exit_fill=108
    # gross=8, net=8, holding_period=1, exit_reason=end_of_data
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=2,
        entry_price=100.0, exit_price=108.0,
        gross_pnl=8.0, net_pnl=8.0,
        entry_fee=0.0, exit_fee=0.0,
        holding_period=1, exit_reason="end_of_data",
    )],
    expected_equity = [10000.0, 10003.0, 10008.0],
)


S10_NO_TRADES = GoldenScenario(
    name        = "S10_no_trades",
    description = "All HOLD signals; no trades generated; equity stays flat.",
    bars = [
        (100, 102, 99, 100),
        (100, 106, 97, 103),
        (103, 108, 101, 106),
    ],
    signals          = ["HOLD", "HOLD", "HOLD"],
    expected_trades  = [],
    expected_equity  = [10000.0, 10000.0, 10000.0],
)


S11_SL_TP_SAME_BAR_SL_WINS = GoldenScenario(
    name        = "S11_sl_tp_same_bar_sl_wins",
    description = "SL and TP both triggered on the same bar; SL takes priority.",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 140, 75, 100),   # bar1: SL=95, TP=110; low=75≤95 AND high=140≥110 → SL wins
        (98,  102, 95,  99),   # bar2: flat
    ],
    signals          = ["BUY", "HOLD", "HOLD"],
    stop_loss_pct    = 0.05,
    take_profit_pct  = 0.10,
    # SL fires; raw=min(95,100)=95; exit=95; gross=-5, net=-5, holding_period=0
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=1,
        entry_price=100.0, exit_price=95.0,
        gross_pnl=-5.0, net_pnl=-5.0,
        entry_fee=0.0, exit_fee=0.0,
        holding_period=0, exit_reason="stop_loss",
    )],
    expected_equity = [10000.0, 9995.0, 9995.0],
)


S12_TWO_TRADES_COMPOUNDING = GoldenScenario(
    name        = "S12_two_trades_compounding",
    description = "Two consecutive trades; equity accumulates realized PnL between them.",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY (trade1)
        (100, 108, 98, 105),   # bar1: entry1=100; close=105
        (105, 114, 103, 112),  # bar2: EXIT; close=112
        (115, 120, 112, 117),  # bar3: exit1=115; BUY (trade2)
        (115, 122, 112, 118),  # bar4: entry2=115; close=118
        (118, 126, 116, 123),  # bar5: EXIT; close=123
        (125, 130, 122, 127),  # bar6: exit2=125; HOLD
        (126, 130, 124, 128),  # bar7: flat
    ],
    signals = ["BUY", "HOLD", "EXIT", "BUY", "HOLD", "EXIT", "HOLD", "HOLD"],
    # trade1: entry=100, exit=115, net=15
    # trade2: entry=115, exit=125, net=10
    expected_trades = [
        ExpectedTrade(
            entry_bar=1, exit_bar=3,
            entry_price=100.0, exit_price=115.0,
            gross_pnl=15.0, net_pnl=15.0,
            entry_fee=0.0, exit_fee=0.0,
            holding_period=2, exit_reason="signal",
        ),
        ExpectedTrade(
            entry_bar=4, exit_bar=6,
            entry_price=115.0, exit_price=125.0,
            gross_pnl=10.0, net_pnl=10.0,
            entry_fee=0.0, exit_fee=0.0,
            holding_period=2, exit_reason="signal",
        ),
    ],
    # equity:
    # bar0: 10000 (flat)
    # bar1: 10000+(105-100)*1=10005
    # bar2: 10000+(112-100)*1=10012
    # bar3: 10000+15=10015 (trade1 exit)
    # bar4: 10015+(118-115)*1=10018
    # bar5: 10015+(123-115)*1=10023
    # bar6: 10015+10=10025 (trade2 exit)
    # bar7: 10025 (flat)
    expected_equity = [10000.0, 10005.0, 10012.0, 10015.0, 10018.0, 10023.0, 10025.0, 10025.0],
)


S13_FEES_AND_SLIPPAGE = GoldenScenario(
    name        = "S13_fees_and_slippage",
    description = "Both fees and slippage applied; verifies combined cost formula.",
    bars = [
        (1000, 1010, 990, 1000),   # bar0: BUY
        (1000, 1050, 980, 1020),   # bar1: entry raw=1000
        (1100, 1150, 1080, 1120),  # bar2: EXIT signal
        (1100, 1155, 1085, 1130),  # bar3: exit raw=1100
    ],
    signals      = ["BUY", "HOLD", "EXIT", "HOLD"],
    fee_rate     = 0.001,
    slippage_pct = 0.0005,
    # entry_fill = 1000*1.0005 = 1000.5
    # entry_fee  = 1000.5*1*0.001 = 1.0005
    # exit_fill  = 1100*0.9995 = 1099.45
    # exit_fee   = 1099.45*1*0.001 = 1.09945
    # gross = (1099.45-1000.5)*1 = 98.95
    # net   = 98.95 - 1.0005 - 1.09945 = 96.85005
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=3,
        entry_price=1000.5, exit_price=1099.45,
        gross_pnl=98.95, net_pnl=96.85005,
        entry_fee=1.0005, exit_fee=1.09945,
        holding_period=2, exit_reason="signal",
    )],
    # bar0: 10000
    # bar1: 10000+(1020-1000.5)*1=10019.5
    # bar2: 10000+(1120-1000.5)*1=10119.5
    # bar3: 10000+96.85005=10096.85005
    expected_equity = [10000.0, 10019.5, 10119.5, 10096.85005],
)


S14_EXIT_FILLS_NEXT_BAR = GoldenScenario(
    name        = "S14_exit_fills_next_bar",
    description = "EXIT signal fills at T+1 open; verifies no same-bar fill (lookahead guard).",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 108, 98, 105),   # bar1: entry=100; EXIT signal here
        (200, 205, 195, 202),  # bar2: exit fills at bar2.open=200 (deliberate gap)
        (202, 206, 200, 204),  # bar3: flat
    ],
    signals = ["BUY", "EXIT", "HOLD", "HOLD"],
    # exit fills at bar2.open=200, not bar1's close=105
    # gross=(200-100)*1=100, net=100
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=2,
        entry_price=100.0, exit_price=200.0,
        gross_pnl=100.0, net_pnl=100.0,
        entry_fee=0.0, exit_fee=0.0,
        holding_period=1, exit_reason="signal",
    )],
    # bar0: 10000
    # bar1: unrealized=(105-100)*1=5 → 10005
    # bar2: exit → 10000+100=10100
    # bar3: 10100
    expected_equity = [10000.0, 10005.0, 10100.0, 10100.0],
)


S15_BUY_WHILE_IN_POSITION = GoldenScenario(
    name        = "S15_buy_while_in_position",
    description = "BUY signal emitted while already long; second BUY is ignored.",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 108, 98, 105),   # bar1: entry=100; BUY (ignored — already long)
        (105, 115, 103, 110),  # bar2: HOLD
        (110, 118, 108, 113),  # bar3: EXIT
        (120, 125, 118, 122),  # bar4: exit=120; flat
        (122, 126, 120, 124),  # bar5: flat
    ],
    signals = ["BUY", "BUY", "HOLD", "EXIT", "HOLD", "HOLD"],
    # Only 1 trade; entry=100, exit=120 at bar4
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=4,
        entry_price=100.0, exit_price=120.0,
        gross_pnl=20.0, net_pnl=20.0,
        entry_fee=0.0, exit_fee=0.0,
        holding_period=3, exit_reason="signal",
    )],
    # bar0: 10000
    # bar1: unrealized=(105-100)*1=5 → 10005
    # bar2: unrealized=(110-100)*1=10 → 10010
    # bar3: unrealized=(113-100)*1=13 → 10013
    # bar4: exit → 10000+20=10020
    # bar5: 10020
    expected_equity = [10000.0, 10005.0, 10010.0, 10013.0, 10020.0, 10020.0],
)


S16_EXIT_WHEN_FLAT = GoldenScenario(
    name        = "S16_exit_when_flat",
    description = "EXIT signal when no position is open; ignored, no trade generated.",
    bars = [
        (100, 102, 99, 100),   # bar0: EXIT (no position)
        (100, 106, 97, 103),   # bar1: HOLD
        (103, 108, 101, 106),  # bar2: HOLD
    ],
    signals         = ["EXIT", "HOLD", "HOLD"],
    expected_trades = [],
    expected_equity = [10000.0, 10000.0, 10000.0],
)


S17_FLAT_MARKET = GoldenScenario(
    name        = "S17_flat_market",
    description = "Entry and exit at the same price; net_pnl=0 (no costs).",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 108, 95, 100),   # bar1: entry=100; HOLD; close=100 (flat)
        (100, 108, 95, 100),   # bar2: EXIT; close=100
        (100, 108, 95, 100),   # bar3: exit=100; flat
    ],
    signals = ["BUY", "HOLD", "EXIT", "HOLD"],
    # gross=0, net=0, is_winner=False, is_loser=False
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=3,
        entry_price=100.0, exit_price=100.0,
        gross_pnl=0.0, net_pnl=0.0,
        entry_fee=0.0, exit_fee=0.0,
        holding_period=2, exit_reason="signal",
    )],
    # bar0: 10000
    # bar1: unrealized=(100-100)*1=0 → 10000
    # bar2: unrealized=(100-100)*1=0 → 10000
    # bar3: exit=10000+0=10000
    expected_equity = [10000.0, 10000.0, 10000.0, 10000.0],
)


S18_LARGE_POSITION = GoldenScenario(
    name        = "S18_large_position",
    description = "Position size=100 units; verifies that all monetary fields scale linearly.",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 108, 98, 105),   # bar1: entry=100; size=100
        (110, 115, 108, 112),  # bar2: EXIT
        (110, 118, 108, 115),  # bar3: exit=110
    ],
    signals       = ["BUY", "HOLD", "EXIT", "HOLD"],
    position_size = 100.0,
    # gross=(110-100)*100=1000, net=1000
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=3,
        entry_price=100.0, exit_price=110.0,
        gross_pnl=1000.0, net_pnl=1000.0,
        entry_fee=0.0, exit_fee=0.0,
        holding_period=2, exit_reason="signal",
    )],
    # bar0: 10000
    # bar1: unrealized=(105-100)*100=500 → 10500
    # bar2: unrealized=(112-100)*100=1200 → 11200
    # bar3: exit → 10000+1000=11000
    expected_equity = [10000.0, 10500.0, 11200.0, 11000.0],
)


S19_SL_NO_GAP = GoldenScenario(
    name        = "S19_sl_no_gap",
    description = "SL fires exactly at stop level (bar opens above SL); fill = SL level.",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 106, 97, 103),   # bar1: entry=100; SL=95; bar1.low=97>95 → no trigger
        (100, 106, 94, 101),   # bar2: bar2.low=94≤95; bar2.open=100>95 → fill at SL=95
        (96,  100, 94,  98),   # bar3: flat
    ],
    signals       = ["BUY", "HOLD", "HOLD", "HOLD"],
    stop_loss_pct = 0.05,
    # bar2: SL fires; raw=min(95,100)=95; exit_fill=95; gross=-5, net=-5
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=2,
        entry_price=100.0, exit_price=95.0,
        gross_pnl=-5.0, net_pnl=-5.0,
        entry_fee=0.0, exit_fee=0.0,
        holding_period=1, exit_reason="stop_loss",
    )],
    # bar0: 10000
    # bar1: unrealized=(103-100)*1=3 → 10003
    # bar2: exit → 10000-5=9995
    # bar3: 9995
    expected_equity = [10000.0, 10003.0, 9995.0, 9995.0],
)


S20_SIZE_2_FEES = GoldenScenario(
    name        = "S20_size_2_fees",
    description = "Size=2 with fees; verifies fees scale with size.",
    bars = [
        (100, 102, 99, 100),   # bar0: BUY
        (100, 108, 98, 105),   # bar1: entry raw=100; size=2
        (110, 115, 108, 112),  # bar2: EXIT
        (110, 118, 108, 115),  # bar3: exit raw=110
    ],
    signals       = ["BUY", "HOLD", "EXIT", "HOLD"],
    fee_rate      = 0.001,
    position_size = 2.0,
    # entry_fill=100, entry_fee=100*2*0.001=0.2
    # exit_fill=110,  exit_fee=110*2*0.001=0.22
    # gross=(110-100)*2=20
    # net=20-0.2-0.22=19.58
    expected_trades = [ExpectedTrade(
        entry_bar=1, exit_bar=3,
        entry_price=100.0, exit_price=110.0,
        gross_pnl=20.0, net_pnl=19.58,
        entry_fee=0.2, exit_fee=0.22,
        holding_period=2, exit_reason="signal",
    )],
    # bar0: 10000
    # bar1: unrealized=(105-100)*2=10 → 10010
    # bar2: unrealized=(112-100)*2=24 → 10024
    # bar3: exit → 10000+19.58=10019.58
    expected_equity = [10000.0, 10010.0, 10024.0, 10019.58],
)


ALL_SCENARIOS: list[GoldenScenario] = [
    S01_WINNER_NO_COSTS,
    S02_LOSER_NO_COSTS,
    S03_FEES_ONLY,
    S04_SLIPPAGE_ONLY,
    S05_SL_ENTRY_BAR,
    S06_SL_GAP_DOWN,
    S07_TP_EXACT,
    S08_TP_GAP_UP,
    S09_END_OF_DATA,
    S10_NO_TRADES,
    S11_SL_TP_SAME_BAR_SL_WINS,
    S12_TWO_TRADES_COMPOUNDING,
    S13_FEES_AND_SLIPPAGE,
    S14_EXIT_FILLS_NEXT_BAR,
    S15_BUY_WHILE_IN_POSITION,
    S16_EXIT_WHEN_FLAT,
    S17_FLAT_MARKET,
    S18_LARGE_POSITION,
    S19_SL_NO_GAP,
    S20_SIZE_2_FEES,
]
