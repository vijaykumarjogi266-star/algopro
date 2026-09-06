"""Unit tests for Instrument Master & Survivorship Bias Protection."""

from datetime import date
from services.market_data.instruments import InstrumentRegistry


def test_instrument_registry_lookup():
    reg = InstrumentRegistry()
    rel = reg.get_instrument("RELIANCE")
    assert rel is not None
    assert rel.isin == "INE002A01018"
    assert rel.tick_size == 0.05
    assert rel.is_active is True

    nifty = reg.get_instrument("NIFTY 50")
    assert nifty is not None
    assert nifty.lot_size == 25


def test_survivorship_bias_protection():
    reg = InstrumentRegistry()
    # RCOM is a delisted company (delisted 2021-10-15)
    rcom = reg.get_instrument("RCOM")
    assert rcom is not None
    assert rcom.is_active is False

    # In 2010, RCOM was actively trading
    assert rcom.is_tradable_on(date(2010, 5, 10)) is True

    # In 2023, RCOM was delisted and must NOT be tradable
    assert rcom.is_tradable_on(date(2023, 1, 1)) is False

    # Before its listing in 2006
    assert rcom.is_tradable_on(date(2000, 1, 1)) is False
