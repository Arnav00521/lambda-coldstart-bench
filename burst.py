import argparse, base64, csv, os, re, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import boto3
from botocore.config import Config

FIELDS = ["utc_time", "round", "slot", "cold", "init_ms", "duration_ms",
          "client_ms", "request_id", "error"]

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

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--region", required=True)
    p.add_argument("--function", default="coldStartBench-ping")
    p.add_argument("--concurrency", type=int, default=5,
                   help="keep below your account limit (10) so calls are not throttled")
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--gap-min", type=float, default=15,
                   help="minutes between bursts, so extra environments expire")
    p.add_argument("--out", default="results/burst_raw.csv")
    args = p.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    new = not os.path.exists(args.out)
    lam = boto3.client("lambda", region_name=args.region,
                       config=Config(retries={"max_attempts": 10, "mode": "standard"}))
    lock = threading.Lock()

    with open(args.out, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        for k in range(args.rounds):
            if k > 0:
                print(f"waiting {args.gap_min} min so extra environments expire...", flush=True)
                time.sleep(args.gap_min * 60)
            gate = threading.Barrier(args.concurrency)   # release all calls together

            def one(slot):
                err, r = "", {"cold": "", "init_ms": "", "duration_ms": "",
                              "client_ms": "", "request_id": ""}
                gate.wait()
                try:
                    r = invoke(lam, args.function)
                except Exception as e:
                    err = type(e).__name__
                row = {"utc_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "round": k, "slot": slot, "error": err, **r}
                with lock:
                    w.writerow(row); f.flush()
                return r["cold"], err

            with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
                res = list(ex.map(one, range(args.concurrency)))
            cold = sum(1 for c, e in res if c is True)
            errs = sum(1 for c, e in res if e)
            print(f"round {k}: {cold} of {args.concurrency} requests were cold starts"
                  + (f" ({errs} errors)" if errs else ""), flush=True)

if __name__ == "__main__":
    main()