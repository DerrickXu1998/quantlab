# User workflow: generating a trading strategy with QuantLab

QuantLab is a research terminal for systematic strategies. The workflow moves
from a broad universe of instruments, through a screen or company view, into a
backtested strategy, and finally into a saved experiment you can compare against
others.

> **Demo vs live data.** Every number carries a small tag: **Live history** means
> the active dataset is real ingested history; **Demo data** means synthetic
> prices and instruments; **Simulated** means the value is generated locally (the
> tick feed, execution book, and forward marks). A thin demo strip also appears
> across the top of the app when the active dataset is synthetic.

---

## 1. Pick a universe

A strategy needs a list to trade. QuantLab publishes named **universes** from
the warehouse (for example, `all`, `us`, `uk`, or a custom list you create).

- Go to **Strategies**.
- Under **Universe & window**, use the presets (**All US**, **All UK**,
  **Everything**) or search for individual tickers.
- When you have a list you want to reuse, click **Save as universe**, give it a
  name, and it becomes available in the **Research > Screen** universe dropdown.

The warehouse stores universe membership as a dated snapshot, so a screen run
against `2024-01-01` uses the members as of that date, not today's survivors.

---

## 2. Research the opportunity

Two starting points feed into a strategy.

### 2a. Screen by filed ratios

- Go to **Research > Screen**.
- Choose a universe, an *as-of* date, and add constraints such as
  `pe_ratio < 15`, `gross_margin > 0.4`, or `debt_to_equity < 1`.
- Click **Run screen**. The result table shows which names passed, which failed,
  and which were never measured (an important distinction: "no filing" is not
  the same as "failed").
- Click any row to open the company page.

### 2b. Inspect a single company

- Go to **Research > Company** and enter a symbol.
- The page shows price bounds, filed fundamentals, signal history, and model
  coverage as of the selected date.
- Click a signal row to carry that rule over to the strategy builder.

---

## 3. Build the strategy

- Go to **Strategies**.
- The **Signal catalogue** lists every registered rule, grouped by category.
  Each card says which roles (entry, exit, filter) the rule supports.
- Click a rule to add it as an entry, exit, or filter.
- Configure parameters in the **Your strategy** panel.
- Choose the **entry logic** and **exit logic**:
  - **All must fire** — every entry component must be active.
  - **Any may fire** — one active entry is enough.
  - **Majority** — more than half.
  - **Weighted** — active components must sum to the threshold you set.
- Set the **agreement window** (how many bars components may agree within) and
  **execution criteria** (capital, sizing, stops, slippage, commission).

The **In plain English** box at the top rewrites the assembled strategy into a
sentence, so you can check it matches your intention before running it.

---

## 4. Run the backtest

- Set the **start** and **end** dates under **Universe & window**.
- Click **Run backtest**.
- The **Results** panel shows:
  - coverage (how many instruments had data),
  - the equity curve versus buy-and-hold,
  - a trade log,
  - an exit-reason breakdown,
  - and the assumptions the run used.

If the run produced signals but no fills, check the execution summary: rejected
entries because of max positions, cooldown, or shorts being disabled are shown
explicitly.

---

## 5. Save and compare

- In the results header, type a name and click **Save experiment**.
- Go to **Overview**. The saved run appears in the **Runs** rail on the left.
- Select it to see the hero summary, equity curve, and open positions.
- The dataset tag (**Live history** or **Demo data**) tells you whether this run
  is comparable to the current dataset. Runs recorded against a different
  dataset are marked **Not reproducible**.

---

## 6. Iterate

- Return to **Strategies**, load the saved strategy from the **Your strategies**
  panel, change a parameter or swap a rule, and run again.
- Use the saved experiments in **Overview** to compare versions side by side.
- When you are ready to trade, the **Execution** destination lets you paper-trade
  against the simulated feed. Everything in Execution is simulated: there is no
  broker connection, fills are immediate, and the book is generated around the
  feed price.

---

## Keyboard and accessibility notes

- The screen constraint form, strategy catalogue, and run results are keyboard
  reachable.
- Delete actions (strategies and runs) are two-step: click the trash icon, then
  **Confirm**.
- Every panel states its purpose on its face; a simulated dataset is tagged
  inline rather than hidden in a footnote.
