#!/usr/bin/env python3
"""Deterministic long-only technical entry screen.

Automates the price-derivable checks of buying-score-v2 (see
scripts/buying_score_v2.py): trend T1-T4, setup/entry E1-E6, liquidity L2 and
the earnings part of L3. Levels come from completed daily bars; the live
price is only the reference entry. Catalyst (C*), fundamentals (F*), spread
(L1) and macro-event checks need human research and are NOT evaluated, so a
pass is a technical candidate to research, never a buy instruction.
"""
import math


def sma(values, n, end=None):
    end = len(values) if end is None else end
    window = values[end - n:end]
    return sum(window) / n if end >= n and len(window) == n else None


def atr(highs, lows, closes, n=14):
    if len(closes) < n + 1:
        return None
    trs = [max(h - l, abs(h - pc), abs(l - pc))
           for h, l, pc in zip(highs[-n:], lows[-n:], closes[-n - 1:-1])]
    return sum(trs) / n


def ret(values, n):
    return values[-1] / values[-1 - n] - 1 if len(values) > n and values[-1 - n] else None


def entry_signal(bars, price, spy_closes=None, days_to_earnings=None):
    """Evaluate one symbol.

    bars: dict of equal-length lists 'high', 'low', 'close', 'volume' for
    COMPLETED sessions (oldest first). price: current reference price.
    Returns a dict with checks, setup, levels and `candidate` (all pass).
    """
    h, l, c, v = bars['high'], bars['low'], bars['close'], bars['volume']
    if len(c) < 60 or not price:
        return {'candidate': False, 'reason': 'insufficient history'}
    s20, s50, s20_prev = sma(c, 20), sma(c, 50), sma(c, 20, len(c) - 5)
    a14 = atr(h, l, c)
    dollar_vol = sum(ci * vi for ci, vi in zip(c[-20:], v[-20:])) / 20
    r20 = ret(c, 20)
    spy_r20 = ret(spy_closes, 20) if spy_closes else None

    checks = {
        'T1 close>SMA20': c[-1] > s20,
        'T2 SMA20>SMA50': s20 > s50,
        'T3 SMA20 rising': s20 > s20_prev,
        'T4 beats SPY 20d': None if spy_r20 is None or r20 is None else r20 > spy_r20,
        'E6 not extended': price <= s20 + a14,
        'L2 $vol>=20M': dollar_vol >= 20e6,
        'L3 no earnings<=5 sessions': None if days_to_earnings is None else days_to_earnings > 7,
    }

    # E1/E2: setup level within 0.5 ATR of the reference price.
    prior_high = max(h[-20:])
    setup = None
    if price > prior_high and price - prior_high <= 0.5 * a14:
        setup, level = '突破20日高点', prior_high
    elif abs(price - s20) <= 0.5 * a14 and price >= s20 - 0.25 * a14:
        setup, level = '回踩20日线', s20
    checks['E1/E2 setup near level'] = setup is not None

    result = {
        'price': round(price, 2), 'sma20': round(s20, 2), 'sma50': round(s50, 2), 'atr14': round(a14, 2),
        'ret20': r20, 'spy_ret20': spy_r20, 'dollar_volume_20d': dollar_vol, 'setup': setup,
    }
    if setup:
        # E3: invalidation below the setup level (structural low or 1 ATR under the level).
        invalidation = min(level - a14, min(l[-10:]))
        risk = price - invalidation
        # E4/E5: the 120-session high is the overhead resistance; the 2R target must clear it.
        high120 = max(h[-120:])
        resistance = high120 if high120 > price + 0.1 * a14 else None
        checks['E3 invalidation below'] = risk > 0
        checks['E4/E5 2R path'] = risk > 0 and (resistance is None or resistance >= price + 2 * risk)
        result.update({'level': round(level, 2), 'invalidation': round(invalidation, 2),
                       'risk_pct': risk / price if price else None, 'target_2r': round(price + 2 * risk, 2),
                       'resistance': None if resistance is None else round(resistance, 2)})
    result['checks'] = checks
    failed = [k for k, ok in checks.items() if ok is False]
    unknown = [k for k, ok in checks.items() if ok is None]
    result['failed'], result['unknown'] = failed, unknown
    # Unknown checks (e.g. earnings date unavailable) do not block, but are reported.
    result['candidate'] = setup is not None and not failed
    passed = sum(1 for ok in checks.values() if ok)
    result['passed'] = f'{passed}/{len(checks)}'
    return result


def bars_from_history(hist, today):
    """Split a yfinance daily frame into completed bars and today's live price."""
    rows = list(zip(hist.index, hist['High'], hist['Low'], hist['Close'], hist['Volume']))
    rows = [r for r in rows if all(isinstance(x, (int, float)) and math.isfinite(x) for x in r[1:4])]
    if not rows:
        return None, None
    price = float(rows[-1][3])
    last_day = getattr(rows[-1][0], 'date', lambda: None)()
    completed = rows[:-1] if last_day == today else rows
    bars = {'high': [float(r[1]) for r in completed], 'low': [float(r[2]) for r in completed],
            'close': [float(r[3]) for r in completed], 'volume': [float(r[4] or 0) for r in completed]}
    return bars, price
