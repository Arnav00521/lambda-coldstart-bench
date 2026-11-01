import json
import time
import boto3

_s3 = boto3.client("s3")
_INIT_TS = time.time()

def lambda_handler(event, context):
    return {
        "statusCode": 200,
        "body": json.dumps({
            "env_age_s": round(time.time() - _INIT_TS, 3),
            "memory_mb": context.memory_limit_in_mb,
        }),
    }