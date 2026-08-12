# Personal Finance & Markets Hub — Feature Breakdown & Rationale

Every feature below is justified two ways: what you'd actually use it for, and what it proves in an interview. Where the personal-use case is genuinely thin, that's said directly rather than forced. This is the second pass — the original 14 grew to 24, and this round adds 11 more, for 35 total across 8 areas.

## Trading & Markets / Quant

### Forex trading bot (in progress)
- **Does:** Executes or signals currency trades based on a rules-based or model-driven strategy.
- **Personal:** You can actually run it (paper or live) and watch your own logic perform with real market data.
- **CV:** The most "trading desk"-flavored project a student can show — you built signals, not just a model.

### Backtesting engine / strategy tester
- **Does:** A reusable framework that replays historical price data through any strategy and reports how it would have performed.
- **Personal:** Lets you cheaply test new trading ideas before ever risking money on them.
- **CV:** Shows you understand that a working bot isn't the same as a validated strategy — separates "hobby coder" from "quant" in an interview.

### Options pricer & Greeks calculator
- **Does:** Prices options with Black-Scholes/binomial models and shows delta, gamma, theta, vega for any contract.
- **Personal:** Lets you understand the real risk/payoff of an option before you'd ever trade one.
- **CV:** Options math is standard in trading interviews — having built the pricer beats reciting the formula.

### Cross-asset correlation & seasonality analyzer
- **Does:** Studies how your traded pairs move relative to equities, commodities, or time of year.
- **Personal:** Directly improves the forex bot — you'd be building a real edge, not trading blind.
- **CV:** Shows independent research instinct, which separates a trader from someone who just runs a script.

### Pairs trading / statistical arbitrage screener
- **Does:** Scans for two historically correlated instruments that have temporarily diverged, flagging a potential mean-reversion trade.
- **Personal:** Another genuine strategy you could paper-trade alongside the forex bot.
- **CV:** Stat arb is a real quant desk strategy family — shows you're thinking beyond directional trading.

### Economic calendar impact tracker
- **Does:** Logs how your traded pairs actually moved around scheduled releases (NFP, CPI, rate decisions) versus normal days.
- **Personal:** Tells you concretely whether it's worth trading (or avoiding) around news events — directly informs the forex bot's rules.
- **CV:** Connects macro awareness to trading mechanics — a combination interviewers specifically probe for on markets desks.

## Investment Banking / Valuation

### DCF / LBO valuation template (planned)
- **Does:** A flexible Excel model that values a public company from its cash flows, or models a leveraged buyout's returns.
- **Personal:** Value a stock yourself before you buy it, instead of trusting a headline price target.
- **CV:** The most common technical test in IB/PE interviews — arriving with your own working model is a real edge.

### Comparable companies (comps) screener
- **Does:** Pulls a peer group's financials and auto-calculates trading multiples (P/E, EV/EBITDA) to see who looks cheap or expensive.
- **Personal:** A genuine, repeatable way to sanity-check any stock you're considering for yourself.
- **CV:** Comps are a first-week analyst task — you'll have already automated it before your internship starts.

### Precedent transactions analyzer
- **Does:** Tracks past M&A deals in a sector and calculates the multiples buyers actually paid, as a second valuation cross-check alongside comps.
- **Personal:** Less direct daily use, but sharpens your read on whether a takeover premium in the news is high or low.
- **CV:** Trading comps, precedent transactions, and DCF are the three pillars of a real valuation — having all three built is a complete, textbook-accurate set.

### Valuation summary ("football field") generator
- **Does:** Takes the output of the DCF, comps, and precedents tools and plots them as the classic overlapping valuation-range bar chart bankers use to summarize a stock's fair value.
- **Personal:** Gives you one clear picture — is this stock cheap or not — instead of three separate spreadsheets to reconcile yourself.
- **CV:** This exact chart is a real banker deliverable — having it auto-generate from your own models is a standout portfolio visual.

### M&A accretion/dilution calculator
- **Does:** Models whether a hypothetical acquisition would raise or lower the acquirer's EPS.
- **Personal:** Mostly CV-driven, but if a stock you own is ever the target of a takeover, this is exactly the math behind whether the market's reaction makes sense.
- **CV:** One of the three classic IB technical questions alongside DCF and LBO — having all three built makes the portfolio unusually complete.

## Asset & Wealth Management

### Hedge fund project (planned)
- **Does:** Simulates running a small fund — thesis-driven positions, position sizing, and a basic risk/drawdown limit.
- **Personal:** Lets you paper-trade your own investment ideas with real position-sizing discipline instead of a hunch.
- **CV:** Shows you can think like a portfolio manager, not just a stock picker — most student projects never demonstrate this.

### Portfolio optimizer
- **Does:** Uses mean-variance optimization (or risk-parity) to build the "best" asset mix for a given risk tolerance.
- **Personal:** Run your own real or paper portfolio through it and see if you're actually as diversified as you think.
- **CV:** Modern portfolio theory shows up in nearly every asset/wealth management interview — you'll have built it, not just studied it.

### Compound growth / retirement projector
- **Does:** Projects your own savings and investments decades forward under different contribution and return assumptions — and doubles as an "opportunity cost" mode for any big purchase (what does skipping a purchase do to your net worth in 10 years?).
- **Personal:** One you'll genuinely use to plan your own retirement, savings targets, and everyday spending trade-offs.
- **CV:** Demonstrates time-value-of-money fluency as a working tool — a strong signal specifically for wealth management interviews.

### Dividend reinvestment (DRIP) tracker
- **Does:** Tracks a real or paper dividend-paying portfolio and simulates the compounding effect of reinvesting dividends.
- **Personal:** You can run this against your own holdings the moment you start investing, if you haven't already.
- **CV:** A concrete demonstration of compounding — a concept everyone claims to understand but rarely models.

### Factor / smart-beta screener
- **Does:** Ranks stocks by classic factors — value, momentum, quality, low-volatility — and shows how a factor-tilted portfolio would have performed.
- **Personal:** Gives you a research-backed alternative to picking stocks on gut feeling.
- **CV:** Factor investing is core language in asset management interviews — showing you can screen and test factors yourself goes beyond reciting the theory.

## Risk Management

### Credit/default risk scorer (planned)
- **Does:** Uses a public loan dataset (e.g. Lending Club) to predict the probability a borrower defaults.
- **Personal:** Less of a daily tool, but the same logic informally applies when you're weighing your own borrowing decisions.
- **CV:** Risk teams do exactly this kind of modeling — very few student portfolios include a risk-side project, so it stands out.

### Monte Carlo VaR simulator
- **Does:** Runs thousands of simulated future scenarios for a portfolio to estimate potential downside losses.
- **Personal:** Quantifies the actual risk sitting in your own forex bot or portfolio, instead of a gut feeling.
- **CV:** VaR is one of the most universally referenced risk concepts across banks — an easy, memorable interview story.

### Stress testing tool
- **Does:** Replays historical crisis scenarios (2008, the 2020 crash) against your current portfolio to show what a repeat would do to it.
- **Personal:** A genuinely sobering, useful gut-check on your own real risk tolerance before markets test it for you.
- **CV:** Stress testing is standard at every bank's risk function post-2008 — pairs naturally with the VaR simulator to show both angles.

### FX hedging calculator
- **Does:** Calculates hedge ratios and forward-rate pricing to offset currency exposure on a position or cash flow.
- **Personal:** Directly useful if you study or intern abroad and want to protect the value of money you're moving between currencies.
- **CV:** Ties your forex bot skills to a genuine corporate/risk use case, not just speculative trading.

## Economics & Macro

### Macro/economics dashboard (planned)
- **Does:** Pulls live inflation, interest rate, GDP, and unemployment data (free FRED API) into one view.
- **Personal:** Keeps you genuinely informed about the economy affecting your own money, not just headlines.
- **CV:** Shows you track markets proactively — a low-effort, high-value talking point in any markets interview.

### Bond & yield curve calculator (planned)
- **Does:** Calculates bond duration, convexity, and price changes under rate-shock scenarios, and flags yield curve inversions as a recession-probability signal.
- **Personal:** Shows exactly what rising or falling rates do to your own savings, or a future loan.
- **CV:** Fixed income is under-represented in most student portfolios — everyone builds equity/FX tools, so this differentiates you.

### Real cost-of-living / inflation-adjusted spending calculator
- **Does:** Takes your actual spending (from the budget tracker) and shows it in real vs. nominal terms, or compares cost of living across cities.
- **Personal:** Genuinely relevant soon — comparing a banking offer in one city vs. another is exactly this calculation.
- **CV:** Connects a macro concept (inflation/CPI) to a real personal decision — a better story than a dashboard alone.

## Personal Finance (daily use)

### Budget tracker (planned)
- **Does:** Logs and categorizes spending, shows what's left in each category.
- **Personal:** The most directly useful tool here — you'll open this constantly.
- **CV:** Less flashy than the trading tools, but shows you can ship a complete, working app end-to-end.

### Net worth aggregator
- **Does:** Combines your bank balance, investments, and forex bot P&L into one running number/chart.
- **Personal:** Answers "am I actually getting richer?" at a glance — genuinely satisfying to watch over time.
- **CV:** Becomes the natural homepage of the whole hub — a strong visual to open an interview walkthrough with.

### Student loan / debt payoff optimizer
- **Does:** Models different payoff strategies (avalanche vs. snowball) against loan terms.
- **Personal:** Build it now with placeholder numbers and it's ready the moment it's real.
- **CV:** Practical, relatable personal finance modeling — evidence you think about money the way a future banker should.

### Job offer & compensation comparison calculator
- **Does:** Compares multiple job offers side by side — base, bonus, signing, benefits, cost of living, taxes — including present value.
- **Personal:** You'll need exactly this in the next year or two comparing internship or full-time banking offers.
- **CV:** Shows you understand total compensation structures — subtle but real, and genuinely useful before you need it.

### Subscription / recurring payment auditor
- **Does:** Scans your transactions for recurring charges and flags ones you've forgotten about or barely use.
- **Personal:** An almost guaranteed way to find money you're currently wasting — genuinely pays for itself in five minutes.
- **CV:** Small and simple, but a nice "shipped something people actually want" project to mention alongside the bigger ones.

### Emergency fund / financial safety-net calculator
- **Does:** Compares your liquid savings to your real monthly expenses (from the budget tracker) and shows how many months you're covered.
- **Personal:** A genuinely important number to actually know about yourself, especially before taking on any investment risk elsewhere.
- **CV:** Shows sound personal financial judgment — a good, honest answer if a banking interviewer ever asks how you think about risk in your own life.

## The Hub Itself (glue layer)

### Performance/risk scoreboard
- **Does:** Calculates Sharpe ratio, max drawdown, and volatility the same way across every trading/investing project.
- **Personal:** Tells you honestly which of your own strategies are actually good versus just lucky.
- **CV:** Standardized performance measurement is how real funds compare strategies — shows maturity beyond "my bot made money."

### Alerts engine
- **Does:** Watches simple rules (budget over X, a yield moved Y bps) and surfaces them automatically.
- **Personal:** The part that actually makes the hub feel like a brain instead of screens you have to remember to check.
- **CV:** Event-driven design (rules, triggers, notifications) is a real software pattern, not only a finance one.

### News/sentiment feed
- **Does:** Pulls headlines relevant to your watchlist and scores them for sentiment.
- **Personal:** Keeps you from missing news that actually matters to your positions.
- **CV:** A small NLP component adds range to the portfolio without needing a whole separate project.

### Personal "earnings report" generator
- **Does:** Auto-writes a weekly or monthly summary of your own finances in the format of a company earnings report — net worth as "revenue growth," spending vs. budget as a "beat/miss," plus a short written commentary section.
- **Personal:** Turns checking in on your finances into something closer to reading a report than digging through numbers.
- **CV:** A genuinely memorable, distinctly finance-flavored idea for an interview — most students won't have thought to frame their own life this way.

### Scenario / what-if simulator
- **Does:** Lets you flow a hypothetical change (a bonus, a rent increase, a new job's salary) through the whole hub at once — net worth, budget, retirement projection — instead of recalculating each tool by hand.
- **Personal:** The single most useful feature for actual decisions — "should I take this job" or "can I afford this" answered in one place.
- **CV:** Shows the hub isn't just a set of tiles but an actual connected system — the strongest evidence of real systems thinking in the whole portfolio.

## Health & Performance

### Tennis training tracker
- **Does:** Logs training load, match results, and upcoming fixtures over a season to show form and trends.
- **Personal:** Directly useful for your own training — you'll look at this one for reasons that have nothing to do with finance.
- **CV:** Less directly bank-relevant, but shows you ship things for yourself, not only for a resume — a good answer to "tell me about a project outside of finance."

## Using this list

You don't need all 35 before this is worth showing off — the architecture doc's build order gets you a working hub after just the first few. Treat this as the full menu, not a checklist. If anything here feels redundant once you're actually building, cut it — the goal was to be exhaustive on paper, not to force you to build all of it.
