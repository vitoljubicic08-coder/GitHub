# NB3 V2 bot engine vs verified backtest — parity report

* Result: **PASS**
* Reference trades: 675; bot trades: 675; identical: 675; discrepancies: 0
* Fields compared per trade: session, signal bar and time, direction, entry minute, entry fill, stop distance, stop and target, exit minute, exit price, exit reason, net R, gross R (prices and R to within 1e-09)
* Largest absolute differences: fill 0.00e+00, dist 0.00e+00, exit_px 0.00e+00, r_net 0.00e+00, r_gross 0.00e+00
* Bot replay: 675 trades, mean +0.1954R, win rate 45.0%, total +131.9R
* Data: /tmp/claude-0/-home-user-GitHub/f4c38b43-8d2d-5827-bc2b-19009e738a12/scratchpad/inst (774 sessions, up to 20260331)


## First 10 trades (New York signal time)

| Session | Signal bar opens | Side | Entry | Stop | Target | Exit | Reason | R |
|---|---|---|---|---|---|---|---|---|
| 20230321 | 09:30 | BUY | 308.7400 | 306.9370 | 314.1490 | 306.9170 | STOP | -1.017 |
| 20230322 | 10:25 | BUY | 311.7100 | 309.9310 | 317.0470 | 309.9110 | STOP | -1.017 |
| 20230323 | 10:05 | BUY | 311.3400 | 309.4888 | 316.8936 | 309.4688 | STOP | -1.016 |
| 20230324 | 09:30 | SELL | 308.6900 | 310.5838 | 303.0085 | 310.6038 | STOP | -1.016 |
| 20230327 | 09:35 | SELL | 310.8700 | 312.7152 | 305.3346 | 309.0400 | EOD | +0.986 |
| 20230328 | 09:30 | SELL | 307.2800 | 309.0964 | 301.8307 | 306.8600 | EOD | +0.226 |
| 20230331 | 09:30 | BUY | 316.7000 | 314.9738 | 321.8787 | 320.4600 | EOD | +2.172 |
| 20230403 | 09:30 | BUY | 319.4800 | 317.7577 | 324.6468 | 317.7377 | STOP | -1.017 |
| 20230404 | 09:40 | SELL | 319.4700 | 321.1434 | 314.4498 | 321.1634 | STOP | -1.018 |
| 20230405 | 09:45 | SELL | 316.9200 | 318.5553 | 312.0141 | 316.0800 | EOD | +0.508 |
