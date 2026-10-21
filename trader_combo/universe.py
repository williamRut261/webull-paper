"""Explicit reviewable liquid stock/ETF candidate universe.

The upstream Trader scanner normally excludes ETFs when discovering listings;
explicit --symbols allows ETF symbols, and we exclude every Beethoven input or
eligible original holding to avoid cross-strategy position ownership.
"""
from strategy_engine import ORIGINAL_EXECUTION_ASSETS, load_strategy, signal_symbols

STOCKS = """
ADBE AMAT AMD AMGN ANET ARM ASML BA BAC BMY CAT CCL CEG CELH
CHWY CMG COIN COST CRM CRWD CSCO CVS DAL DE DELL DIS DOCU
DUOL F FDX GME GM GS HD HIMS IBM INTC ISRG JPM KHC KO
LLY LMT LOW LRCX MCD MCHP MSTR NFLX NKE NOW NVO
ORCL PANW PEP PFE PINS PYPL RBLX RCL RDDT RIVN ROKU
SBUX SHOP SNAP SNOW SQ T TGT TMO U UBER UNH UPS
VZ WFC WMT XOM ZM ZS
"""
ETFS = """
ARKK ARKG ARKW DIA EEM EFA EIDO EMB ERX ERY
EWJ EWW FXI GDX GLD HYG IAU IBB IEF IJH IJR IWM
JETS KRE LQD MCHI QQQM RSP SCHD SCHG SCHX
SHY SIL SMH SOXX SPYD SPLG SPTM TAN TBT TNA TZA
UNG USO VOO VTI VTV VUG VWO XBI XES XHB XLE
XLI XLP XLU XLV XLY XME XOP XRT XSD
"""
SOURCE = frozenset(STOCKS.split()) | frozenset(ETFS.split())
EXCLUDED = frozenset(ORIGINAL_EXECUTION_ASSETS) | frozenset(signal_symbols(load_strategy()))
CANDIDATES = frozenset(SOURCE - EXCLUDED)
MAX_SYMBOLS = 180
MAX_POSITIONS = 3
BEETHOVEN_WEIGHT = 0.80
TRADER_WEIGHT = 0.19
MAX_TOTAL_EXPOSURE = 0.99
MAX_TRADE_LOSS_FRACTION = 0.003  # estimated stop risk, not guaranteed fill
MAX_STOP_DISTANCE = 0.035
MIN_STOP_DISTANCE = 0.004

if not CANDIDATES or len(CANDIDATES) > MAX_SYMBOLS:
    raise RuntimeError("Unexpected Trader scanner candidate count")
if CANDIDATES & EXCLUDED:
    raise RuntimeError("Scanner ticker overlaps Beethoven strategy")
if abs(BEETHOVEN_WEIGHT + TRADER_WEIGHT - MAX_TOTAL_EXPOSURE) > 1e-9:
    raise RuntimeError("Combined allocations exceed 99%")
