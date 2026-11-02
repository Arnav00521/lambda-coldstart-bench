import argparse, base64, csv, json, os, re, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import boto3
from botocore.config import Config

FIELDS = ["utc_time", "round", "slot", "env", "cold", "init_ms", "duration_ms",
          "client_ms", "request_id", "error"]

def invoke(lam, fn, sleep_s):
    t0 = time.perf_counter()
    resp = lam.invoke(FunctionName=fn, LogType="Tail",
                      Payload=json.dumps({"sleep_s": sleep_s}).encode())
    body = json.loads(resp["Payload"].read())
    client_ms = (time.perf_counter() - t0) * 1000
    log = base64.b64decode(resp["LogResult"]).decode()
    m = re.search(r"REPORT RequestId: (\S+)\s+Duration: ([\d.]+) ms", log)
    i = re.search(r"Init Duration: ([\d.]+) ms", log)
    return {"env": body.get("env", ""), "request_id": m.group(1),
            "duration_ms": float(m.group(2)),
            "init_ms": float(i.group(1)) if i else "",
            "cold": i is not None, "client_ms": round(client_ms, 1)}

def reset_to_one_warm(lam, fn, tag):
    # a config change throws away every environment; one call then creates exactly one
    lam.update_function_configuration(
        FunctionName=fn, Environment={"Variables": {"BENCH_NONCE": f"{tag}-{time.time_ns()}"}})
    lam.get_waiter("function_updated_v2").wait(FunctionName=fn)
    invoke(lam, fn, 0)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--region", required=True)
    p.add_argument("--function", default="coldStartBench-burst")
    p.add_argument("--concurrency", type=int, default=5, help="keep below the account limit (10)")
    p.add_argument("--rounds", type=int, default=5)
    p.add_argument("--sleep-s", type=float, default=1.0, help="how long each request runs")
    p.add_argument("--out", default="results/burst_overlap_raw.csv")
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
            reset_to_one_warm(lam, args.function, f"r{k}")
            gate = threading.Barrier(args.concurrency)

            def one(slot):
                err, r = "", {"env": "", "cold": "", "init_ms": "", "duration_ms": "",
                              "client_ms": "", "request_id": ""}
                gate.wait()
                try:
                    r = invoke(lam, args.function, args.sleep_s)
                except Exception as e:
                    err = type(e).__name__
                row = {"utc_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "round": k, "slot": slot, "error": err, **r}
                with lock:
                    w.writerow(row); f.flush()
                return r["env"], r["cold"], err

            with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
                res = list(ex.map(one, range(args.concurrency)))
            envs = {e for e, c, er in res if e}
            cold = sum(1 for e, c, er in res if c is True)
            errs = sum(1 for e, c, er in res if er)
            print(f"round {k}: {len(envs)} distinct environments, {cold} of "
                  f"{args.concurrency} cold" + (f", {errs} errors" if errs else ""), flush=True)

if __name__ == "__main__":
    main()