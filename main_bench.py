import argparse, base64, csv, os, random, re, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import boto3
from botocore.config import Config

# strategy name -> (function name, alias/qualifier)
STRATEGIES = {
    "baseline": ("coldStartBench-baseline", None),
    "ping":     ("coldStartBench-ping", None),
    "prov":     ("coldStartBench-prov", "live"),
}
FIELDS = ["utc_time", "round", "strategy", "scheduled_utc", "late_s", "cold",
          "init_ms", "duration_ms", "billed_ms", "client_ms", "request_id", "error"]

def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")

def invoke(lam, strategy):
    fn, qualifier = STRATEGIES[strategy]
    kwargs = dict(FunctionName=fn, LogType="Tail", Payload=b"{}")
    if qualifier:
        kwargs["Qualifier"] = qualifier
    t0 = time.perf_counter()
    resp = lam.invoke(**kwargs)
    resp["Payload"].read()
    client_ms = (time.perf_counter() - t0) * 1000
    log = base64.b64decode(resp["LogResult"]).decode()
    m = re.search(r"REPORT RequestId: (\S+)\s+Duration: ([\d.]+) ms\s+Billed Duration: ([\d.]+) ms", log)
    i = re.search(r"Init Duration: ([\d.]+) ms", log)
    return {"request_id": m.group(1), "duration_ms": float(m.group(2)),
            "billed_ms": float(m.group(3)),
            "init_ms": float(i.group(1)) if i else "",
            "cold": i is not None, "client_ms": round(client_ms, 1)}

def run_round(k, target, args, lam, writer, f, lock, rng):
    order = list(args.strategies)
    rng.shuffle(order)                       # seeded: order of calls within a round
    late = round(time.time() - target, 2)

    def one(s):
        err = ""
        try:
            r = invoke(lam, s)
        except Exception as e:               # a failed call is recorded, not fatal
            r = {"cold": "", "init_ms": "", "duration_ms": "", "billed_ms": "",
                 "client_ms": "", "request_id": ""}
            err = type(e).__name__
        row = {"utc_time": iso(time.time()), "round": k, "strategy": s,
               "scheduled_utc": iso(target), "late_s": late, "error": err, **r}
        with lock:
            writer.writerow(row)
            f.flush()
        print(f"round {k:2d} {s:8s} {'COLD' if r['cold'] is True else 'warm' if r['cold'] is False else 'ERROR ' + err}", flush=True)

    with ThreadPoolExecutor(max_workers=len(order)) as ex:
        list(ex.map(one, order))

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--region", required=True)
    p.add_argument("--seed", type=int, required=True, help="last two digits of ID number")
    p.add_argument("--strategies", nargs="+", default=["baseline", "ping"], choices=list(STRATEGIES))
    p.add_argument("--rounds", type=int, default=30)
    p.add_argument("--gap-sec", type=int, default=360)
    p.add_argument("--out", default="results/main_raw.csv")
    args = p.parse_args()

    rng = random.Random(args.seed)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    new = not os.path.exists(args.out)
    lam = boto3.client("lambda", region_name=args.region,
                       config=Config(retries={"max_attempts": 10, "mode": "standard"}))
    lock = threading.Lock()

    now = time.time()
    start = (now // args.gap_sec + 1) * args.gap_sec    # next multiple of the gap
    if start - now < 45:
        start += args.gap_sec
    print("first round at", iso(start), "UTC; rounds:", args.rounds, flush=True)

    with open(args.out, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        for k in range(args.rounds):
            target = start + k * args.gap_sec            # absolute schedule: no drift
            while time.time() < target:
                time.sleep(min(5, max(0.0, target - time.time())))
            run_round(k, target, args, lam, writer, f, lock, rng)

if __name__ == "__main__":
    main()