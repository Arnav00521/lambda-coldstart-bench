# Lambda cold-start benchmark

Track D. Arnav Chhabra , ID-2023A7PS0567P, Random Seed-67

What I did

Two identical Python 3.12 Lambda functions (128 MB, ap-south-1). baseline was called every 6 minutes, longer than an idle environment survives, so every call was cold. ping was kept warm by a scheduled ping every 3 minutes. A pilot first measured the idle lifetime (about 5 minutes). Result over 30 rounds: baseline 30 of 30 cold, median 496.8 ms; ping 0 of 30 cold, median 30.5 ms (server side latency). A burst test showed one warm environment does not cover overlapping requests. Provisioned concurrency was blocked by my new account's concurrency limit (10), so it was not tested. Limitations are in the report.

Files
handler.py: the Lambda function
pilot.py: finds how long an idle environment survives
main_bench.py: main run, baseline vs ping
analyze.py: summary table and chart
burst.py, burst_handler.py, burst_overlap.py: burst tests
results/: raw CSV output of every run, summary.csv, server_latency.png

Commands I ran

I created the Lambda functions, the IAM role and the EventBridge rule with the AWS CLI (profile bench, region ap-south-1), and ran the experiments from the command line (PowerShell). Key commands:

#create a function 
1)aws lambda create-function --function-name coldStartBench --runtime python3.12 --handler handler.lambda_handler --role arn:aws:iam::<ACCOUNT_ID>:role/coldStartBenchRole --zip-file fileb://function.zip --memory-size 128 --timeout 10 --region ap-south-1

# ping every 3 minutes,
2)aws events put-rule --name coldStartBench-ping-rule --schedule-expression "cron(1/3 * * * ? *)" --state ENABLED --region ap-south-1
aws events put-targets --rule coldStartBench-ping-rule --targets "Id=1,Arn=arn:aws:lambda:ap-south-1:<ACCOUNT_ID>:function:coldStartBench-ping" --region ap-south-1

3) pilot:
python pilot.py --region ap-south-1
python pilot.py --region ap-south-1 --gaps 6 7 8 9 --repeats 4 --out results\pilot_refine.csv

# main run (30 rounds, one call to each function every 6 minutes) and analysis
python main_bench.py --region ap-south-1 --seed 67
python analyze.py results\main_raw.csv

# burst test (1 second handler so that requests overlap)
python burst_overlap.py --region ap-south-1

Where I got stuck
