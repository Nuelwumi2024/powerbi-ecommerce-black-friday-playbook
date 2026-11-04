"""Customer, marketing and operations analysis for the Adire Market case study.

Run from the repo root:  python src/analysis.py
Reads data/raw/*.csv; writes data/processed/*.csv and figures/*.png; prints the numbers quoted in the README.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT, FIG = ROOT / "data" / "raw", ROOT / "data" / "processed", ROOT / "figures"
OUT.mkdir(exist_ok=True); FIG.mkdir(exist_ok=True)
NAVY, TEAL, GREY, RED, AMBER = "#1F3A5F", "#2A9D8F", "#B8C2CC", "#C0392B", "#E9C46A"
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "axes.titleweight": "bold",
                     "axes.titlesize": 12, "figure.dpi": 130})
ASOF = pd.Timestamp("2026-10-31")

orders = pd.read_csv(RAW / "orders.csv", parse_dates=["order_date", "ship_date"])
customers = pd.read_csv(RAW / "customers.csv", parse_dates=["first_order_date"])
spend = pd.read_csv(RAW / "marketing_spend.csv", parse_dates=["month"])
pidx = pd.read_csv(RAW / "price_index.csv", parse_dates=["month"])

orders["month"] = orders.order_date.dt.to_period("M").dt.to_timestamp()
orders = orders.merge(pidx, on="month")
orders["real_revenue"] = orders.realised_revenue / orders.price_index          # constant January-2024 naira
orders["year"] = orders.order_date.dt.year
ytd = orders[orders.order_date.dt.month <= 10]                                 # Jan-Oct, like for like
dl = orders[orders.order_status == "Delivered"]
ngn = lambda x: f"NGN {x/1e6:,.0f}M"

# ----------------------------------------------------------------- 1. nominal vs real growth
g = ytd.groupby("year").agg(orders=("order_id", "size"), customers=("customer_id", "nunique"),
                            nominal=("realised_revenue", "sum"), real=("real_revenue", "sum"),
                            units=("units", "sum"))
g["aov_nominal"] = g.nominal / ytd[ytd.order_status == "Delivered"].groupby("year").size()
print("JAN-OCT BY YEAR\n", g.round(0).to_string())
for a, b in ((2025, 2026), (2024, 2025)):
    print(f"  {a}->{b}: nominal {g.nominal[b]/g.nominal[a]-1:+.1%}, real {g.real[b]/g.real[a]-1:+.1%}, "
          f"orders {g.orders[b]/g.orders[a]-1:+.1%}, AOV {g.aov_nominal[b]/g.aov_nominal[a]-1:+.1%}")
g.to_csv(OUT / "yearly_jan_oct.csv")

# ----------------------------------------------------------------- 2. channel quality: CAC, repeat, 12m CLV
valid = orders[~orders.order_status.eq("Cancelled (payment failed)")]
first = customers.set_index("customer_id").first_order_date
valid = valid.assign(first=valid.customer_id.map(first))
valid["days_since_first"] = (valid.order_date - valid["first"]).dt.days
c12 = valid[valid.days_since_first < 365].groupby("customer_id").contribution.sum()
cust = customers.copy()
cust["contrib_12m"] = cust.customer_id.map(c12).fillna(0)
mature = cust[cust.first_order_date <= ASOF - pd.Timedelta(days=365)]          # a full 12 months of history
n_orders = valid.groupby("customer_id").size()
cust["orders"] = cust.customer_id.map(n_orders).fillna(0)
rep90 = valid[(valid.days_since_first > 0) & (valid.days_since_first <= 90)].groupby("customer_id").size()
cust["repeat_90d"] = cust.customer_id.isin(rep90.index)
cohort90 = cust[cust.first_order_date <= ASOF - pd.Timedelta(days=90)]

sp = spend.groupby("channel").agg(spend=("spend", "sum"), new_customers=("new_customers", "sum"))
sp["cac"] = sp.spend / sp.new_customers
ch = pd.DataFrame({
    "customers": cust.groupby("acquisition_channel").size(),
    "repeat_rate_90d": cohort90.groupby("acquisition_channel").repeat_90d.mean(),
    "orders_per_customer": cust.groupby("acquisition_channel").orders.mean(),
    "contribution_12m": mature.groupby("acquisition_channel").contrib_12m.mean(),
}).join(sp[["spend", "cac"]])
ch["ltv_to_cac"] = ch.contribution_12m / ch.cac
ch["share_of_customers"] = ch.customers / ch.customers.sum()
print("\nCHANNELS\n", ch.round(3).sort_values("ltv_to_cac", ascending=False).to_string())
ch.to_csv(OUT / "channel_summary.csv")

# repeat rate and mix by acquisition quarter
cohort90 = cohort90.assign(q=cohort90.first_order_date.dt.to_period("Q").astype(str))
qr = cohort90.groupby("q").agg(repeat=("repeat_90d", "mean"), n=("customer_id", "size"),
                               tiktok=("acquisition_channel", lambda s: (s == "TikTok Ads").mean()))
print("\nREPEAT (within 90d) BY ACQUISITION QUARTER\n", qr.round(3).to_string())
qr.to_csv(OUT / "repeat_by_quarter.csv")

# blended CAC
bl = spend.assign(y=spend.month.dt.year).groupby("y").agg(spend=("spend", "sum"), new=("new_customers", "sum"))
bl["cac"] = bl.spend / bl.new
print("\nBLENDED CAC BY YEAR\n", bl.round(0).to_string())

# ----------------------------------------------------------------- 3. RFM segmentation (as of 31 Oct 2026)
d = dl.assign(rev=dl.real_revenue)
rfm = d.groupby("customer_id").agg(last=("order_date", "max"), frequency=("order_id", "size"),
                                   monetary=("rev", "sum"), first=("order_date", "min")).reset_index()
rfm["recency_days"] = (ASOF - rfm["last"]).dt.days
rfm["R"] = pd.qcut(rfm.recency_days.rank(method="first", ascending=False), 5, labels=[1, 2, 3, 4, 5]).astype(int)
rfm["F"] = pd.cut(rfm.frequency, [0, 1, 2, 3, 5, 999], labels=[1, 2, 3, 4, 5]).astype(int)
rfm["M"] = pd.qcut(rfm.monetary.rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)


def seg(r):
    if r.R >= 4 and r.F >= 4: return "Champions"
    if r.R >= 3 and r.F >= 3: return "Loyal"
    if r.R <= 2 and r.F >= 4: return "Can't lose them"
    if r.R <= 2 and r.F >= 3: return "At risk"
    if r.R >= 4 and r.F == 1: return "New customers"
    if r.R >= 3 and r.F == 2: return "Potential loyalists"
    if r.R >= 3: return "Promising"
    if r.F >= 2: return "Slipping away"
    return "Hibernating"


rfm["segment"] = rfm.apply(seg, axis=1)
rfm = rfm.merge(customers[["customer_id", "acquisition_channel", "city"]], on="customer_id")
rfm.drop(columns=["last", "first"]).to_csv(OUT / "customer_segments.csv", index=False)
sg = rfm.groupby("segment").agg(customers=("customer_id", "size"), revenue=("monetary", "sum"),
                                avg_recency=("recency_days", "mean"), avg_orders=("frequency", "mean"))
sg["share_customers"] = sg.customers / sg.customers.sum()
sg["share_revenue"] = sg.revenue / sg.revenue.sum()
sg = sg.sort_values("share_revenue", ascending=False)
print("\nRFM SEGMENTS\n", sg.round(3).to_string())
top = rfm.sort_values("monetary", ascending=False)
n10 = int(len(top) * .10)
print(f"top 10% customers = {top.head(n10).monetary.sum()/top.monetary.sum():.1%} of real revenue; top 20% = "
      f"{top.head(int(len(top)*.2)).monetary.sum()/top.monetary.sum():.1%}")
winback = rfm[rfm.segment.isin(["At risk", "Can't lose them"])]
print(f"win-back list (At risk + Can't lose them): {len(winback):,} customers, "
      f"{winback.monetary.sum()/rfm.monetary.sum():.1%} of past revenue; avg past revenue {winback.monetary.mean():,.0f} (real NGN)")
sg.to_csv(OUT / "rfm_segment_summary.csv")

# ----------------------------------------------------------------- 4. payments and delivery
st = pd.crosstab(orders.payment_method, orders.order_status, normalize="index")
print("\nORDER OUTCOME BY PAYMENT METHOD\n", (st * 100).round(1).to_string())
lost = orders[orders.order_status.isin(["Cancelled (payment failed)", "Refused at delivery"])]
print(f"orders lost to payment failure/refusal: {len(lost):,} = {len(lost)/len(orders):.1%} of orders, "
      f"NGN {lost.gross_value.sum()/1e6:,.0f}M of order value ({lost.gross_value.sum()/orders.gross_value.sum():.1%})")
by_pm = lost.groupby("payment_method").gross_value.sum() / lost.gross_value.sum()
print("share of lost value by payment method\n", by_pm.round(3).to_string())
ct = orders[orders.order_status != "Cancelled (payment failed)"].groupby("city").agg(
    delivery_days=("delivery_days", "mean"), orders=("order_id", "size"))
ct["repeat_90d"] = cohort90.groupby("city").repeat_90d.mean()
ct["refused_pct"] = orders.groupby("city").order_status.apply(lambda s: (s == "Refused at delivery").mean())
print("\nCITIES\n", ct.round(3).sort_values("delivery_days").to_string())
st.to_csv(OUT / "outcome_by_payment.csv")
ct.to_csv(OUT / "city_summary.csv")

# ----------------------------------------------------------------- 5. Black Friday window vs normal
orders["period"] = np.where((orders.order_date.dt.month == 11) & (orders.order_date.dt.day >= 20), "Black Friday window (20-30 Nov)",
                    np.where(orders.order_date.dt.month == 12, "December", "Rest of year"))
days = {"Black Friday window (20-30 Nov)": 11 * 2, "December": 31 * 2, "Rest of year": 365 * 2 + 304 - 11 * 2 - 31 * 2 + 0}
bfy = orders[orders.year.isin([2024, 2025])]
rows = []
for p, gp in bfy.groupby("period"):
    n_days = {"Black Friday window (20-30 Nov)": 22, "December": 62, "Rest of year": 366 + 365 - 22 - 62}[p]
    dlv = gp[gp.order_status == "Delivered"]
    rows.append({"period": p, "orders_per_day": len(gp) / n_days, "avg_discount": gp.discount.mean(),
                 "fail_or_refused": gp.order_status.isin(["Cancelled (payment failed)", "Refused at delivery"]).mean(),
                 "delivery_days": gp.delivery_days.mean(),
                 "contribution_margin": gp.contribution.sum() / gp.realised_revenue.sum()})
bf = pd.DataFrame(rows).set_index("period")
bf["uplift_vs_normal"] = bf.orders_per_day / bf.loc["Rest of year", "orders_per_day"]
print("\nBLACK FRIDAY / DECEMBER vs REST OF YEAR (2024 and 2025)\n", bf.round(3).to_string())
bf.to_csv(OUT / "black_friday_summary.csv")

# ----------------------------------------------------------------- 6. budget reallocation (illustrative)
shift = 0.25 * ch.loc["Influencer", "spend"]
gain = shift * (ch.loc["Google Ads", "ltv_to_cac"] - ch.loc["Influencer", "ltv_to_cac"])
print(f"\nREALLOCATION: moving 25% of influencer spend (NGN {shift/1e6:,.1f}M) to Google Ads at each channel's average "
      f"LTV:CAC would change 12-month contribution by about NGN {gain/1e6:,.1f}M (before diminishing returns)")

# ----------------------------------------------------------------- 7. Black Friday economics by category + discount cap
orders["bf_window"] = (orders.order_date.dt.month == 11) & (orders.order_date.dt.day >= 20)
bfc = orders[orders.bf_window].groupby("category").agg(realised=("realised_revenue", "sum"), contribution=("contribution", "sum"),
                                                      discount=("discount", "mean"))
bfc["bf_margin"] = bfc.contribution / bfc.realised
normal = orders[~orders.bf_window & (orders.order_date.dt.month != 12)].groupby("category").agg(
    realised=("realised_revenue", "sum"), contribution=("contribution", "sum"))
bfc["normal_margin"] = normal.contribution / normal.realised
print("\nCONTRIBUTION MARGIN BY CATEGORY: Black Friday window vs normal\n", bfc[["discount", "bf_margin", "normal_margin"]].round(3).to_string())
bfc.to_csv(OUT / "black_friday_by_category.csv")
b25 = orders[orders.bf_window & (orders.year == 2025)]
list_sales = b25.units * b25.unit_price
capped = list_sales * (1 - b25.discount.clip(upper=0.15))
new_c = np.where(b25.order_status == "Delivered", capped - b25.cogs - b25.delivery_cost, b25.contribution)
print(f"BF 2025 window: contribution NGN {b25.contribution.sum()/1e6:,.1f}M at {b25.discount.mean():.0%} average discount; "
      f"with discounts capped at 15% (volume held) NGN {new_c.sum()/1e6:,.1f}M")

# ----------------------------------------------------------------- figures
# 1 nominal vs real
fig, ax = plt.subplots(figsize=(7.5, 4.2))
x = np.arange(3); w = .38
ax.bar(x - w / 2, g.nominal / 1e6, w, color=NAVY, label="Revenue in naira (as reported)")
ax.bar(x + w / 2, g.real / 1e6, w, color=TEAL, label="Revenue in constant 2024 naira (real)")
ax.set_xticks(x); ax.set_xticklabels([f"Jan-Oct {y}" for y in g.index])
ax.set_ylabel("NGN millions"); ax.legend(frameon=False, fontsize=8)
ax.set_title("Naira revenue grows faster than real demand (inflation inflates it)")
fig.tight_layout(); fig.savefig(FIG / "01_nominal_vs_real.png"); plt.close(fig)

# 2 channel quality
cs = ch.sort_values("ltv_to_cac")
fig, ax = plt.subplots(figsize=(7.5, 4.2))
ax.barh(cs.index, cs.ltv_to_cac, color=[RED if v == cs.ltv_to_cac.min() else NAVY for v in cs.ltv_to_cac])
for y, (cac, v) in enumerate(zip(cs.cac, cs.ltv_to_cac)):
    ax.text(v + .1, y, f"{v:.1f}x  (CAC NGN {cac:,.0f})", va="center", fontsize=8.5)
ax.axvline(3, color=GREY, ls="--", lw=1)
ax.set_xlim(0, cs.ltv_to_cac.max() * 1.35)
ax.set_xlabel("12-month contribution per customer / cost to acquire")
ax.set_title("Which channels pay back? (dashed line = 3x rule of thumb)")
fig.tight_layout(); fig.savefig(FIG / "02_channel_ltv_to_cac.png"); plt.close(fig)

# 3 repeat rate by channel, and TikTok's growing share of new customers
fig, axs = plt.subplots(1, 2, figsize=(10, 4.2), gridspec_kw={"width_ratios": [1, 1.1]})
rc = ch.sort_values("repeat_rate_90d")
axs[0].barh(rc.index, rc.repeat_rate_90d * 100, color=[RED if n == "TikTok Ads" else NAVY for n in rc.index])
for y, v in enumerate(rc.repeat_rate_90d * 100):
    axs[0].text(v + .5, y, f"{v:.0f}%", va="center", fontsize=9)
axs[0].set_xlim(0, 45)
axs[0].set_xlabel("% of customers who reorder within 90 days")
axs[0].set_title("TikTok customers rarely come back", fontsize=11)
axs[1].bar(qr.index, qr.tiktok * 100, color=RED, alpha=.8)
axs[1].set_ylabel("TikTok share of new customers (%)")
axs[1].set_title("Its share of new customers keeps rising", fontsize=11)
plt.setp(axs[1].get_xticklabels(), rotation=45, ha="right", fontsize=8)
fig.tight_layout(); fig.savefig(FIG / "03_repeat_by_channel_tiktok_share.png"); plt.close(fig)

# 4 RFM
order = ["Champions", "Loyal", "Can't lose them", "At risk", "Potential loyalists", "Promising", "New customers", "Slipping away", "Hibernating"]
s2 = sg.reindex([o for o in order if o in sg.index])
fig, ax = plt.subplots(figsize=(8.5, 4.4))
x = np.arange(len(s2)); w = .38
ax.bar(x - w / 2, s2.share_customers * 100, w, color=GREY, label="% of customers")
ax.bar(x + w / 2, s2.share_revenue * 100, w, color=NAVY, label="% of revenue")
ax.set_xticks(x); ax.set_xticklabels(s2.index, rotation=30, ha="right", fontsize=8)
ax.set_ylabel("%"); ax.legend(frameon=False)
ax.set_title("A few segments carry most of the revenue")
fig.tight_layout(); fig.savefig(FIG / "04_rfm_segments.png"); plt.close(fig)

# 5 payment outcomes
pm = st.reindex(["Card", "Bank transfer", "USSD", "Pay on delivery"])
fig, ax = plt.subplots(figsize=(7.5, 4.2))
bad = pm["Cancelled (payment failed)"] + pm["Refused at delivery"]
ax.bar(pm.index, bad * 100, color=[RED if v == bad.max() else NAVY for v in bad])
for i, v in enumerate(bad):
    ax.text(i, v * 100 + .3, f"{v*100:.0f}%", ha="center", fontsize=9)
ax.set_ylabel("% of orders failed or refused")
ax.set_title("Where orders are lost: failed payments and refusals at the door")
fig.tight_layout(); fig.savefig(FIG / "05_orders_lost_by_payment.png"); plt.close(fig)

# 6 black friday
fig, axs = plt.subplots(1, 3, figsize=(10, 3.8))
lab = ["BF window", "December", "Rest of year"]
ordr = ["Black Friday window (20-30 Nov)", "December", "Rest of year"]
for ax, col, title, fmt, scale in ((axs[0], "orders_per_day", "Orders per day", "{:,.0f}", 1),
                                   (axs[1], "fail_or_refused", "Orders failed or refused (%)", "{:.0f}", 100),
                                   (axs[2], "delivery_days", "Average delivery days", "{:.1f}", 1)):
    v = bf.loc[ordr, col] * scale
    ax.bar(lab, v, color=[RED, AMBER, NAVY])
    for i, val in enumerate(v):
        ax.text(i, val * 1.01, fmt.format(val), ha="center", fontsize=9)
    ax.set_title(title, fontsize=10)
    ax.tick_params(axis="x", labelsize=8)
fig.suptitle("Black Friday strains payments and delivery (2024 and 2025 average)", fontweight="bold", fontsize=11)
fig.tight_layout(); fig.savefig(FIG / "06_black_friday_strain.png"); plt.close(fig)

# 7 cities
fig, ax = plt.subplots(figsize=(7.5, 4.4))
ax.scatter(ct.delivery_days, ct.repeat_90d * 100, s=ct.orders / 25, color=NAVY, alpha=.75)
for name, r in ct.iterrows():
    ax.annotate(name, (r.delivery_days, r.repeat_90d * 100), xytext=(6, 4), textcoords="offset points", fontsize=8)
ax.set_xlabel("Average delivery days"); ax.set_ylabel("% reordering within 90 days")
ax.set_title("Slower delivery cities keep fewer customers (bubble = orders)")
fig.tight_layout(); fig.savefig(FIG / "07_city_delivery_vs_repeat.png"); plt.close(fig)
print("\nfigures:", sorted(p.name for p in FIG.glob("*.png")))
