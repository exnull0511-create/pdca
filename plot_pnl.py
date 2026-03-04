"""全5案比較グラフ: FINAL / BAL / LOOSE-A / LOOSE-B / LOOSE-C"""
import re, numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from pathlib import Path

import matplotlib.font_manager as fm
_avail = {f.name for f in fm.fontManager.ttflist}
_jp    = next((f for f in ["Meiryo","MS Gothic","Yu Gothic"] if f in _avail), "sans-serif")
plt.rcParams["font.family"]        = _jp
plt.rcParams["axes.unicode_minus"] = False

RE_INVEST = re.compile(r"💰 【投資】 ¥([\d,]+)")
RE_PAYOUT = re.compile(r"🎉 【的中】.*?払戻.*?¥([\d,]+)")

def parse_log(path):
    txt=Path(path).read_text(encoding="utf-8")
    ci=cr=0; recs=[]
    for b in re.split(r"={50,}", txt):
        im=RE_INVEST.search(b)
        if not im: continue
        ci+=int(im.group(1).replace(",",""))
        pm=RE_PAYOUT.search(b)
        if pm: cr+=int(pm.group(1).replace(",",""))
        recs.append((ci,cr))
    return recs

CASES = [
    ("FINAL\n39R/ROI675%",  "iteration_1_logs_S_MAXHIT_14_EV_FINAL.txt",    "#ffcc00"),
    ("BAL\n46R/ROI624%",    "iteration_1_logs_S_MAXHIT_14_EV_BAL.txt",      "#4af0a4"),
    ("LOOSE-A\n51R/ROI609%","iteration_1_logs_S_MAXHIT_14_EV_LOOSE_A.txt",  "#4a9eff"),
    ("LOOSE-B\n73R/ROI525%","iteration_1_logs_S_MAXHIT_14_EV_LOOSE_B.txt",  "#ff9944"),
    ("LOOSE-C\n80R/ROI506%","iteration_1_logs_S_MAXHIT_14_EV_LOOSE_C.txt",  "#cc88ff"),
]

DARK, PANEL = "#12121f", "#1a1a2e"
fig, axes = plt.subplots(2, 5, figsize=(22, 9),
                         gridspec_kw={"height_ratios":[2,1]})
fig.patch.set_facecolor(DARK)
fig.suptitle("ルックフィルター 段階比較（EV傾斜配分ベース）",
             fontsize=13, fontweight="bold", color="white", y=1.01)

print("=== 集計確認 ===")
for col, (label, logfile, color) in enumerate(CASES):
    ax_p = axes[0][col]; ax_d = axes[1][col]
    for ax in (ax_p, ax_d):
        ax.set_facecolor(PANEL)
        ax.tick_params(colors="white", labelsize=7)
        for sp in ax.spines.values(): sp.set_color("#555")
        ax.grid(axis="y", color="#333", linewidth=0.4)

    if not Path(logfile).exists():
        ax_p.text(0.5,0.5,"ログなし",ha="center",va="center",
                  color="gray",transform=ax_p.transAxes,fontsize=8)
        continue

    recs = parse_log(logfile)
    xs   = np.arange(1, len(recs)+1)
    inv  = np.array([r[0] for r in recs])
    ret  = np.array([r[1] for r in recs])
    pnl  = ret - inv
    peak = np.maximum.accumulate(pnl)
    dd   = pnl - peak
    final_roi = ret[-1]/inv[-1]*100 if inv[-1] else 0
    final_pnl = pnl[-1]
    max_dd    = dd.min()
    max_dd_x  = int(np.argmin(dd))+1
    neg_pct   = (pnl<0).sum()/len(pnl)*100

    sign = "+" if final_pnl>=0 else ""
    print(f"[{label.splitlines()[0]}] ROI:{final_roi:.1f}%  損益:{sign}¥{final_pnl:,}  "
          f"最大DD:¥{max_dd:,.0f}  マイナス:{(pnl<0).sum()}/{len(recs)}R")

    # ── PnL ──
    ax_p.plot(xs, pnl, color=color, linewidth=1.6, zorder=4)
    ax_p.axhline(0, color="white", linewidth=0.8, linestyle="--", alpha=0.4, zorder=3)
    ax_p.fill_between(xs, pnl, 0, where=(pnl>=0), color=color, alpha=0.20)
    ax_p.fill_between(xs, pnl, 0, where=(pnl<0),  color="#ff3333", alpha=0.50)
    ax_p.scatter([max_dd_x],[pnl[max_dd_x-1]],color="#ff4444",s=60,marker="v",zorder=5)
    ax_p.set_title(
        f"{label}\n損益:{sign}¥{int(final_pnl):,}\nマイナス:{neg_pct:.1f}%",
        fontsize=7.5, color=color, fontweight="bold", pad=4)
    ax_p.set_ylabel("累積純損益" if col==0 else "", color="white", fontsize=7)
    ax_p.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v,_: f"¥{int(v/1000):,}k"))

    # ── Drawdown ──
    ax_d.plot(xs, dd, color="#ff8888", linewidth=1.2)
    ax_d.fill_between(xs, dd, 0, color="#ff3333", alpha=0.30)
    ax_d.axhline(0, color="white", linewidth=0.6, linestyle="--", alpha=0.3)
    ax_d.set_title(f"最大DD:¥{int(max_dd):,}", fontsize=7, color="#ff8888", pad=3)
    ax_d.set_ylabel("ドローダウン" if col==0 else "", color="white", fontsize=7)
    ax_d.set_xlabel("ベットRC数", color="white", fontsize=7)
    ax_d.yaxis.set_major_formatter(
        mticker.FuncFormatter(lambda v,_: f"¥{int(v/1000):,}k"))

plt.tight_layout()
out = "pnl_loose_compare.png"
plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=DARK)
print(f"\n✅ 保存: {out}")
plt.close()
