# Financial model (estimates)

Inputs and sources are in `finance/model.py`. All amounts in EUR.

## Per-client economics (per month)

| Tier | Set-up | Monthly | Direct cost | Gross margin | Onboarding h | Support h/month |
| --- | --- | --- | --- | --- | --- | --- |
| starter | 199 | 59 | 0.50 | 99% | 4 | 1.0 |
| pro | 399 | 99 | 10.50 | 89% | 8 | 1.5 |
| premium | 799 | 179 | 21.12 | 88% | 16 | 3.0 |

## 12-month scenarios (base case)

| Active at month 12 | Revenue | of which set-up | Gross profit | Operating profit before tax | Paušal tax | Contributions | Take-home (obrt) | Take-home if on student contracts | Hours | Take-home per hour | Month-12 monthly take-home |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 0 | 0 | 0 | -516 | 0 | 3492 | -4128 | -516 | 0 | — | -344 |
| 1 | 696 | 173 | 661 | 145 | 203 | 3492 | -3670 | 145 | 34 | -109.23 | -283 |
| 3 | 2339 | 769 | 2234 | 1718 | 203 | 3492 | -2097 | 1718 | 101 | -20.77 | -129 |
| 5 | 4125 | 1509 | 3950 | 3434 | 203 | 3492 | -382 | 3434 | 168 | -2.27 | 26 |
| 10 | 8590 | 3358 | 8239 | 7723 | 203 | 3492 | 3908 | 7723 | 336 | 11.63 | 413 |
| 20 | 17520 | 7055 | 16819 | 16303 | 358 | 3492 | 12333 | n/a (over 12,000) | 672 | 18.35 | 1159 |
| 30 | 26450 | 10753 | 25398 | 24882 | 551 | 3492 | 20719 | n/a (over 12,000) | 1008 | 20.55 | 1933 |

## Monthly recurring revenue targets

### conservative

| MRR goal | Customers (mix) | at €59 / €99 / €179 | Months to reach | Support h/month | Acquisition h/month | Monthly take-home |
| --- | --- | --- | --- | --- | --- | --- |
| 500 | 7 | 9 / 6 / 3 | 9 | 9.5 | 10.7 | 100 |
| 1000 | 13 | 17 / 11 / 6 | 21 | 17.6 | 19.8 | 561 |
| 2000 | 25 | 34 / 21 / 12 | not reachable at 60 contacts/month | 33.8 | 38.1 | 1471 |
| 3000 | 37 | 51 / 31 / 17 | not reachable at 60 contacts/month | 50.0 | 56.4 | 2390 |
| 5000 | 61 | 85 / 51 / 28 | not reachable at 60 contacts/month | 82.4 | 93.0 | 4227 |

### base

| MRR goal | Customers (mix) | at €59 / €99 / €179 | Months to reach | Support h/month | Acquisition h/month | Monthly take-home |
| --- | --- | --- | --- | --- | --- | --- |
| 500 | 7 | 9 / 6 / 3 | 4 | 9.5 | 3.2 | 100 |
| 1000 | 13 | 17 / 11 / 6 | 8 | 17.6 | 5.9 | 561 |
| 2000 | 25 | 34 / 21 / 12 | 16 | 33.8 | 11.4 | 1471 |
| 3000 | 37 | 51 / 31 / 17 | 27 | 50.0 | 16.9 | 2390 |
| 5000 | 61 | 85 / 51 / 28 | 81 | 82.4 | 27.9 | 4227 |

### optimistic

| MRR goal | Customers (mix) | at €59 / €99 / €179 | Months to reach | Support h/month | Acquisition h/month | Monthly take-home |
| --- | --- | --- | --- | --- | --- | --- |
| 500 | 7 | 9 / 6 / 3 | 2 | 9.5 | 1.1 | 100 |
| 1000 | 13 | 17 / 11 / 6 | 4 | 17.6 | 2.0 | 561 |
| 2000 | 25 | 34 / 21 / 12 | 7 | 33.8 | 3.8 | 1471 |
| 3000 | 37 | 51 / 31 / 17 | 11 | 50.0 | 5.6 | 2390 |
| 5000 | 61 | 85 / 51 / 28 | 19 | 82.4 | 9.3 | 4227 |
