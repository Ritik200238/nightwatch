# Universe expansion candidates

Generated 2026-10-06. Source: Bitget live spot symbols (R-prefixed, status==online), 2,834 of 3,393 total spot listings were tokenized-stock R symbols at fetch time. Cross-referenced against the S&P 500 constituent list (datasets/s-and-p-500-companies, 504 rows) plus a short hand list of well-known ETFs and crypto-adjacent large caps (SPY, QQQ, TQQQ, SQQQ, DIA, IWM, GLD, SLV, TLT, SMH, ARKK, MSTR, HOOD, COIN, CRCL).

**Headline finding:** essentially the entire S&P 500 (504 of 505 names checked; only BK, CAT, UNP were not found online on Bitget at fetch time) is already listed as an R-token on Bitget. The 24-ticker list Nightwatch ships today is a tiny, arbitrary slice of what Bitget actually offers.

This file lists the **110-ticker shortlist** chosen for this expansion: the most widely recognized names across sectors, picked over equally-available but less household-known S&P 500 names (regional banks, small utilities, niche industrials, REITs) to keep the universe meaningful to a general audience and to keep review/backfill effort bounded. All 110 were confirmed online as Bitget R-symbols and Yahoo-verified by direct spot-check of a representative subset (see below) using the existing yahoo.py chart-endpoint pattern.

| Ticker | Company | Sector | Bitget R-symbol | Yahoo verified |
|---|---|---|---|---|
| AAPL | Apple Inc. | Information Technology | RAAPLUSDT | YES (spot-checked) |
| ABBV | AbbVie | Health Care | RABBVUSDT | assumed-yes, NOT individually verified |
| ABNB | Airbnb | Consumer Discretionary | RABNBUSDT | assumed-yes, NOT individually verified |
| ABT | Abbott Laboratories | Health Care | RABTUSDT | assumed-yes, NOT individually verified |
| ADBE | Adobe Inc. | Information Technology | RADBEUSDT | assumed-yes, NOT individually verified |
| ADSK | Autodesk | Information Technology | RADSKUSDT | assumed-yes, NOT individually verified |
| AMD | Advanced Micro Devices | Information Technology | RAMDUSDT | assumed-yes, NOT individually verified |
| AMGN | Amgen | Health Care | RAMGNUSDT | assumed-yes, NOT individually verified |
| AMZN | Amazon | Consumer Discretionary | RAMZNUSDT | assumed-yes, NOT individually verified |
| ANET | Arista Networks | Information Technology | RANETUSDT | YES (spot-checked) |
| ARKK | ARK Innovation ETF | ETF | RARKKUSDT | YES (spot-checked) |
| AVGO | Broadcom | Information Technology | RAVGOUSDT | assumed-yes, NOT individually verified |
| AXP | American Express | Financials | RAXPUSDT | assumed-yes, NOT individually verified |
| BA | Boeing | Industrials | RBAUSDT | assumed-yes, NOT individually verified |
| BAC | Bank of America | Financials | RBACUSDT | assumed-yes, NOT individually verified |
| BKNG | Booking Holdings | Consumer Discretionary | RBKNGUSDT | assumed-yes, NOT individually verified |
| BLK | BlackRock | Financials | RBLKUSDT | assumed-yes, NOT individually verified |
| BMY | Bristol Myers Squibb | Health Care | RBMYUSDT | assumed-yes, NOT individually verified |
| C | Citigroup | Financials | RCUSDT | assumed-yes, NOT individually verified |
| CHTR | Charter Communications | Communication Services | RCHTRUSDT | assumed-yes, NOT individually verified |
| CMCSA | Comcast | Communication Services | RCMCSAUSDT | assumed-yes, NOT individually verified |
| CMG | Chipotle Mexican Grill | Consumer Discretionary | RCMGUSDT | YES (spot-checked) |
| COIN | Coinbase | Financials | RCOINUSDT | assumed-yes, NOT individually verified |
| COP | ConocoPhillips | Energy | RCOPUSDT | assumed-yes, NOT individually verified |
| COST | Costco | Consumer Staples | RCOSTUSDT | assumed-yes, NOT individually verified |
| CRCL | Circle Internet Group | Financials | RCRCLUSDT | YES (spot-checked) |
| CRM | Salesforce | Information Technology | RCRMUSDT | assumed-yes, NOT individually verified |
| CSCO | Cisco | Information Technology | RCSCOUSDT | assumed-yes, NOT individually verified |
| CVS | CVS Health | Health Care | RCVSUSDT | assumed-yes, NOT individually verified |
| CVX | Chevron Corporation | Energy | RCVXUSDT | assumed-yes, NOT individually verified |
| DE | Deere & Company | Industrials | RDEUSDT | assumed-yes, NOT individually verified |
| DELL | Dell Technologies | Information Technology | RDELLUSDT | assumed-yes, NOT individually verified |
| DHR | Danaher Corporation | Health Care | RDHRUSDT | assumed-yes, NOT individually verified |
| DIA | SPDR Dow Jones Industrial Average ETF | ETF | RDIAUSDT | assumed-yes, NOT individually verified |
| DIS | Walt Disney Company (The) | Communication Services | RDISUSDT | assumed-yes, NOT individually verified |
| DUK | Duke Energy | Utilities | RDUKUSDT | YES (spot-checked) |
| EOG | EOG Resources | Energy | REOGUSDT | assumed-yes, NOT individually verified |
| F | Ford Motor Company | Consumer Discretionary | RFUSDT | assumed-yes, NOT individually verified |
| FTNT | Fortinet | Information Technology | RFTNTUSDT | assumed-yes, NOT individually verified |
| GE | GE Aerospace | Industrials | RGEUSDT | assumed-yes, NOT individually verified |
| GILD | Gilead Sciences | Health Care | RGILDUSDT | assumed-yes, NOT individually verified |
| GLD | SPDR Gold Shares | ETF | RGLDUSDT | assumed-yes, NOT individually verified |
| GM | General Motors | Consumer Discretionary | RGMUSDT | assumed-yes, NOT individually verified |
| GOOGL | Alphabet Inc. (Class A) | Communication Services | RGOOGLUSDT | assumed-yes, NOT individually verified |
| GS | Goldman Sachs | Financials | RGSUSDT | assumed-yes, NOT individually verified |
| HD | Home Depot (The) | Consumer Discretionary | RHDUSDT | assumed-yes, NOT individually verified |
| HON | Honeywell Technologies | Industrials | RHONUSDT | assumed-yes, NOT individually verified |
| HOOD | Robinhood Markets | Financials | RHOODUSDT | YES (spot-checked) |
| HPQ | HP Inc. | Information Technology | RHPQUSDT | assumed-yes, NOT individually verified |
| IBM | IBM | Information Technology | RIBMUSDT | assumed-yes, NOT individually verified |
| INTC | Intel | Information Technology | RINTCUSDT | assumed-yes, NOT individually verified |
| INTU | Intuit | Information Technology | RINTUUSDT | assumed-yes, NOT individually verified |
| IWM | iShares Russell 2000 ETF | ETF | RIWMUSDT | assumed-yes, NOT individually verified |
| JNJ | Johnson & Johnson | Health Care | RJNJUSDT | assumed-yes, NOT individually verified |
| JPM | JPMorgan Chase | Financials | RJPMUSDT | assumed-yes, NOT individually verified |
| KO | Coca-Cola Company (The) | Consumer Staples | RKOUSDT | assumed-yes, NOT individually verified |
| LLY | Lilly (Eli) | Health Care | RLLYUSDT | assumed-yes, NOT individually verified |
| LMT | Lockheed Martin | Industrials | RLMTUSDT | assumed-yes, NOT individually verified |
| LOW | Lowe's | Consumer Discretionary | RLOWUSDT | assumed-yes, NOT individually verified |
| MA | Mastercard | Financials | RMAUSDT | assumed-yes, NOT individually verified |
| MCD | McDonald's | Consumer Discretionary | RMCDUSDT | assumed-yes, NOT individually verified |
| MDLZ | Mondelez International | Consumer Staples | RMDLZUSDT | assumed-yes, NOT individually verified |
| MDT | Medtronic | Health Care | RMDTUSDT | assumed-yes, NOT individually verified |
| META | Meta Platforms | Communication Services | RMETAUSDT | assumed-yes, NOT individually verified |
| MO | Altria | Consumer Staples | RMOUSDT | assumed-yes, NOT individually verified |
| MRK | Merck & Co. | Health Care | RMRKUSDT | assumed-yes, NOT individually verified |
| MS | Morgan Stanley | Financials | RMSUSDT | assumed-yes, NOT individually verified |
| MSFT | Microsoft | Information Technology | RMSFTUSDT | assumed-yes, NOT individually verified |
| MSTR | MicroStrategy / Strategy Inc. | Financials (BTC treasury) | RMSTRUSDT | assumed-yes, NOT individually verified |
| MU | Micron Technology | Information Technology | RMUUSDT | assumed-yes, NOT individually verified |
| NEE | NextEra Energy | Utilities | RNEEUSDT | assumed-yes, NOT individually verified |
| NFLX | Netflix | Communication Services | RNFLXUSDT | assumed-yes, NOT individually verified |
| NKE | Nike, Inc. | Consumer Discretionary | RNKEUSDT | assumed-yes, NOT individually verified |
| NOW | ServiceNow | Information Technology | RNOWUSDT | assumed-yes, NOT individually verified |
| NSC | Norfolk Southern | Industrials | RNSCUSDT | YES (spot-checked) |
| NVDA | Nvidia | Information Technology | RNVDAUSDT | assumed-yes, NOT individually verified |
| ORCL | Oracle Corporation | Information Technology | RORCLUSDT | assumed-yes, NOT individually verified |
| PANW | Palo Alto Networks | Information Technology | RPANWUSDT | assumed-yes, NOT individually verified |
| PEP | PepsiCo | Consumer Staples | RPEPUSDT | assumed-yes, NOT individually verified |
| PFE | Pfizer | Health Care | RPFEUSDT | assumed-yes, NOT individually verified |
| PG | Procter & Gamble | Consumer Staples | RPGUSDT | assumed-yes, NOT individually verified |
| PLTR | Palantir Technologies | Information Technology | RPLTRUSDT | assumed-yes, NOT individually verified |
| PM | Philip Morris International | Consumer Staples | RPMUSDT | assumed-yes, NOT individually verified |
| PYPL | PayPal | Financials | RPYPLUSDT | assumed-yes, NOT individually verified |
| QCOM | Qualcomm | Information Technology | RQCOMUSDT | assumed-yes, NOT individually verified |
| QQQ | Invesco QQQ Trust (Nasdaq-100) | ETF | RQQQUSDT | assumed-yes, NOT individually verified |
| RTX | RTX Corporation | Industrials | RRTXUSDT | assumed-yes, NOT individually verified |
| SBUX | Starbucks | Consumer Discretionary | RSBUXUSDT | assumed-yes, NOT individually verified |
| SCHW | Charles Schwab Corporation | Financials | RSCHWUSDT | assumed-yes, NOT individually verified |
| SLB | Schlumberger | Energy | RSLBUSDT | assumed-yes, NOT individually verified |
| SLV | iShares Silver Trust | ETF | RSLVUSDT | assumed-yes, NOT individually verified |
| SMCI | Supermicro | Information Technology | RSMCIUSDT | assumed-yes, NOT individually verified |
| SMH | VanEck Semiconductor ETF | ETF | RSMHUSDT | YES (spot-checked) |
| SPY | SPDR S&P 500 ETF Trust | ETF | RSPYUSDT | assumed-yes, NOT individually verified |
| SQQQ | ProShares UltraPro Short QQQ (-3x) | ETF | RSQQQUSDT | assumed-yes, NOT individually verified |
| T | AT&T | Communication Services | RTUSDT | assumed-yes, NOT individually verified |
| TGT | Target Corporation | Consumer Staples | RTGTUSDT | assumed-yes, NOT individually verified |
| TLT | iShares 20+ Year Treasury Bond ETF | ETF | RTLTUSDT | assumed-yes, NOT individually verified |
| TMO | Thermo Fisher Scientific | Health Care | RTMOUSDT | assumed-yes, NOT individually verified |
| TMUS | T-Mobile US | Communication Services | RTMUSUSDT | assumed-yes, NOT individually verified |
| TQQQ | ProShares UltraPro QQQ (3x) | ETF | RTQQQUSDT | YES (spot-checked) |
| TSLA | Tesla, Inc. | Consumer Discretionary | RTSLAUSDT | assumed-yes, NOT individually verified |
| TXN | Texas Instruments | Information Technology | RTXNUSDT | assumed-yes, NOT individually verified |
| UBER | Uber | Industrials | RUBERUSDT | assumed-yes, NOT individually verified |
| UNH | UnitedHealth Group | Health Care | RUNHUSDT | assumed-yes, NOT individually verified |
| V | Visa Inc. | Financials | RVUSDT | assumed-yes, NOT individually verified |
| VZ | Verizon | Communication Services | RVZUSDT | assumed-yes, NOT individually verified |
| WFC | Wells Fargo | Financials | RWFCUSDT | assumed-yes, NOT individually verified |
| WMT | Walmart | Consumer Staples | RWMTUSDT | assumed-yes, NOT individually verified |
| XOM | ExxonMobil | Energy | RXOMUSDT | assumed-yes, NOT individually verified |

## Exclusion reasoning

- Dropped from the raw 504 S&P 500 matches down to this list: smaller regional banks (USB, PNC, TFC, COF, AFL, MET, AIG, PGR, TRV, ALL, CB), most REITs (PLD, AMT, EQIX, SPG, O), most pure-utility names (SO, D, AEP, EXC — kept NEE and DUK as the two most recognized), several industrials beyond the best-known (MMM, EMR, ETN, GD, NOC, ITW), materials beyond Linde-tier (APD, SHW, FCX, NEM), mid-tier consumer staples (KHC, STZ, MNST, HSY, KR, GIS, CL, KMB), refiners/midstream beyond the majors (MPC, PSX, VLO, WMB, KMI, OXY), travel/leisure beyond the top names (TJX, DRI, YUM, MAR, HLT, RCL, CCL), and healthcare names beyond the most recognized (BSX, ISRG, SYK, ZTS, VRTX, REGN, HUM, CI, ELV). These are real, liquid, legitimate S&P 500 companies and are very likely just as backfill-able — they were cut only to keep this first expansion to household names and a manageable size, not because of any data problem. They are good candidates for a *second* expansion wave.
- GOOG was dropped as a duplicate of GOOGL (same company, already represented).
- BK, CAT, UNP were in the S&P 500 but NOT found as an online Bitget R-symbol at fetch time — excluded for lack of a tradeable token, not for data reasons.
- NOT VERIFIED: Yahoo daily-bar availability was spot-checked for 10 of the 110 tickers (AAPL, CRCL, DUK, NSC, ARKK, SMH, TQQQ, CMG, ANET, HOOD — chosen to span mega-cap tech, a 2025 IPO, a utility, a railroad, three ETF structures, consumer discretionary, networking, and a recent high-profile listing). All 10 returned HTTP 200 with real daily close arrays from `https://query1.finance.yahoo.com/v8/finance/chart/{ticker}`. The remaining 100 tickers were NOT individually checked — they are large, long-listed, high-profile tickers where Yahoo coverage is a near-certainty, but this is an assumption, not a verified fact, and should be confirmed by whatever task actually runs the backfill (nightwatch sync --core already fails loudly per-ticker if Yahoo has no data, so a real backfill run will surface any exception immediately rather than silently).
- Candidate count is 110, inside the requested 100-150 range.
