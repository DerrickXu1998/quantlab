# ruff: noqa: E501  (generated: Tiingo descriptions are kept verbatim)
"""Tiingo fundamentals field definitions: what each statement dataCode means.

Generated from ``GET /tiingo/fundamentals/definitions`` (85 fields, fetched
2026-10-05) so the research page can label a stored ``tag`` without a
network call. Reference data, not configuration: a code Tiingo adds later
still renders, under its raw dataCode, until this is regenerated.
"""

from __future__ import annotations

from typing import NamedTuple


class TiingoField(NamedTuple):
    statement: str
    name: str
    #: "$", "%" (held as a fraction: 0.12 is 12%) or "" (a count or a ratio).
    units: str
    description: str


#: dataCode -> definition, ordered income statement, balance sheet, cash
#: flow, overview -- the order the page shows them in.
FIELDS: dict[str, TiingoField] = {
    'consolidatedIncome': TiingoField(
        'incomeStatement',
        'Consolidated Income',
        '$',
        'The portion of profit or loss for the period, net of income taxes, which is attributable to the consolidated entity.',
    ),
    'costRev': TiingoField(
        'incomeStatement',
        'Cost of Revenue',
        '$',
        'The aggregate cost of goods produced and sold and services rendered during the reporting period.',
    ),
    'ebit': TiingoField(
        'incomeStatement',
        'Earning Before Interest & Taxes EBIT',
        '$',
        'Earning Before Interest & Taxes (EBIT)',
    ),
    'ebitda': TiingoField(
        'incomeStatement',
        'EBITDA',
        '$',
        'EBITDA is a non-GAAP accounting metric that is widely used when assessing the performance of companies, calculated by adding Depreciation/Amortization back to Earnings before interest and taxes',
    ),
    'ebt': TiingoField(
        'incomeStatement',
        'Earnings before tax',
        '$',
        'Revenue - Expenses and excluding tax',
    ),
    'eps': TiingoField(
        'incomeStatement',
        'Earnings Per Share',
        '$',
        'Earnings per basic share (not diluted)',
    ),
    'epsDil': TiingoField(
        'incomeStatement',
        'Earnings Per Share Diluted',
        '$',
        'EPS for diluted shares',
    ),
    'grossProfit': TiingoField(
        'incomeStatement',
        'Gross Profit',
        '$',
        'Aggregate revenue [REVENUE] less cost of revenue [COR] directly attributable to the revenue generation activity.',
    ),
    'intexp': TiingoField(
        'incomeStatement',
        'Interest Expense',
        '$',
        'Interest expense',
    ),
    'netinc': TiingoField(
        'incomeStatement',
        'Net Income',
        '$',
        'Net income',
    ),
    'netIncComStock': TiingoField(
        'incomeStatement',
        'Net Income Common Stock',
        '$',
        'Net Income applied to common share holders. Used in calculating EPS (earnings per share).',
    ),
    'netIncDiscOps': TiingoField(
        'incomeStatement',
        'Net Income from Discontinued Operations',
        '$',
        'Net income from discontinued operations',
    ),
    'nonControllingInterests': TiingoField(
        'incomeStatement',
        'Net Income to Non-Controlling Interests',
        '$',
        'The portion of income which is attributable to non-controlling interest shareholders, subtracted from consolidated income in order to obtain net income',
    ),
    'opex': TiingoField(
        'incomeStatement',
        'Operating Expenses',
        '$',
        'Operating expenses represents the total expenditure on SG&A, R&D and other operating expense items, it excludes cost of revenue.',
    ),
    'opinc': TiingoField(
        'incomeStatement',
        'Operating Income',
        '$',
        'Operating income is a measure of financial performance before the deduction of interest expense, tax expenses and other Non-Operating items. It is calculated as gross profit minus operating expenses',
    ),
    'prefDVDs': TiingoField(
        'incomeStatement',
        'Preferred Dividends Income Statement Impact',
        '$',
        "Impact of dividend on company's preferred shares",
    ),
    'revenue': TiingoField(
        'incomeStatement',
        'Revenue',
        '$',
        'Revenue',
    ),
    'rnd': TiingoField(
        'incomeStatement',
        'Research & Development',
        '$',
        'The aggregate costs incurred in a planned search or critical investigation aimed at discovery of new knowledge with the hope that such knowledge will be useful in developing a new product or service.',
    ),
    'sga': TiingoField(
        'incomeStatement',
        'Selling, General & Administrative',
        '$',
        "The aggregate total costs related to selling a firm's product and services, as well as all other general and administrative expenses. Direct selling expenses (for example, credit, warranty, and advertising) are expenses that can be directly linked to the sale of specific products. Indirect selling expenses are expenses that cannot be directly linked to the sale of specific products, for example telephone expenses, Internet, and postal charges. General and administrative expenses include salaries",
    ),
    'shareswa': TiingoField(
        'incomeStatement',
        'Weighted Average Shares',
        '',
        'Weighted average shares (undiluted)',
    ),
    'shareswaDil': TiingoField(
        'incomeStatement',
        'Weighted Average Shares Diluted',
        '',
        'Used to calculated diluted EPS. Considers all outstanding common stock plus all instruments that can be converted into shares (like stock options)',
    ),
    'taxExp': TiingoField(
        'incomeStatement',
        'Tax Expense',
        '$',
        'Tax expenses',
    ),
    'accoci': TiingoField(
        'balanceSheet',
        'Accumulated Other Comprehensive Income',
        '$',
        "Unrealized gains and losses - such as items that have changed in value but haven't been bought or sold yet",
    ),
    'acctPay': TiingoField(
        'balanceSheet',
        'Accounts Payable',
        '$',
        'Short-term debt the company must pay off within a year',
    ),
    'acctRec': TiingoField(
        'balanceSheet',
        'Accounts Receivable',
        '$',
        'Amount company will receive based on work already completed and delivered',
    ),
    'assetsCurrent': TiingoField(
        'balanceSheet',
        'Current Assets',
        '$',
        'Assets that can easily be converted to cash and can be used to fund day-to-day operations',
    ),
    'assetsNonCurrent': TiingoField(
        'balanceSheet',
        'Other Assets',
        '$',
        'Assets that cannot be easily converted into cash and where the value of the item will be realized in a year',
    ),
    'cashAndEq': TiingoField(
        'balanceSheet',
        'Cash and Equivalents',
        '$',
        'Cash or assets that can be converted to cash immediately',
    ),
    'debt': TiingoField(
        'balanceSheet',
        'Total Debt',
        '$',
        'Debt',
    ),
    'debtCurrent': TiingoField(
        'balanceSheet',
        'Current Debt',
        '$',
        'Current debt - debt due within a year',
    ),
    'debtNonCurrent': TiingoField(
        'balanceSheet',
        'Non-Current Debt',
        '$',
        'Longer-term debt, typically greater than a year',
    ),
    'deferredRev': TiingoField(
        'balanceSheet',
        'Deferred Revenue',
        '$',
        'Revenue that was received, but not yet paid out including sales, license fees, and royalties, but excluding interest income.',
    ),
    'deposits': TiingoField(
        'balanceSheet',
        'Deposits',
        '$',
        'Deposit liabilities, both domestic and international including deposits such as savings deposts',
    ),
    'equity': TiingoField(
        'balanceSheet',
        'Shareholders Equity',
        '$',
        'Shareholders Equity',
    ),
    'intangibles': TiingoField(
        'balanceSheet',
        'Intangible Assets',
        '$',
        'Goodwill and Intangible Assets',
    ),
    'inventory': TiingoField(
        'balanceSheet',
        'Inventory',
        '$',
        'A component of Total Assets representing the amount after valuation and reserves of inventory expected to be sold, or consumed within one year or operating cycle, if longer.',
    ),
    'investments': TiingoField(
        'balanceSheet',
        'Investments',
        '$',
        'A component of assets representing the total amount of marketable and non-marketable securties, loans receivable and other invested assets.',
    ),
    'investmentsCurrent': TiingoField(
        'balanceSheet',
        'Current Investments',
        '$',
        'The current portion of Investments, reported if the company operates a classified balance sheet that segments current and non-current assets.',
    ),
    'investmentsNonCurrent': TiingoField(
        'balanceSheet',
        'Non-Current Investments',
        '$',
        'The non-current portion of investments, reported if the company operates a classified balance sheet that segments current and non-current assets.',
    ),
    'liabilitiesCurrent': TiingoField(
        'balanceSheet',
        'Current Liabilities',
        '$',
        'Debt or liabilities that are due within a year',
    ),
    'liabilitiesNonCurrent': TiingoField(
        'balanceSheet',
        'Other Liabilities',
        '$',
        'Long-term liabilities (like debt) that are not due within a year',
    ),
    'ppeq': TiingoField(
        'balanceSheet',
        'Property, Plant & Equipment',
        '$',
        'A component of assets representing the total amount of marketable and non-marketable securties, loans receivable and other invested assets.',
    ),
    'retainedEarnings': TiingoField(
        'balanceSheet',
        'Accumulated Retained Earnings or Deficit',
        '$',
        "A component of Shareholder's Equity representing the cumulative amount of the entities undistributed earnings or deficit. May only be reported annually by certain companies, rather than quarterly.",
    ),
    'sharesBasic': TiingoField(
        'balanceSheet',
        'Shares Outstanding',
        '',
        'Outstanding shares',
    ),
    'taxAssets': TiingoField(
        'balanceSheet',
        'Tax Assets',
        '$',
        'A component of assets representing tax assets and receivables.',
    ),
    'taxLiabilities': TiingoField(
        'balanceSheet',
        'Tax Liabilities',
        '$',
        'A component of liabilities representing outstanding tax liabilities.',
    ),
    'totalAssets': TiingoField(
        'balanceSheet',
        'Total Assets',
        '$',
        'Total assets',
    ),
    'totalLiabilities': TiingoField(
        'balanceSheet',
        'Total Liabilities',
        '$',
        'Total Liabilities',
    ),
    'businessAcqDisposals': TiingoField(
        'cashFlow',
        'Business Acquisitions & Disposals',
        '$',
        'A component of cash flow from investing, representing the net cash inflow (outflow) associated with the acquisition & disposal of businesses, joint-ventures, affiliates, and other named investments.',
    ),
    'capex': TiingoField(
        'cashFlow',
        'Capital Expenditure',
        '$',
        'Money uses to upgrade or acquire property or materials to maintain and increase size',
    ),
    'depamor': TiingoField(
        'cashFlow',
        'Depreciation, Amortization & Accretion',
        '$',
        'Depreciation, Amortization, and Accretion',
    ),
    'freeCashFlow': TiingoField(
        'cashFlow',
        'Free Cash Flow',
        '$',
        'Operating Cash Flow - Capex, How much cash is left over after reinvesting it in the business. Used as a measure to evaluate financial performance of a company',
    ),
    'investmentsAcqDisposals': TiingoField(
        'cashFlow',
        'Investment Acquisitions & Disposals',
        '$',
        'A component of cash flow from financing, representing the net cash inflow (outflow) associated with the acquisition & disposal of investments, including marketable securities and loan originations.',
    ),
    'issrepayDebt': TiingoField(
        'cashFlow',
        'Issuance or Repayment of Debt Securities',
        '$',
        'Representing the net cash inflow (outflow) from issuance (repayment) of debt securities.',
    ),
    'issrepayEquity': TiingoField(
        'cashFlow',
        'Issuance or Repayment of Equity',
        '$',
        'Representing the net cash inflow (outflow) from issuance (repayment) of equity.',
    ),
    'ncf': TiingoField(
        'cashFlow',
        'Net Cash Flow to Change in Cash & Cash Equivalents',
        '$',
        'Net Cash flow - Total cash minux liabilities',
    ),
    'ncff': TiingoField(
        'cashFlow',
        'Net Cash Flow from Financing',
        '$',
        'Net Cash flow from financing activities like issuing stock or debt minus dividends or acquiring debt',
    ),
    'ncfi': TiingoField(
        'cashFlow',
        'Net Cash Flow from Investing',
        '$',
        'Cash flow from investments made by the company',
    ),
    'ncfo': TiingoField(
        'cashFlow',
        'Net Cash Flow from Operations',
        '$',
        "Cash flow generating from a company's operations",
    ),
    'ncfx': TiingoField(
        'cashFlow',
        'Effect of Exchange Rate Changes on Cash',
        '$',
        'Cash flow from exchange rate changes',
    ),
    'payDiv': TiingoField(
        'cashFlow',
        'Payment of Dividends & Other Cash Distributions',
        '$',
        'Representing dividends and dividend equivalents paid on common stock and restricted stock units.',
    ),
    'sbcomp': TiingoField(
        'cashFlow',
        'Shared-based Compensation',
        '$',
        "A component of cash flow from operating activities, representing the total amount of noncash, equity-based employee remuneration. This may include the value of stock or unit options, amortization of restricted stock or units, and adjustment for officers' compensation. As noncash, this element is an add back when calculating net cash generated by operating activities using the indirect method.",
    ),
    'assetTurnover': TiingoField(
        'overview',
        'Asset Turnover',
        '',
        'Revenue over assets',
    ),
    'bookVal': TiingoField(
        'overview',
        'Book Value',
        '$',
        'Book value of the share, assets - liabilities',
    ),
    'bvps': TiingoField(
        'overview',
        'Book Value Per Share',
        '$',
        'Book Value per each share',
    ),
    'currentRatio': TiingoField(
        'overview',
        'Current Ratio',
        '',
        'Ability for a company to pay off its short-term liabilities, Current Assets/Current Liabilities',
    ),
    'debtEquity': TiingoField(
        'overview',
        'Debt to Equity Ratio',
        '',
        'Debt/Equity ratio',
    ),
    'enterpriseVal': TiingoField(
        'overview',
        'Enterprise Value',
        '$',
        "An alternative to marketcap that's the theoretical takeover price of a company (marketcap + debt - cash and cash equivalents)",
    ),
    'epsQoQ': TiingoField(
        'overview',
        'Earnings Per Share QoQ Growth',
        '%',
        'Earnings Per Share Quarter-over-Quarter Growth rate',
    ),
    'fxRate': TiingoField(
        'overview',
        'FX Rate',
        '',
        'The exchange rate used for the conversion of foreign currency to USD for non-US companies that do not report in USD.',
    ),
    'grossMargin': TiingoField(
        'overview',
        'Gross Margin',
        '%',
        'The margin of good sold, basically how much of the money the company keeps after selling their goods and services. (Rev.-Cost of Rev.)/Rev.',
    ),
    'longTermDebtEquity': TiingoField(
        'overview',
        'Long-term Debt to Equity',
        '',
        'Long term debt to equity',
    ),
    'marketCap': TiingoField(
        'overview',
        'Market Capitalization',
        '$',
        'Size of the company (shares outstanding * share price)',
    ),
    'netMargin': TiingoField(
        'overview',
        'Net Margin',
        '%',
        'Net Profit Margin, or the Net Income as a proportion of Revenue. In other words, Net Income/Revenue',
    ),
    'opMargin': TiingoField(
        'overview',
        'Operating Margin',
        '%',
        'Operating margin, or how much money a company makes on each dollar of revenue. In other words Operating Income/Revenue',
    ),
    'pbRatio': TiingoField(
        'overview',
        'Price to Book Ratio',
        '',
        'Price/Book value per share ratio',
    ),
    'peRatio': TiingoField(
        'overview',
        'Price to Earnings Ratio',
        '',
        'P/E Ratio',
    ),
    'piotroskiFScore': TiingoField(
        'overview',
        'Piotroski F-Score',
        '',
        "0-9 point scale to determine strength of company's financial position",
    ),
    'profitMargin': TiingoField(
        'overview',
        'Profit Margin',
        '%',
        'This field is marked for DEPRECATION. Please use grossMargin instead. Profit Margin is calculated by the (Revenue - COGS)/Revenue',
    ),
    'revenueQoQ': TiingoField(
        'overview',
        'Revenue QoQ Growth',
        '%',
        'Revenue Quarter-over-Quarter Growth rate',
    ),
    'roa': TiingoField(
        'overview',
        'Return on Assets ROA',
        '%',
        'Net Income/Total Assets',
    ),
    'roe': TiingoField(
        'overview',
        'Return on Equity ROE',
        '%',
        "Return on Shareholder's equity; ROE=Net Income/Shareholder's Equity",
    ),
    'rps': TiingoField(
        'overview',
        'Revenue Per Share',
        '$',
        'Revenue per share',
    ),
    'shareFactor': TiingoField(
        'overview',
        'Share Factor',
        '',
        'Share factor is a multiplicant in the calculation of [MARKETCAP]. For the overwhelming majority of companies its value will be 1. For American Depository Receipts (ADRs) and companies which have different earnings share for different share classes (eg Berkshire Hathaway - BRKB).',
    ),
    'trailingPEG1Y': TiingoField(
        'overview',
        'PEG Ratio',
        '',
        'PEG ratio using the trailing 1 year EPS growth rate in the denominator',
    ),
}
