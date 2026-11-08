#!/usr/bin/env python3
"""Daily options research report for the watch universe.

Pulls delayed option chains from Yahoo Finance (via yfinance), computes
volatility and positioning metrics, writes Markdown + JSON reports and
optionally pushes a short digest (see scripts/notify.py).

Research only: no orders are placed and nothing here is a trade instruction.
Yahoo data is delayed/unofficial; implied volatility outside market hours is
unreliable, so run it during the regular session.
"""
import argparse
import datetime as dt
import json
import math
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from trading_calendar import early_close, in_session, is_trading_day  # noqa: E402

ET = ZoneInfo('America/New_York')
BENCHMARKS = ['SPY', 'QQQ']
UNUSUAL_MIN_VOLUME = 500
UNUSUAL_VOL_OI = 3.0
# Push thresholds: only "important" events notify, each at most once per day.
BIG_FLOW_MIN_VOLUME = 2000      # contracts
BIG_FLOW_VOL_OI = 5.0           # volume vs open interest
BIG_FLOW_MIN_PREMIUM = 1_000_000  # USD traded (volume x mid x 100)
IV_ALERT_PTS = 0.08             # IV30 change vs the 10:00 ET baseline (vol points)...
IV_ALERT_REL = 0.25             # ...and relative change
MOVE_ALERT_SIGMA = 2.0          # spot move vs one-day implied sigma...
MOVE_ALERT_MIN = 0.03           # ...and at least this absolute move
BASELINE_AFTER = dt.time(10, 0)  # IV baseline / optional digest after the open settles


# ---------------------------------------------------------------- pure math

def _num(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def mid_price(row):
    bid, ask, last = _num(row.get('bid')), _num(row.get('ask')), _num(row.get('lastPrice'))
    if bid and ask and ask >= bid > 0:
        return (bid + ask) / 2
    return last if last and last > 0 else None


def historical_volatility(closes, window=20):
    """Annualized close-to-close volatility over the last `window` returns."""
    closes = [c for c in (_num(x) for x in closes) if c and c > 0]
    if len(closes) < window + 1:
        return None
    rets = [math.log(b / a) for a, b in zip(closes[-window - 1:-1], closes[-window:])]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def nearest(rows, target):
    rows = [r for r in rows if _num(r.get('strike')) is not None]
    return min(rows, key=lambda r: abs(float(r['strike']) - target)) if rows else None


def _iv(row):
    iv = _num(row.get('impliedVolatility')) if row else None
    # yfinance reports placeholder IVs (~0 or >5) for stale/no-bid contracts.
    return iv if iv and 0.01 < iv < 5 else None


def atm_iv(calls, puts, spot):
    values = [v for v in (_iv(nearest(calls, spot)), _iv(nearest(puts, spot))) if v]
    return sum(values) / len(values) if values else None


def straddle_move(calls, puts, spot):
    call, put = nearest(calls, spot), nearest(puts, spot)
    if not call or not put:
        return None
    c, p = mid_price(call), mid_price(put)
    return c + p if c and p else None


def skew(calls, puts, spot, width=0.05):
    """OTM put IV minus OTM call IV at +/- width moneyness (vol points)."""
    put_iv, call_iv = _iv(nearest(puts, spot * (1 - width))), _iv(nearest(calls, spot * (1 + width)))
    return put_iv - call_iv if put_iv and call_iv else None


def max_pain(calls, puts):
    """Strike that minimizes total intrinsic value owed to option holders."""
    strikes = sorted({float(r['strike']) for r in calls + puts if _num(r.get('strike')) is not None})
    if not strikes:
        return None

    def pain(price):
        total = 0.0
        for r in calls:
            total += max(price - float(r['strike']), 0) * (_num(r.get('openInterest')) or 0)
        for r in puts:
            total += max(float(r['strike']) - price, 0) * (_num(r.get('openInterest')) or 0)
        return total

    return min(strikes, key=pain)


def total(rows, field):
    return sum(_num(r.get(field)) or 0 for r in rows)


def unusual(rows, side, expiry):
    hits = []
    for r in rows:
        vol, oi = _num(r.get('volume')) or 0, _num(r.get('openInterest')) or 0
        if vol >= UNUSUAL_MIN_VOLUME and vol >= UNUSUAL_VOL_OI * max(oi, 1):
            mid = mid_price(r)
            hits.append({'side': side, 'expiry': expiry, 'strike': float(r['strike']),
                         'volume': int(vol), 'open_interest': int(oi),
                         'iv': _iv(r), 'mid': mid,
                         'premium': vol * mid * 100 if mid else None})
    return hits


def iv_rank(current, history):
    values = [v for v in history if v] + [current]
    lo, hi = min(values), max(values)
    if len(values) < 20 or hi - lo < 1e-9:
        return None
    return (current - lo) / (hi - lo) * 100


def pick_expiry(expiries, today, target_days):
    dated = [(e, (dt.date.fromisoformat(e) - today).days) for e in expiries]
    dated = [x for x in dated if x[1] >= 1]
    return min(dated, key=lambda x: abs(x[1] - target_days)) if dated else (None, None)


def classify(m):
    """Plain-language regime and long-only-friendly ideas (not instructions)."""
    notes, ideas = [], []
    ratio, ivr = m.get('iv_hv_ratio'), m.get('iv_rank')
    rich = (ivr is not None and ivr >= 60) or (ivr is None and ratio and ratio >= 1.3)
    cheap = (ivr is not None and ivr <= 25) or (ivr is None and ratio and ratio <= 0.85)
    if rich:
        notes.append('IV偏贵')
        ideas.append('卖方占优：持股可考虑备兑看涨(covered call)，或现金担保看跌(cash-secured put)在支撑位接货')
    elif cheap:
        notes.append('IV偏便宜')
        ideas.append('买方占优：看多可考虑长期看涨/牛市看涨价差(debit spread)替代追高')
    if m.get('days_to_earnings') is not None and 0 <= m['days_to_earnings'] <= 14:
        notes.append(f"{m['days_to_earnings']}天后财报")
        ideas.append('财报前IV通常抬升、财报后回落(IV crush)，买方注意时间与波动率损耗')
    pc = m.get('pc_volume_ratio')
    if pc is not None and pc >= 1.5:
        notes.append(f'看跌成交偏重 P/C {pc:.2f}')
    elif pc is not None and pc <= 0.5:
        notes.append(f'看涨成交偏重 P/C {pc:.2f}')
    sk = m.get('skew_pts')
    if sk is not None and sk >= 0.08:
        notes.append('下行保护需求高(put skew陡)')
    if m.get('trend') == 'down':
        notes.append('价格在50日线下')
    return notes, ideas


# ---------------------------------------------------------------- data fetch

def _records(frame):
    return [] if frame is None or frame.empty else frame.to_dict('records')


def analyze_symbol(symbol, today, iv_history):
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    hist = ticker.history(period='6mo', auto_adjust=False)
    closes = hist['Close'].tolist() if not hist.empty else []
    if not closes:
        raise RuntimeError('no price history')
    spot = float(closes[-1])
    last_bar = getattr(hist.index[-1], 'date', lambda: None)()
    has_today = last_bar == today and len(closes) >= 2
    day_change = spot / float(closes[-2]) - 1 if has_today else None
    expiries = list(ticker.options or [])
    if not expiries:
        raise RuntimeError('no listed options')

    front, front_dte = pick_expiry([e for e in expiries if (dt.date.fromisoformat(e) - today).days >= 5] or expiries, today, 7)
    month, month_dte = pick_expiry(expiries, today, 30)
    chains = {}
    for exp in {front, month} | {e for e in expiries if 1 <= (dt.date.fromisoformat(e) - today).days <= 45}:
        chain = ticker.option_chain(exp)
        chains[exp] = (_records(chain.calls), _records(chain.puts))

    m_calls, m_puts = chains[month]
    f_calls, f_puts = chains[front]
    iv30 = atm_iv(m_calls, m_puts, spot)
    hv20 = historical_volatility(closes, 20)
    straddle = straddle_move(f_calls, f_puts, spot)

    all_calls = [r for c, _ in chains.values() for r in c]
    all_puts = [r for _, p in chains.values() for r in p]
    call_vol, put_vol = total(all_calls, 'volume'), total(all_puts, 'volume')
    call_oi, put_oi = total(all_calls, 'openInterest'), total(all_puts, 'openInterest')

    flow = []
    for exp, (c, p) in sorted(chains.items()):
        flow += unusual(c, 'call', exp) + unusual(p, 'put', exp)
    flow.sort(key=lambda x: -x['volume'])

    sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
    days_to_earnings = None
    try:
        cal = ticker.calendar or {}
        dates = cal.get('Earnings Date') if isinstance(cal, dict) else None
        upcoming = [d for d in (dates or []) if isinstance(d, dt.date) and d >= today]
        if upcoming:
            days_to_earnings = (min(upcoming) - today).days
    except Exception:  # calendar endpoint is flaky; earnings flag is best-effort
        pass

    metrics = {
        'symbol': symbol,
        'spot': round(spot, 2),
        'day_change': day_change,
        'trend': None if sma50 is None else ('up' if spot >= sma50 else 'down'),
        'hv20': hv20,
        'iv30': iv30,
        'iv_hv_ratio': iv30 / hv20 if iv30 and hv20 else None,
        'iv_rank': iv_rank(iv30, iv_history) if iv30 else None,
        'iv_history_days': len([v for v in iv_history if v]),
        'month_expiry': month, 'month_dte': month_dte,
        'front_expiry': front, 'front_dte': front_dte,
        'expected_move': straddle,
        'expected_move_pct': straddle / spot if straddle else None,
        'skew_pts': skew(m_calls, m_puts, spot),
        'max_pain_front': max_pain(f_calls, f_puts),
        'pc_volume_ratio': put_vol / call_vol if call_vol else None,
        'pc_oi_ratio': put_oi / call_oi if call_oi else None,
        'option_volume': int(call_vol + put_vol),
        'unusual': flow[:5],
        'days_to_earnings': days_to_earnings,
    }
    metrics['notes'], metrics['ideas'] = classify(metrics)
    return metrics


# ---------------------------------------------------------------- reporting

def pct(v, digits=0):
    return '—' if v is None else f'{v * 100:.{digits}f}%'


def fmt(v, spec='.2f'):
    return '—' if v is None else format(v, spec)


def render_markdown(report):
    lines = [f"# 期权日报 {report['date']}（{report['generated_at_et']} ET）", '']
    if report.get('early_close'):
        lines += [f"> 今日提前收盘 13:00 ET：{report['early_close']}", '']
    lines += ['> 研究用途，非交易指令。数据来自 Yahoo Finance（延迟、非官方）。IV Rank 需累积≥20个交易日历史后才显示。', '']
    lines += ['| 代码 | 现价 | IV30 | HV20 | IV/HV | IVR | 近期预期波动 | P/C量 | P/C仓 | Skew | 最大痛点 | 提示 |',
              '|---|---|---|---|---|---|---|---|---|---|---|---|']
    for m in report['symbols']:
        lines.append('| {symbol} | {spot} | {iv} | {hv} | {ratio} | {ivr} | {em} | {pcv} | {pco} | {sk} | {mp} | {notes} |'.format(
            symbol=m['symbol'], spot=fmt(m['spot']), iv=pct(m['iv30']), hv=pct(m['hv20']),
            ratio=fmt(m['iv_hv_ratio']), ivr=fmt(m['iv_rank'], '.0f'),
            em=f"±{pct(m['expected_move_pct'], 1)} ({m['front_expiry']})" if m['expected_move_pct'] else '—',
            pcv=fmt(m['pc_volume_ratio']), pco=fmt(m['pc_oi_ratio']),
            sk=fmt(None if m['skew_pts'] is None else m['skew_pts'] * 100, '+.1f'),
            mp=fmt(m['max_pain_front'], 'g'), notes='；'.join(m['notes']) or ''))
    flows = [(m['symbol'], u) for m in report['symbols'] for u in m['unusual']]
    if flows:
        lines += ['', '## 异常成交（成交量 ≥ 3×未平仓且 ≥ 500 张）', '',
                  '| 代码 | 类型 | 到期 | 行权价 | 成交量 | 未平仓 | IV | 中间价 |', '|---|---|---|---|---|---|---|---|']
        for sym, u in sorted(flows, key=lambda x: -x[1]['volume'])[:25]:
            lines.append(f"| {sym} | {u['side']} | {u['expiry']} | {u['strike']:g} | {u['volume']:,} | "
                         f"{u['open_interest']:,} | {pct(u['iv'])} | {fmt(u['mid'])} |")
    ideas = [(m['symbol'], i) for m in report['symbols'] for i in m['ideas']]
    if ideas:
        lines += ['', '## 策略思路（需自行判断，非建议）', '']
        lines += [f'- **{s}**：{i}' for s, i in ideas]
    if report['errors']:
        lines += ['', '## 未获取', ''] + [f'- {s}: {e}' for s, e in report['errors'].items()]
    lines += ['', '### 指标说明', '',
              '- **IV30**：约30天到期平值隐含波动率；**HV20**：20日历史波动率。IV/HV>1.3 偏贵，<0.85 偏便宜。',
              '- **IVR**：IV30 在已记录历史中的百分位（0–100）。',
              '- **近期预期波动**：约1周后到期（≥5天）的平值跨式价格 ÷ 现价，约为市场定价的 1σ 区间。',
              '- **Skew**：95% 看跌 IV 减 105% 看涨 IV（波动率点），越高代表下行保护越贵。',
              '- **最大痛点**：最近到期合约持有人总内在价值最小的行权价，仅作参考。']
    return '\n'.join(lines) + '\n'


def render_digest(report, url=None):
    """Short push-notification text."""
    syms = report['symbols']
    out = [f"📊 期权日报 {report['date']}" + (f"（提前收盘：{report['early_close']}）" if report.get('early_close') else '')]
    for m in syms:
        if m['symbol'] in BENCHMARKS:
            out.append(f"{m['symbol']} {fmt(m['spot'])} IV30 {pct(m['iv30'])} 近期±{pct(m['expected_move_pct'], 1)} P/C {fmt(m['pc_volume_ratio'])}")

    def score(m):
        return m['iv_rank'] if m['iv_rank'] is not None else (m['iv_hv_ratio'] or 0) * 50

    ranked = [m for m in syms if m['symbol'] not in BENCHMARKS and m['iv30']]
    rich = sorted(ranked, key=score, reverse=True)[:5]
    cheap = sorted(ranked, key=score)[:5]
    out.append('IV偏贵: ' + ', '.join(f"{m['symbol']} {pct(m['iv30'])} (IV/HV {fmt(m['iv_hv_ratio'])})" for m in rich))
    out.append('IV偏便宜: ' + ', '.join(f"{m['symbol']} {pct(m['iv30'])} (IV/HV {fmt(m['iv_hv_ratio'])})" for m in cheap))
    earn = [f"{m['symbol']}({m['days_to_earnings']}天)" for m in syms
            if m['days_to_earnings'] is not None and m['days_to_earnings'] <= 14]
    if earn:
        out.append('两周内财报: ' + ', '.join(earn))
    flows = sorted(((m['symbol'], u) for m in syms for u in m['unusual']), key=lambda x: -x[1]['volume'])[:5]
    if flows:
        out.append('异常成交: ' + '; '.join(
            f"{s} {u['expiry'][5:]} {u['strike']:g}{u['side'][0].upper()} {u['volume']:,}/{u['open_interest']:,}" for s, u in flows))
    if report['errors']:
        out.append(f"未获取: {', '.join(report['errors'])}")
    if url:
        out.append(f'完整报告: {url}')
    out.append('研究用途，非交易指令。')
    return '\n'.join(out)


# ---------------------------------------------------------------- intraday scan

def is_big_flow(u):
    return (u['volume'] >= BIG_FLOW_MIN_VOLUME
            and u['volume'] >= BIG_FLOW_VOL_OI * max(u['open_interest'], 1)
            and (u.get('premium') or 0) >= BIG_FLOW_MIN_PREMIUM)


def scan_alerts(report, state, now):
    """Return (important alert lines, new state, baseline_just_set).

    Only important events qualify, and each (symbol, kind[, contract]) is
    pushed at most once per trading day. State resets each day.
    """
    today = report['date']
    if state.get('date') != today:
        state = {'date': today, 'baseline_set': False, 'iv_base': {}, 'alerted': []}
    alerted = set(state['alerted'])
    alerts = []
    set_baseline = not state['baseline_set'] and now.time() >= BASELINE_AFTER

    def once(key, text):
        if key not in alerted:
            alerted.add(key)
            alerts.append(text)

    for m in report['symbols']:
        sym, iv = m['symbol'], m.get('iv30')
        if iv and (set_baseline or (state['baseline_set'] and sym not in state['iv_base'])):
            state['iv_base'][sym] = iv
        base = state['iv_base'].get(sym)
        if iv and base and abs(iv - base) >= IV_ALERT_PTS and abs(iv - base) / base >= IV_ALERT_REL:
            once(f'{sym}|iv', f"⚡ {sym} IV30 {'飙升' if iv > base else '骤降'} {pct(base)} → {pct(iv)}"
                              f"（{(iv - base) * 100:+.1f} 点）")
        move, sigma = m.get('day_change'), (iv / math.sqrt(252) if iv else None)
        if move is not None and sigma and abs(move) >= max(MOVE_ALERT_SIGMA * sigma, MOVE_ALERT_MIN):
            once(f'{sym}|move', f"📉 {sym} 日内 {move * 100:+.1f}%，约 {abs(move) / sigma:.1f}σ（隐含单日 σ≈{sigma * 100:.1f}%）"
                 if move < 0 else f"📈 {sym} 日内 {move * 100:+.1f}%，约 {abs(move) / sigma:.1f}σ（隐含单日 σ≈{sigma * 100:.1f}%）")
        for u in m.get('unusual', []):
            if is_big_flow(u):
                once(f"{sym}|{u['expiry']}|{u['strike']:g}|{u['side']}",
                     f"🐋 {sym} 大单 {u['expiry'][5:]} {u['strike']:g}{u['side'][0].upper()} "
                     f"量 {u['volume']:,} / 仓 {u['open_interest']:,}，成交额约 ${u['premium'] / 1e6:.1f}M"
                     + (f"，IV {pct(u['iv'])}" if u.get('iv') else ''))
    if set_baseline:
        state['baseline_set'] = True
    state['alerted'] = sorted(alerted)
    return alerts, state, set_baseline


# ---------------------------------------------------------------- main

def load_symbols(path):
    data = json.loads(Path(path).read_text())
    latest = data['score_history'][-1]['path']
    records = json.loads((Path(path).parent.parent / latest).read_text())['records']
    return [r['symbol'] for r in records]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--symbols', help='Comma-separated tickers (default: watch universe + SPY,QQQ)')
    parser.add_argument('--watch', default=str(ROOT / 'docs/data/watch.json'))
    parser.add_argument('--out', default='options-report', help='Output directory')
    parser.add_argument('--iv-history', default='options-iv-history.json', help='Rolling IV30 store for IV Rank')
    parser.add_argument('--force', action='store_true', help='Run even if today is not a trading day')
    parser.add_argument('--notify', action='store_true', help='Push the digest via configured channels')
    parser.add_argument('--report-url', help='Link added to the digest')
    parser.add_argument('--scan', action='store_true',
                        help='Intraday mode: run only in session, send the digest once a day and push only new alerts')
    parser.add_argument('--state', default='options-scan-state.json', help='Intraday alert state (with --scan)')
    parser.add_argument('--push-digest', action='store_true',
                        help='With --scan, also push the full daily digest once (default: important alerts only)')
    args = parser.parse_args(argv)

    now = dt.datetime.now(ET)
    today = now.date()
    if not args.force and not is_trading_day(today):
        print(f'{today} is not an NYSE trading day; skipping.')
        return 0
    if args.scan and not args.force and not in_session(now):
        print(f'{now:%H:%M} ET is outside the regular session; skipping.')
        return 0

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
    else:
        symbols = BENCHMARKS + [s for s in load_symbols(args.watch) if s not in BENCHMARKS]

    hist_path = Path(args.iv_history)
    store = json.loads(hist_path.read_text()) if hist_path.exists() else {}
    results, errors = [], {}
    for sym in symbols:
        series = store.get(sym, {})
        past = [v for d, v in sorted(series.items()) if d != today.isoformat()][-252:]
        try:
            m = analyze_symbol(sym, today, past)
        except Exception as exc:  # one bad ticker must not sink the report
            errors[sym] = str(exc)[:200]
            print(f'{sym}: {exc}', file=sys.stderr)
            continue
        results.append(m)
        if m['iv30']:
            series[today.isoformat()] = round(m['iv30'], 4)
            store[sym] = dict(sorted(series.items())[-300:])

    report = {
        'date': today.isoformat(),
        'generated_at_et': now.strftime('%H:%M'),
        'early_close': early_close(today),
        'symbols': results,
        'errors': errors,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f'options-{today}.json').write_text(json.dumps(report, indent=2, default=str) + '\n')
    (out / f'options-{today}.md').write_text(render_markdown(report))
    hist_path.write_text(json.dumps(store, indent=1, sort_keys=True) + '\n')
    digest = render_digest(report, args.report_url)
    messages = []
    if args.scan:
        state_path = Path(args.state)
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        alerts, state, baseline_now = scan_alerts(report, state, now)
        state_path.write_text(json.dumps(state, indent=1) + '\n')
        send_digest = args.push_digest and baseline_now
        if send_digest:
            messages.append((f'期权日报 {today}', digest))
        if alerts:
            body = '\n'.join(alerts[:30]) + (f'\n…另有 {len(alerts) - 30} 条' if len(alerts) > 30 else '')
            if args.report_url:
                body += f'\n完整报告: {args.report_url}'
            messages.append((f'期权重要异动 {now:%H:%M} ET', body + '\n研究用途，非交易指令。'))
        print(f'Scan {now:%H:%M} ET: {len(alerts)} important alert(s); digest {"pushed" if send_digest else "not pushed"}.')
    else:
        messages.append((f'期权日报 {today}', digest))
    for title, body in messages:
        print(f'--- {title}\n{body}')

    if args.notify and messages:
        from notify import send_all
        for title, body in messages:
            sent = send_all(title, body)
            print(f'Notified "{title}": {", ".join(sent) or "no channel configured"}')
    if not results:
        print('No symbols analyzed.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
