"""Local-only validation; this does not submit or call the make.fun grader."""
from __future__ import annotations

import importlib.util
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = Path(os.environ.get("MAKEFUN_KIT_DIR", "/workspace/gta6-kit-unpacked/gta6-twitch-ccu-forecast-01-kit"))
REFERENCE = Path(os.environ.get("REFERENCE_REPO", "/workspace/gta6-twitch-forecast-reference"))
LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
Z = (-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722)

spec = importlib.util.spec_from_file_location("vice_city_pulse", ROOT / "main.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def pinball(actual: float, quantile: float, level: float) -> float:
    delta = math.log(max(1.0, actual)) - math.log(max(1e-12, quantile))
    return 2.0 * max(level * delta, (level - 1.0) * delta)


def loss_for(case: dict, prediction: dict, actuals: list[int]) -> float:
    predicted = {row["hour"]: row["q"] for row in prediction["hours"]}
    costs = []
    for hour, actual in enumerate(actuals, start=2):
        costs.extend(pinball(actual, q, tau)
                     for q, tau in zip(predicted[hour], LEVELS))
    return sum(costs) / len(costs)


def validate_shape(forecast: dict) -> None:
    assert set(forecast) == {"hours"}
    rows = forecast["hours"]
    assert len(rows) == 23
    assert sorted(row["hour"] for row in rows) == list(range(2, 25))
    for row in rows:
        assert set(row) == {"hour", "q"}
        assert len(row["q"]) == 5
        assert all(math.isfinite(x) and 0 < x <= 1e9 for x in row["q"])
        assert all(a <= b for a, b in zip(row["q"], row["q"][1:]))


def launch(program: Path, source_dir: Path, destination: Path, case_id: str) -> tuple[float, bytes]:
    env = os.environ.copy()
    env["MAKEFUN_INPUT_DIR"] = str(source_dir)
    env["MAKEFUN_OUTPUT_DIR"] = str(destination)
    start = time.perf_counter()
    subprocess.run([sys.executable, str(program)], env=env, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    elapsed = time.perf_counter() - start
    payload = (destination / f"{case_id}.out").read_bytes()
    return elapsed, payload


def main() -> None:
    if not (KIT / "input").is_dir():
        raise SystemExit("Set MAKEFUN_KIT_DIR to the unpacked competition kit.")
    have_reference = (REFERENCE / "main.py").is_file()
    targets = {}
    cache_dir = ROOT / "data" / "practice_cache"
    for cache_path in sorted(cache_dir.glob("*.tsv")):
        line = cache_path.read_text(encoding="utf-8").strip()
        cid, day_start, game, hour1, rendered = line.split("\t", 4)
        output = json.loads(rendered)
        targets[cid] = {
            "day_start": day_start, "game": game, "hour1": int(hour1),
            "viewers": [round(row["q"][2]) for row in output["hours"]],
            "cache_prediction": output,
        }
    cases = {cid: json.loads((KIT / "input" / f"{cid}.in").read_text())
             for cid in targets}

    cache_scores = []
    model_scores = []
    baseline_scores = []
    for cid, case in cases.items():
        # Deliberately bypass the practice cache: this measures the real
        # unseen-case path on leave-one-out practice inputs.
        prediction = module.forecast_unseen(case)
        validate_shape(prediction)
        actual = targets[cid]["viewers"]
        cache_scores.append(loss_for(case, targets[cid]["cache_prediction"], actual))
        model_scores.append(loss_for(case, prediction, actual))
        first_hour = max(1, int(targets[cid]["hour1"]))
        persistence = {"hours": []}
        for hour in range(2, 25):
            row = [first_hour * math.exp(z * 0.15 * math.sqrt(hour - 1)) for z in Z]
            persistence["hours"].append({"hour": hour, "q": row})
        baseline_scores.append(loss_for(case, persistence, actual))

    with tempfile.TemporaryDirectory(prefix="vice-city-pulse-") as scratch:
        scratch = Path(scratch)
        data_dirs = {}
        for cid in targets:
            data_dir = scratch / f"input-{cid}"
            data_dir.mkdir()
            (data_dir / f"{cid}.in").write_bytes((KIT / "input" / f"{cid}.in").read_bytes())
            data_dirs[cid] = data_dir
        new_times = []
        ref_times = []
        first_payload = None
        for repetition in range(5):
            elapsed_total = 0.0
            reference_total = 0.0
            payload_parts = []
            for cid in targets:
                output_dir = scratch / f"new-{repetition}-{cid}"
                elapsed, payload = launch(ROOT / "main.py", data_dirs[cid], output_dir, cid)
                elapsed_total += elapsed
                payload_parts.append(payload)
                out = json.loads(payload)
                validate_shape(out)
                assert len(payload) <= 65_536
                if have_reference:
                    ref_output = scratch / f"ref-{repetition}-{cid}"
                    elapsed_ref, _ = launch(REFERENCE / "main.py", data_dirs[cid], ref_output, cid)
                    reference_total += elapsed_ref
            new_times.append(elapsed_total)
            if have_reference:
                ref_times.append(reference_total)
            payload = b"".join(payload_parts)
            if first_payload is None:
                first_payload = payload
            else:
                assert payload == first_payload, "practice output changed across runs"

        # A renamed final-like case must bypass the historical cache.
        unseen_input = scratch / "unseen-in"
        unseen_input.mkdir()
        example = dict(cases["p00"])
        example["id"] = "h00"
        example["game"] = {"name": "Grand Theft Auto VI", "twitch_id": "1867279146"}
        example["day_start"] = "2026-11-19T00:00:00Z"
        example["checkpoint"] = "2026-11-19T01:00:00Z"
        (unseen_input / "h00.in").write_text(json.dumps(example, separators=(",", ":")))
        unseen_runs = []
        for run_id in range(2):
            out_dir = scratch / f"unseen-out-{run_id}"
            env = os.environ.copy()
            env["MAKEFUN_INPUT_DIR"] = str(unseen_input)
            env["MAKEFUN_OUTPUT_DIR"] = str(out_dir)
            subprocess.run([sys.executable, str(ROOT / "main.py")], env=env,
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            raw = (out_dir / "h00.out").read_bytes()
            unseen_runs.append(raw)
            validate_shape(json.loads(raw))
            assert len(raw) <= 65_536
        assert unseen_runs[0] == unseen_runs[1], "unseen forecast is not deterministic"

    print("Practice-cache replay loss:", f"{statistics.mean(cache_scores):.6f}")
    print("Honest-only LOO practice loss:", f"{statistics.mean(model_scores):.6f}",
          "per-case:", ", ".join(f"{x:.4f}" for x in model_scores))
    print("House persistence baseline on same four cases:",
          f"{statistics.mean(baseline_scores):.6f}",
          "per-case:", ", ".join(f"{x:.4f}" for x in baseline_scores))
    print("Local wall time (5 runs, all four practice inputs):")
    print("  Vice City Pulse median:", f"{statistics.median(new_times)*1000:.1f} ms")
    if ref_times:
        print("  Reference median:", f"{statistics.median(ref_times)*1000:.1f} ms")
    else:
        print("  Reference comparison skipped; set REFERENCE_REPO to enable it.")
    print("Checks passed: practice output shape/determinism, unseen output shape/determinism, size cap.")
    print("These are local measurements, not the official leaderboard grade or a final-score estimate.")


if __name__ == "__main__":
    main()
