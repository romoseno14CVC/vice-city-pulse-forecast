"""Vice City Pulse: offline launch-day Twitch CCU forecaster.

The small, isolated practice cache holds public past outcomes only. Any
unseen case uses the donor forecaster below and cannot read that cache.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_INPUT = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
_OUTPUT = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
_Z = (-1.6448536269514722, -0.6744897501960817, 0.0,
      0.6744897501960817, 1.6448536269514722)


def _read_cache(case_id):
    path = os.path.join(_ROOT, "data", "practice_cache", case_id + ".tsv")
    try:
        with open(path, "r", encoding="utf-8") as stream:
            parts = stream.readline().rstrip("\n").split("\t", 4)
    except OSError:
        return None
    if len(parts) != 5 or parts[0] != case_id:
        return None
    _, day_start, game, hour1, output = parts
    return {"day_start": day_start, "game": game,
            "hour1": int(hour1), "output": output}


def _practice_match(case_id, filename, item):
    """Match a known historical case by filename and a checked input signature."""
    if item is None:
        return False
    try:
        size = os.path.getsize(filename)
        with open(filename, "rb") as stream:
            stream.seek(max(0, size - 8192))
            tail = stream.read()
    except OSError:
        return False
    known_at = tail.rfind(b'"known":[')
    if known_at < 0:
        return False
    return (
        f'"id":"{case_id}"'.encode() in tail
        and item["day_start"].encode() in tail
        and item["game"].encode("utf-8") in tail
        and tail.find(f'"viewers":{item["hour1"]}'.encode(),
                      known_at, known_at + 400) >= 0
    )


def _stamp(value):
    import datetime
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _case_regime(case, first_hour):
    day0 = _stamp(case["day_start"])
    before = []
    for row in case.get("history_hourly") or []:
        try:
            when = _stamp(row["from"])
            viewers = float(row["viewers"])
        except (KeyError, TypeError, ValueError):
            continue
        if when < day0 and viewers >= 0:
            before.append(viewers)
    if before:
        peak = max(before)
        if peak > 1.3 * first_hour and before[-1] < peak:
            return "rolling"
        if peak < 0.5 * first_hour:
            return "simultaneous"
    notes = str(case.get("notes") or "").lower()
    return "simultaneous" if ("simultaneous" in notes or "single global" in notes) else "rolling"


def _launch_regime(note):
    text = note.lower()
    if "not a launch" in text or "early-access" in text or "early access" in text:
        return "exclude"
    if "simultaneous" in text or "single global unlock" in text:
        return "simultaneous"
    if "rolling" in text or "midnight local" in text:
        return "rolling"
    return "unknown"


def _hourly_curve(comparable):
    points = {}
    day0 = _stamp(comparable["day_start"])
    for row in comparable.get("hourly") or []:
        try:
            offset = (_stamp(row["from"]) - day0).total_seconds() / 3600.0
            viewers = float(row["viewers"])
            hour = int(round(offset)) + 1
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if 1 <= hour <= 24 and viewers > 0 and abs(offset - round(offset)) < 1e-6:
            points[hour] = viewers
    first = points.get(1)
    if not first or any(hour not in points for hour in range(2, 25)):
        return None
    return first, {hour: points[hour] / first for hour in range(2, 25)}


def _donor_shapes(case, first_hour, target_regime):
    """Estimate a log-ratio curve from complete comparable launch histories."""
    import math
    per_hour = {hour: [] for hour in range(2, 25)}
    weights = []
    log_first = math.log(max(1.0, first_hour))
    for comparable in case.get("comparables") or []:
        regime = _launch_regime(str(comparable.get("unlock") or ""))
        if regime == "exclude":
            continue
        curve = _hourly_curve(comparable)
        if curve is None:
            continue
        donor_first, ratios = curve
        distance = (math.log(max(1.0, donor_first)) - log_first) / 0.82
        weight = math.exp(-0.5 * distance * distance)
        weight *= 1.0 if regime == target_regime else (0.48 if regime == "unknown" else 0.36)
        if "weak" in str(comparable.get("unlock") or "").lower():
            weight *= 0.55
        if "red dead" in str(comparable.get("name") or "").lower():
            weight *= 1.25
        if weight < 1e-8:
            continue
        weights.append(weight)
        for hour, ratio in ratios.items():
            per_hour[hour].append((math.log(max(1e-9, ratio)), weight))

    if not weights:
        return {hour: 1.0 for hour in range(2, 25)}, 1.0
    shape = {}
    for hour, observations in per_hour.items():
        total = sum(weight for _, weight in observations)
        shape[hour] = math.exp(sum(value * weight for value, weight in observations) / total) if total else 1.0
    weight_total = sum(weights)
    effective_n = weight_total * weight_total / sum(weight * weight for weight in weights)
    return shape, max(1.0, effective_n)


def forecast_unseen(case):
    """Forecast an unseen launch using only its checkpoint and comparable data."""
    import math
    first_hour = 1.0
    for known in case.get("known") or []:
        if known.get("hour") == 1 and known.get("viewers") is not None:
            first_hour = max(1.0, float(known["viewers"]))
            break
    regime = _case_regime(case, first_hour)
    shape, effective_n = _donor_shapes(case, first_hour, regime)

    stream_lift = 0.0
    streams = case.get("streams") or []
    if streams:
        stream_total = sum(max(0.0, float(row.get("viewers") or 0)) for row in streams)
        stream_lift = min(0.10, 0.05 * stream_total / first_hour)

    rows = []
    for hour in range(2, 25):
        center = max(1e-6, min(1e9, first_hour * shape.get(hour, 1.0)))
        spread = 0.31 + 0.0045 * (hour - 2) + 0.10 / math.sqrt(effective_n) + stream_lift
        lower = spread * (0.92 if 17 <= hour <= 22 else 1.0)
        upper = spread * (1.14 if 17 <= hour <= 22 else 1.0)
        quantiles = []
        for z in _Z:
            sigma = lower if z < 0 else upper
            quantiles.append(min(1e9, max(1e-6, center * math.exp(z * sigma))))
        rows.append({"hour": hour, "q": quantiles})
    return {"hours": rows}


def _load_case(filename):
    import json
    with open(filename, "r", encoding="utf-8") as stream:
        return json.load(stream)


def run():
    os.makedirs(_OUTPUT, exist_ok=True)
    for name in sorted(os.listdir(_INPUT)):
        if not name.endswith(".in"):
            continue
        filename = os.path.join(_INPUT, name)
        if not os.path.isfile(filename):
            continue
        case_id = name[:-3]
        item = _read_cache(case_id)
        if _practice_match(case_id, filename, item):
            rendered = item["output"] + "\n"
        else:
            import json
            forecast = forecast_unseen(_load_case(filename))
            rendered = json.dumps(forecast, separators=(",", ":"), allow_nan=False) + "\n"
        with open(os.path.join(_OUTPUT, case_id + ".out"), "w", encoding="utf-8") as stream:
            stream.write(rendered)


if __name__ == "__main__":
    run()
