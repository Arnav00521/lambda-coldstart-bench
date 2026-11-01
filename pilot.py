import argparse, base64, csv, os, re, threading, time
from datetime import datetime, timezone
import boto3

FIELDS = ["utc_time", "function", "gap_min", "attempt", "cold",
          "init_ms", "duration_ms", "client_ms", "request_id"]

def invoke(lam, fn):
    t0 = time.perf_counter()
    resp = lam.invoke(FunctionName=fn, LogType="Tail", Payload=b"{}")
    resp["Payload"].read()
    client_ms = (time.perf_counter() - t0) * 1000
    log = base64.b64decode(resp["LogResult"]).decode()
    m = re.search(r"REPORT RequestId: (\S+)\s+Duration: ([\d.]+) ms", log)
    i = re.search(r"Init Duration: ([\d.]+) ms", log)
    return {"request_id": m.group(1), "duration_ms": float(m.group(2)),
            "init_ms": float(i.group(1)) if i else "",
            "cold": i is not None, "client_ms": round(client_ms, 1)}

def worker(gap, args, lam, writer, f, lock):
    fn = f"coldStartBench-gap{gap}"
    for attempt in range(args.repeats + 1):      # attempt 0 = warm-up call
        if attempt > 0:
            time.sleep(gap * args.unit)          # the idle gap
        r = invoke(lam, fn)
        row = {"utc_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "function": fn, "gap_min": gap, "attempt": attempt, **r}
        with lock:
            writer.writerow(row)
            f.flush()
        print(f"{fn} attempt {attempt}: {'COLD' if r['cold'] else 'warm'}", flush=True)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--region", required=True)
    p.add_argument("--gaps", type=int, nargs="+", default=[5, 10, 20, 30, 45])
    p.add_argument("--repeats", type=int, default=4)
    p.add_argument("--unit", type=float, default=60, help="seconds per 'minute' (use 1 for a dry run)")
    p.add_argument("--out", default="results/pilot_raw.csv")
    args = p.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    new = not os.path.exists(args.out)
    lam = boto3.client("lambda", region_name=args.region)
    lock = threading.Lock()
    with open(args.out, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        threads = [threading.Thread(target=worker, args=(g, args, lam, writer, f, lock))
                   for g in args.gaps]
        for t in threads: t.start()
        for t in threads: t.join()

if __name__ == "__main__":
    main()