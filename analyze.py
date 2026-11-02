"""Summarise a main_bench.py CSV: per-strategy cold-start rate and latency.

server_ms = init_ms (cold only) + duration_ms  -> latency as AWS measured it
client_ms = what the laptop timed, including network (secondary, noisy)
"""
import argparse, csv, math, os, statistics
from collections import defaultdict

def num(x):
    return float(x) if x not in ("", None) else None

def pct(values, q):                      # nearest-rank percentile
    s = sorted(values)
    return s[max(0, math.ceil(q * len(s)) - 1)]

def stats(values):
    if not values:
        return ("-", "-", "-")
    return (round(statistics.median(values), 1), round(pct(values, 0.95), 1), round(max(values), 1))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("file")
    p.add_argument("--skip-rounds", type=int, default=0, help="ignore the first N rounds")
    p.add_argument("--late-s", type=float, default=60, help="flag rounds started this late")
    p.add_argument("--out", default="results/summary.csv")
    p.add_argument("--chart", default="results/server_latency.png")
    args = p.parse_args()

    rows = list(csv.DictReader(open(args.file)))
    rows = [r for r in rows if int(r["round"]) >= args.skip_rounds]
    errors = defaultdict(int)
    good = defaultdict(list)
    for r in rows:
        if r["error"]:
            errors[r["strategy"]] += 1
        else:
            r["server_ms"] = num(r["duration_ms"]) + (num(r["init_ms"]) or 0)
            good[r["strategy"]].append(r)

    header = ["strategy", "n", "errors", "late", "cold_n", "cold_rate_%",
              "server_median", "server_p95", "server_max",
              "cold_server_median", "warm_server_median", "init_median",
              "client_median", "client_p95"]
    table = []
    for s, rs in good.items():
        cold = [r for r in rs if r["cold"] == "True"]
        warm = [r for r in rs if r["cold"] == "False"]
        server = [r["server_ms"] for r in rs]
        client = [num(r["client_ms"]) for r in rs]
        init = [num(r["init_ms"]) for r in cold]
        med, p95, mx = stats(server)
        cmed, cp95, _ = stats(client)
        table.append([s, len(rs), errors[s], sum(1 for r in rs if float(r["late_s"]) > args.late_s),
                      len(cold), round(100 * len(cold) / len(rs), 1), med, p95, mx,
                      stats([r["server_ms"] for r in cold])[0],
                      stats([r["server_ms"] for r in warm])[0],
                      stats(init)[0], cmed, cp95])

    widths = [max(len(str(x)) for x in col) for col in zip(header, *table)]
    for row in [header] + table:
        print("  ".join(str(x).ljust(w) for x, w in zip(row, widths)))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(table)
    print("\nsaved", args.out)
    print("note: with n=30, p95 is the 29th-smallest value, so it is close to the max")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed: skipping chart (pip install matplotlib)")
        return
    colors = {"baseline": "#2a78d6", "ping": "#eb6834", "prov": "#1baf7a"}
    ink, muted, grid = "#0b0b0b", "#52514e", "#e4e3df"
    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=150)
    fig.patch.set_facecolor("#fcfcfb"); ax.set_facecolor("#fcfcfb")
    for s, rs in good.items():
        xs = [int(r["round"]) for r in rs]; ys = [r["server_ms"] for r in rs]
        ax.plot(xs, ys, color=colors.get(s, "#6250d6"), lw=1.5, marker="o", ms=4,
                markeredgecolor="#fcfcfb", markeredgewidth=1, label=s)
    ax.set_yscale("log")
    ax.set_xlabel("round (one request to each function every 6 minutes)", color=muted)
    ax.set_ylabel("server-side latency, ms (log scale)", color=muted)
    ax.set_title("Server-side latency of each request (cold starts are the high points)", color=ink, loc="left", fontsize=11)
    ax.grid(axis="y", color=grid, lw=0.8); ax.set_axisbelow(True)
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"): ax.spines[sp].set_color(grid)
    ax.tick_params(colors=muted)
    leg = ax.legend(frameon=False, loc="center right")
    for t in leg.get_texts(): t.set_color(ink)
    fig.tight_layout()
    os.makedirs(os.path.dirname(args.chart) or ".", exist_ok=True)
    fig.savefig(args.chart); print("saved", args.chart)

if __name__ == "__main__":
    main()