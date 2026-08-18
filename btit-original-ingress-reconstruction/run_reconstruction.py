from __future__ import annotations
import datetime as dt
import hashlib
import json
import pathlib
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
PROTOCOL = json.loads((ROOT / "sealed_protocol.json").read_text())
RELAYS = PROTOCOL["anchor_ingress_rule"]["allowed_relays"]
N = int(PROTOCOL["bundle"]["request_count"])

rows = []
for i in range(N):
    base = RELAYS[i % len(RELAYS)]
    url = base + "?" + urllib.parse.urlencode({"btit_receipt": f"{time.time_ns()}-{i}"})
    requested_at = dt.datetime.now(dt.timezone.utc).isoformat()
    row = {
        "index": i + 1,
        "relay": base,
        "requested_at_utc": requested_at,
        "raw_round_received": None,
        "signature_sha256": None,
        "http_source_url": url,
        "success": False,
        "error": None,
    }
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "btit-ingress-reconstruction/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        row["received_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        row["raw_round_received"] = int(payload["round"])
        row["signature_sha256"] = hashlib.sha256(bytes.fromhex(payload["signature"])).hexdigest()
        row["success"] = True
    except Exception as exc:
        row["received_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        row["error"] = f"{type(exc).__name__}: {exc}"
    rows.append(row)

raw = {
    "schema": "btit.latent-path.ingress-reconstruction.raw-bundle.v1",
    "protocol_sha256": PROTOCOL["protocol_sha256"],
    "calendar_conversion_done": False,
    "fixed_offset_applied": False,
    "btit_output_used_to_choose_round": False,
    "receipts": rows,
}
raw_hash = hashlib.sha256(
    json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
raw["raw_bundle_sha256"] = raw_hash
(ROOT / "raw_round_receipts.json").write_text(json.dumps(raw, indent=2))

GENESIS_UNIX = 1595431050
PERIOD = 30
converted = []
for row in rows:
    out = dict(row)
    if row["success"]:
        r = int(row["raw_round_received"])
        round_unix = GENESIS_UNIX + (r - 1) * PERIOD
        round_dt = dt.datetime.fromtimestamp(round_unix, tz=dt.timezone.utc)
        received_dt = dt.datetime.fromisoformat(row["received_at_utc"])
        expected = int((received_dt.timestamp() - GENESIS_UNIX) // PERIOD) + 1
        out["round_datetime_utc"] = round_dt.isoformat()
        out["expected_round_from_receipt_time"] = expected
        out["round_minus_expected"] = r - expected
        out["age_seconds_at_receipt"] = int((received_dt - round_dt).total_seconds())
    converted.append(out)

result = {
    "schema": "btit.latent-path.ingress-reconstruction.result.v1",
    "protocol_sha256": PROTOCOL["protocol_sha256"],
    "raw_bundle_sha256": raw_hash,
    "receipts": converted,
}
result["result_sha256"] = hashlib.sha256(
    json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
(ROOT / "result.json").write_text(json.dumps(result, indent=2))

successes = [x for x in converted if x["success"]]
summary = {
    "successes": len(successes),
    "failures": len(converted) - len(successes),
    "unique_raw_rounds": sorted({x["raw_round_received"] for x in successes}),
    "min_round_minus_expected": min((x["round_minus_expected"] for x in successes), default=None),
    "max_round_minus_expected": max((x["round_minus_expected"] for x in successes), default=None),
    "max_age_seconds_at_receipt": max((x["age_seconds_at_receipt"] for x in successes), default=None),
    "result_sha256": result["result_sha256"],
}
print("BTIT_INGRESS_RECONSTRUCTION=" + json.dumps(summary, sort_keys=True))
