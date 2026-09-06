"""Indian Market Instrument Master & Symbol Registry.

Manages NSE/BSE cash equities, indices, and derivatives instruments.
Enforces survivorship-bias protection (Principle 6) by tracking listing and delisting dates.
"""

from datetime import date
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from data.schemas.contracts import AssetClass, Exchange


class MarketSegment(str, Enum):
    CASH_EQ = "EQ"
    INDEX = "INDEX"
    INDEX_FUT = "FUTIDX"
    STOCK_FUT = "FUTSTK"
    INDEX_OPT = "OPTIDX"
    STOCK_OPT = "OPTSTK"


class Instrument(BaseModel):
    """Authoritative instrument specification."""

    symbol: str
    name: str
    isin: str
    exchange: Exchange
    segment: MarketSegment
    asset_class: AssetClass
    tick_size: float = Field(default=0.05, gt=0, description="Minimum price movement (INR)")
    lot_size: int = Field(default=1, gt=0, description="Contract or order lot size")
    listed_date: date
    delisted_date: Optional[date] = None
    is_active: bool = True
    industry_sector: Optional[str] = None
    underlying_symbol: Optional[str] = None

    def is_tradable_on(self, query_date: date) -> bool:
        """Survivership-bias check: Verifies if the symbol was actively listed and tradable on query_date."""
        if query_date < self.listed_date:
            return False
        if self.delisted_date and query_date > self.delisted_date:
            return False
        return True


class InstrumentRegistry:
    """Registry maintaining current and historically active instruments."""

    def __init__(self):
        self._instruments: Dict[str, Instrument] = {}
        self._load_core_universe()

    def _load_core_universe(self):
        """Initializes canonical Indian market core universe."""
        core_universe = [
            Instrument(
                symbol="NIFTY 50",
                name="NIFTY 50 Index",
                isin="INX000000001",
                exchange=Exchange.NSE,
                segment=MarketSegment.INDEX,
                asset_class=AssetClass.INDEX,
                tick_size=0.05,
                lot_size=25,
                listed_date=date(1996, 4, 22),
            ),
            Instrument(
                symbol="BANKNIFTY",
                name="NIFTY Bank Index",
                isin="INX000000002",
                exchange=Exchange.NSE,
                segment=MarketSegment.INDEX,
                asset_class=AssetClass.INDEX,
                tick_size=0.05,
                lot_size=15,
                listed_date=date(2003, 6, 9),
            ),
            Instrument(
                symbol="RELIANCE",
                name="Reliance Industries Ltd",
                isin="INE002A01018",
                exchange=Exchange.NSE,
                segment=MarketSegment.CASH_EQ,
                asset_class=AssetClass.EQUITY,
                tick_size=0.05,
                lot_size=1,
                listed_date=date(1995, 11, 29),
                industry_sector="Oil Gas & Consumable Fuels",
            ),
            Instrument(
                symbol="TCS",
                name="Tata Consultancy Services Ltd",
                isin="INE467B01029",
                exchange=Exchange.NSE,
                segment=MarketSegment.CASH_EQ,
                asset_class=AssetClass.EQUITY,
                tick_size=0.05,
                lot_size=1,
                listed_date=date(2004, 8, 25),
                industry_sector="Information Technology",
            ),
            Instrument(
                symbol="HDFCBANK",
                name="HDFC Bank Ltd",
                isin="INE040A01034",
                exchange=Exchange.NSE,
                segment=MarketSegment.CASH_EQ,
                asset_class=AssetClass.EQUITY,
                tick_size=0.05,
                lot_size=1,
                listed_date=date(1995, 5, 19),
                industry_sector="Financial Services",
            ),
            Instrument(
                symbol="INFY",
                name="Infosys Ltd",
                isin="INE009A01021",
                exchange=Exchange.NSE,
                segment=MarketSegment.CASH_EQ,
                asset_class=AssetClass.EQUITY,
                tick_size=0.05,
                lot_size=1,
                listed_date=date(1993, 6, 14),
                industry_sector="Information Technology",
            ),
            Instrument(
                symbol="ICICIBANK",
                name="ICICI Bank Ltd",
                isin="INE090A01021",
                exchange=Exchange.NSE,
                segment=MarketSegment.CASH_EQ,
                asset_class=AssetClass.EQUITY,
                tick_size=0.05,
                lot_size=1,
                listed_date=date(1997, 9, 17),
                industry_sector="Financial Services",
            ),
            # Historical delisted instrument sample for survivorship-bias verification
            Instrument(
                symbol="RCOM",
                name="Reliance Communications Ltd (Delisted)",
                isin="INE330H01012",
                exchange=Exchange.NSE,
                segment=MarketSegment.CASH_EQ,
                asset_class=AssetClass.EQUITY,
                tick_size=0.05,
                lot_size=1,
                listed_date=date(2006, 3, 6),
                delisted_date=date(2021, 10, 15),
                is_active=False,
                industry_sector="Telecommunication",
            ),
        ]
        for inst in core_universe:
            self._instruments[inst.symbol] = inst

    def get_instrument(self, symbol: str) -> Optional[Instrument]:
        return self._instruments.get(symbol.upper())

    def list_instruments(self, only_active: bool = False) -> List[Instrument]:
        if only_active:
            return [inst for inst in self._instruments.values() if inst.is_active]
        return list(self._instruments.values())

    def validate_symbol(self, symbol: str) -> bool:
        return symbol.upper() in self._instruments
