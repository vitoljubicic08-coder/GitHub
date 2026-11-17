"""One-off sensitivity: which funded risk cap, with execution costs inside per-contract risk."""
import sys, zlib, numpy as np
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[2] / 'backtest'))
import prop_sim as ps, intraday_lab as il
d = il.load_instrument(sys.argv[1], 'QQQ')
base = ps.build_pool(d, 20250101, 20260331, ps.EXEC_BASE)
SLIP_USD = 2 * 0.50          # 1 MNQ tick per side, as in the base execution model
def day_arrays_cost(pool, st, firm, risk, dll):
    idx, src = st['idx'], st['src']; dpr = np.nan_to_num(pool['dpr'][idx]); has = pool['has'][idx]
    rpc = dpr + firm.commission_rt + SLIP_USD
    c = np.where(has & (rpc > 0), np.minimum(np.floor(risk / np.where(rpc > 0, rpc, 1) + 1e-9), firm.max_micros), 0.0)
    pnl = c * pool['r'][src] * dpr - c * firm.commission_rt
    low = c * pool['lo'][src] * dpr - c * firm.commission_rt / 2
    if dll is not None:
        hit = low <= -dll; pnl = np.where(hit, -dll, pnl); low = np.where(hit, -dll, low)
    return pnl, low, c > 0, c, dpr
rows = []
for volname, scale in (('holdout vol', 1.0), ('today vol', ps.CURVOL_SCALE)):
    pool = dict(base); pool['dpr'] = base['dpr'] * scale
    for scen, k in (('B', 0.75), ('C', 0.5), ('E', 0.0)):
        st = ps.make_streams(pool, 2000, 504, 'bootstrap', 10, k, zlib.crc32(f'funded|{scen}|{volname}'.encode()))
        for firm in ('topstep', 'lucid', 'tradeify'):
            f = ps.FIRMS[firm]
            for er, fr in ((350, 250), (350, 300), (350, 350), (350, 400)):
                E = day_arrays_cost(pool, st, f, er, f.eval_dll); F = day_arrays_cost(pool, st, f, fr, f.funded_dll)
                outs = [ps.run_stream(f, tuple(x[i] for x in E), tuple(x[i] for x in F), 504, 1, 'above_cushion', pool, st['src'][i]) for i in range(2000)]
                m = ps.lifecycle_metrics([a[0] for a, _ in outs])
                rows.append((volname, scen, firm, f'{er}/{fr}', float(F[2].mean() / max(pool['has'][st['idx']].mean(), 1e-9)), m['pass_prob'], m['p_first_payout'], m['mean_net_profit'], m['median_net_profit'], m['p5_net_profit'], m['p_profit']))
import csv
w = csv.writer(sys.stdout); w.writerow(['vol', 'scenario', 'firm', 'eval/funded', 'funded_trade_share', 'pass', 'payout', 'mean_net', 'median_net', 'p5_net', 'p_profit'])
for r in rows: w.writerow([r[0], r[1], r[2], r[3]] + [round(x, 3) for x in r[4:]])
