"""Generate the synthetic 'Adire Market' e-commerce dataset (Nigeria, Jan 2024 to Oct 2026).

Run from the repo root:  python src/generate_data.py

Built-in patterns, so the analysis has real stories to find:
  * Prices inflate about 28% a year, so naira revenue grows faster than real demand
  * Q4 is huge: Black Friday (late Nov) and December peaks, with delivery delays and payment failures
  * Acquisition channels differ in cost and in customer quality (TikTok is cheap but its customers rarely return)
  * TikTok's share of new customers grows over time, quietly lowering overall repeat rate
  * Payment method drives failures (USSD) and refusals at the door (pay on delivery)
  * Slow delivery cities (Kano, Port Harcourt) retain customers worse
"""
import calendar

import numpy as np
import pandas as pd

rng = np.random.default_rng(2026)

MONTHS = pd.period_range("2024-01", "2026-10", freq="M")
M = len(MONTHS)
PRICE_INDEX = 1.021 ** np.arange(M)                       # ~28% a year
SEASON = {1: .85, 2: .90, 3: .95, 4: 1.0, 5: .95, 6: .95, 7: .95, 8: 1.0, 9: 1.0, 10: 1.05, 11: 1.7, 12: 1.45}
season = np.array([SEASON[p.month] for p in MONTHS])
acq_season = 1 + .6 * (season - 1)

# ---------------------------------------------------------------- channels
CH = {  # name: (base share, CAC at 2024 prices, monthly churn hazard, order propensity, order value multiplier)
    "Organic Search": (.27, 0, .07, 1.00, 1.00),
    "WhatsApp Referral": (.10, 900, .05, 1.25, 1.05),
    "Instagram Ads": (.22, 2400, .11, .90, 1.00),
    "TikTok Ads": (.20, 1600, .20, .70, .85),
    "Google Ads": (.13, 3100, .08, 1.05, 1.10),
    "Influencer": (.08, 4200, .15, .80, 1.00),
}
chs = list(CH)

# ---------------------------------------------------------------- cities
CITY = {  # share, delivery days, delivery cost factor, propensity factor, churn factor
    "Lagos": (.38, 2.1, 1.0, 1.00, 1.00),
    "Abuja": (.14, 3.5, 1.3, .95, 1.00),
    "Ibadan": (.08, 2.8, 1.1, .95, 1.00),
    "Port Harcourt": (.10, 4.0, 1.5, .85, 1.10),
    "Kano": (.08, 5.2, 1.9, .75, 1.25),
    "Enugu": (.06, 4.2, 1.5, .85, 1.10),
    "Benin City": (.07, 4.5, 1.5, .85, 1.10),
    "Other cities": (.09, 5.0, 1.8, .80, 1.15),
}
cities = list(CITY)

CATEGORY = {  # weight, base price (NGN, 2024), gross margin
    "Fashion": (.26, 16000, .38),
    "Phones & Accessories": (.20, 22000, .22),
    "Beauty": (.17, 9000, .45),
    "Home & Kitchen": (.15, 26000, .30),
    "Groceries": (.12, 14000, .16),
    "Electronics": (.10, 85000, .12),
}
cats = list(CATEGORY)

# ---------------------------------------------------------------- new customers by month and channel
n_new = np.round(250 * 1.03 ** np.arange(M) * acq_season * rng.normal(1, .05, M)).astype(int)
cust_rows = []
for m in range(M):
    tiktok = .08 + (.28 - .08) * m / (M - 1)               # TikTok share rises 8% -> 28%
    sh = np.array([CH[c][0] for c in chs], dtype=float)
    sh[chs.index("TikTok Ads")] = 0
    sh = sh / sh.sum() * (1 - tiktok)
    sh[chs.index("TikTok Ads")] = tiktok
    ch_idx = rng.choice(len(chs), n_new[m], p=sh)
    cust_rows.append(pd.DataFrame({"acq_month": m, "channel": np.array(chs)[ch_idx]}))
cust = pd.concat(cust_rows, ignore_index=True)
N = len(cust)
cust["customer_id"] = [f"C{i:06d}" for i in range(1, N + 1)]
cust["city"] = rng.choice(cities, N, p=[CITY[c][0] for c in cities])
cust["device"] = rng.choice(["Mobile app", "Mobile web", "Desktop"], N, p=[.42, .38, .20])


def attr(col, idx):
    return cust.channel.map(lambda c: CH[c][idx]).values if col == "channel" else cust.city.map(lambda c: CITY[c][idx]).values


p_base = .16 * attr("channel", 3) * attr("city", 3) * rng.lognormal(0, .5, N)
hazard = np.clip(attr("channel", 2) * attr("city", 4) * rng.lognormal(0, .25, N), .01, .6)

# ---------------------------------------------------------------- simulate monthly activity
alive = np.ones(N, dtype=bool)
order_cust, order_month = [], []
for m in range(M):
    first = cust.acq_month.values == m
    order_cust.append(np.where(first)[0]); order_month.append(np.full(first.sum(), m))
    started = cust.acq_month.values < m
    alive &= ~(started & (rng.random(N) < hazard))
    prob = np.clip(p_base * season[m], 0, .6)
    buys = started & alive & (rng.random(N) < prob)
    n_extra = buys & (rng.random(N) < .15)
    for mask in (buys, n_extra):
        order_cust.append(np.where(mask)[0]); order_month.append(np.full(mask.sum(), m))
ci = np.concatenate(order_cust)
mi = np.concatenate(order_month)
n = len(ci)


def day_of(m, forced_first):
    p = MONTHS[m]
    days = calendar.monthrange(p.year, p.month)[1]
    d = rng.integers(1, days + 1)
    if p.month == 11 and rng.random() < .5:
        d = rng.integers(20, 31)                          # Black Friday window
    return pd.Timestamp(p.year, p.month, int(d))


dates = pd.to_datetime([day_of(m, False) for m in mi])
o = pd.DataFrame({"customer_idx": ci, "m": mi, "order_date": dates})
o = o.sort_values(["order_date", "customer_idx"]).reset_index(drop=True)
o["order_id"] = [f"ORD{i:07d}" for i in range(1, n + 1)]
o["customer_id"] = cust.customer_id.values[o.customer_idx]
o["city"] = cust.city.values[o.customer_idx]
o["channel"] = cust.channel.values[o.customer_idx]
o["device"] = cust.device.values[o.customer_idx]
bf = ((o.order_date.dt.month == 11) & (o.order_date.dt.day >= 20)).values
dec = (o.order_date.dt.month == 12).values
o["black_friday_window"] = np.where(bf, "Yes", "No")

# category, units, price, discount
o["category"] = rng.choice(cats, n, p=[CATEGORY[c][0] for c in cats])
o["units"] = np.where(o.category == "Electronics", rng.choice([1, 2], n, p=[.9, .1]), rng.choice([1, 2, 3], n, p=[.65, .25, .10]))
price_idx = PRICE_INDEX[o.m.values]
base = o.category.map(lambda c: CATEGORY[c][1]).values
cmult = o.channel.map(lambda c: CH[c][4]).values
o["unit_price"] = np.round(base * price_idx * cmult * rng.lognormal(0, .25, n), -1)
disc = rng.choice([0, .05, .10], n, p=[.55, .25, .20])
disc = np.where(dec, rng.choice([.05, .10, .15], n), disc)
disc = np.where(bf, rng.choice([.15, .20, .25, .30, .35], n), disc)
o["discount"] = disc
o["gross_value"] = np.round(o.units * o.unit_price * (1 - o.discount), -1)
gm = o.category.map(lambda c: CATEGORY[c][2]).values
cogs = o.units * o.unit_price * (1 - gm)
o["cogs"] = np.round(cogs, -1)
cf = o.city.map(lambda c: CITY[c][2]).values
o["delivery_cost"] = np.round(1200 * PRICE_INDEX[o.m.values] ** .8 * cf, -1)

# payment method and outcome
o["payment_method"] = np.where(
    o.device.eq("Desktop"),
    rng.choice(["Card", "Bank transfer", "USSD", "Pay on delivery"], n, p=[.46, .30, .06, .18]),
    rng.choice(["Card", "Bank transfer", "USSD", "Pay on delivery"], n, p=[.34, .27, .14, .25]))
fail = {"Card": .07, "Bank transfer": .05, "USSD": .13, "Pay on delivery": .0}
refuse = {"Card": 0, "Bank transfer": 0, "USSD": 0, "Pay on delivery": .15}
ret = .03
pf = o.payment_method.map(fail).values + np.where(bf, .04, 0) * (o.payment_method != "Pay on delivery")
pr = o.payment_method.map(refuse).values + np.where(bf, .04, 0) * (o.payment_method == "Pay on delivery")
u = rng.random(n)
status = np.where(u < pf, "Cancelled (payment failed)",
          np.where(u < pf + pr, "Refused at delivery",
          np.where(u < pf + pr + ret, "Returned", "Delivered")))
o["order_status"] = status
ddays = o.city.map(lambda c: CITY[c][1]).values + np.where(bf, 1.5, 0) + np.where(dec, .6, 0)
o["delivery_days"] = np.where(np.isin(status, ["Cancelled (payment failed)"]), np.nan,
                              np.clip(np.round(rng.normal(ddays, 1.1)), 1, 14))
o["ship_date"] = o.order_date + pd.to_timedelta(o.delivery_days.fillna(0), unit="D")
o.loc[o.delivery_days.isna(), "ship_date"] = pd.NaT
delivered = o.order_status.eq("Delivered")
o["realised_revenue"] = np.where(delivered, o.gross_value, 0)
o["contribution"] = np.where(delivered, o.gross_value - o.cogs - o.delivery_cost,
                     np.where(o.order_status.isin(["Refused at delivery", "Returned"]), -2 * o.delivery_cost, 0))

orders = o[["order_id", "order_date", "customer_id", "city", "device", "channel", "category", "units", "unit_price",
            "discount", "gross_value", "cogs", "delivery_cost", "payment_method", "order_status", "delivery_days",
            "ship_date", "black_friday_window", "realised_revenue", "contribution"]].copy()

# ---------------------------------------------------------------- customers table
first_dates = orders.groupby("customer_id").order_date.min()
customers = pd.DataFrame({"customer_id": cust.customer_id, "acquisition_channel": cust.channel,
                          "city": cust.city, "primary_device": cust.device})
customers["first_order_date"] = customers.customer_id.map(first_dates)

# ---------------------------------------------------------------- marketing spend
new_by = cust.groupby(["acq_month", "channel"]).size().unstack(fill_value=0).reindex(columns=chs, fill_value=0)
spend_rows = []
for m in range(M):
    for c in chs:
        cac0 = CH[c][1]
        if c == "Organic Search":
            spend = 120000 * PRICE_INDEX[m]                  # content and SEO retainer
        elif c == "WhatsApp Referral":
            spend = new_by.loc[m, c] * cac0 * PRICE_INDEX[m] ** .7   # referral rewards
        else:
            spend = new_by.loc[m, c] * cac0 * PRICE_INDEX[m] ** .7 * rng.normal(1.15, .06)
        spend_rows.append((MONTHS[m].to_timestamp(), c, int(new_by.loc[m, c]), round(spend, -2)))
spend = pd.DataFrame(spend_rows, columns=["month", "channel", "new_customers", "spend"])

# ---------------------------------------------------------------- funnel by month and device
orders["month"] = orders.order_date.dt.to_period("M").dt.to_timestamp()
fn = orders.groupby(["month", "device"]).agg(orders_placed=("order_id", "size"),
                                             delivered=("order_status", lambda s: (s == "Delivered").sum())).reset_index()
conv = {"Mobile app": .052, "Mobile web": .021, "Desktop": .033}
atc = {"Mobile app": .12, "Mobile web": .09, "Desktop": .11}
chk = {"Mobile app": .66, "Mobile web": .55, "Desktop": .64}
fn["sessions"] = np.round(fn.orders_placed / fn.device.map(conv) * rng.normal(1, .04, len(fn))).astype(int)
fn["add_to_cart"] = np.round(fn.sessions * fn.device.map(atc) * rng.normal(1, .03, len(fn))).astype(int)
fn["checkout_started"] = np.round(fn.orders_placed / fn.device.map(chk) * rng.normal(1, .02, len(fn))).astype(int)
funnel = fn[["month", "device", "sessions", "add_to_cart", "checkout_started", "orders_placed", "delivered"]]

price_idx_df = pd.DataFrame({"month": [p.to_timestamp() for p in MONTHS], "price_index": np.round(PRICE_INDEX, 4)})

orders.drop(columns="month").to_csv("data/raw/orders.csv", index=False)
customers.to_csv("data/raw/customers.csv", index=False)
spend.to_csv("data/raw/marketing_spend.csv", index=False)
funnel.to_csv("data/raw/funnel.csv", index=False)
price_idx_df.to_csv("data/raw/price_index.csv", index=False)

print(f"{len(orders):,} orders, {len(customers):,} customers, {M} months")
print(f"gross value NGN {orders.gross_value.sum()/1e9:.2f}bn; realised NGN {orders.realised_revenue.sum()/1e9:.2f}bn")
print(orders.groupby(orders.order_date.dt.year).agg(orders=("order_id", "size"), realised=("realised_revenue", "sum")).round(0))
