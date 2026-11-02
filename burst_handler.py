import json
import time
import uuid

_ENV = uuid.uuid4().hex[:8]   # created once per environment, so it identifies the environment


def lambda_handler(event, context):
    time.sleep(float(event.get("sleep_s", 0)))   # makes the request last long enough to overlap
    return {"env": _ENV}