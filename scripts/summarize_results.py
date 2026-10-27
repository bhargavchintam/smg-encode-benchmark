"""Build the results section of README.md from the committed files in results/.

Every number in the generated tables is copied, as written, from a results
file; nothing is measured or recomputed here. The summary lines only pick the
smallest and largest speed-up that the files already print.

Run from the repository root:
  python3 scripts/summarize_results.py           # print the section
  python3 scripts/summarize_results.py --write   # replace it in README.md
  python3 scripts/summarize_results.py --check   # fail if README.md is out of date
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
START, END = "<!-- results:start -->", "<!-- results:end -->"
# (label used in the tables, file in results/)
MACHINES = [
    ("Apple M4", "2026-09-27-mac-m4.md"),
    ("Linux x86_64", "2026-09-28-gha-linux-x86_64.md"),
    ("Linux arm64", "2026-09-28-gha-linux-arm64.md"),
]
# (section name in the results files, label used in the tables)
MODELS = [("qwen3", "Qwen3-4B"), ("deepseek-v3.2", "DeepSeek-V3.2")]

PARITY = "Token-id parity"
FRESH = "Encode latency on fresh prompts"
TURNS = "Growing chats"
THROUGHPUT = "Throughput"
LOAD = "Load time and memory"

FRESH_COLUMNS = ["SMG as shipped", "SMG, all O2", "HF encode_fast", "fastokens", "fastokens, 1 thread"]
OPT_COLUMNS = ["SMG as shipped", "SMG, tokenizers at O2", "SMG, tokenizers+onig at O2", "SMG, HF hot deps at O2", "SMG, all O2"]
TURN_COLUMNS = ["SMG as shipped", "SMG + L0/L1 caches", "fastokens", "fastokens + L0/L1 caches"]
SPEEDUP = re.compile(r"\(([0-9.]+)×\)")


def parse_report(text):
    """Setup lines and, per model, every table as (header, rows) by section title."""
    setup, models = {}, {}
    model = section = None
    for line in text.splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            model = None if name == "Setup" else name
            if model is not None:
                models[model] = {}
            section = None
        elif line.startswith("### ") and model is not None:
            section = line[4:].strip()
            models[model][section] = []
        elif line.startswith("- **") and model is None:
            match = re.match(r"- \*\*(.+?)\*\*: (.*)", line)
            if match:
                setup[match.group(1)] = match.group(2)
        elif line.startswith("|") and model is not None and section is not None:
            models[model][section].append([c.strip() for c in line.strip().strip("|").split("|")])
    for sections in models.values():
        for title, lines in sections.items():
            sections[title] = (lines[0], lines[2:]) if lines else ([], [])
    return {"setup": setup, "models": models}


def load_reports(results_dir):
    return {label: parse_report((Path(results_dir) / name).read_text(encoding="utf-8")) for label, name in MACHINES}


def table(report, model, prefix):
    """The table whose section title starts with `prefix`, as a list of dicts."""
    for title, (header, rows) in report["models"][model].items():
        if title.startswith(prefix):
            return [dict(zip(header, row)) for row in rows]
    raise KeyError(f"{model}: no section starting with {prefix!r}")


def markdown(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    return "\n".join(lines + ["| " + " | ".join(row) + " |" for row in rows])


def speedups(reports, prefix, column, models=None):
    """The speed-ups printed in one column, over every machine, model and bucket."""
    found = []
    for report in reports.values():
        for model, _ in MODELS:
            if models and model not in models:
                continue
            for row in table(report, model, prefix):
                match = SPEEDUP.search(row.get(column, ""))
                if match:
                    found.append(match.group(1))
    if not found:
        raise ValueError(f"no speed-ups in column {column!r}")
    return min(found, key=float), max(found, key=float)


def parity_summary(reports):
    rows = []
    for label, report in reports.items():
        checked = mismatched = 0
        for model, _ in MODELS:
            for row in table(report, model, PARITY):
                checked += 1
                cells = [row["chat (add_special_tokens=false)"], row["embeddings (true)"]]
                if any(c != "—" and not re.fullmatch(r"0/\d+", c) for c in cells):
                    mismatched += 1
        rows.append([label, str(checked), str(mismatched)])
    return markdown(["machine", "parity rows (both models)", "rows with any mismatch"], rows)


def setup_table(reports):
    rows = []
    for (label, name), report in zip(MACHINES, reports.values()):
        s = report["setup"]
        rows.append([label, f"[{name}](results/{name})", s["machine"], s["os"], s["power"], s["rustc"], s["rounds"]])
    return markdown(["machine", "file", "CPU", "OS", "power", "rustc", "timing legs"], rows)


def fresh_table(reports, model):
    rows = []
    for label, report in reports.items():
        for row in table(report, model, FRESH):
            rows.append([label, row["bucket"], row["tokens (median)"]] + [row[c] for c in FRESH_COLUMNS])
    return markdown(["machine", "bucket", "tokens (median)"] + FRESH_COLUMNS, rows)


def opt_table(reports, bucket="50k"):
    rows = []
    for label, report in reports.items():
        for model, name in MODELS:
            row = next(r for r in table(report, model, FRESH) if r["bucket"] == bucket)
            rows.append([label, name] + [row[c] for c in OPT_COLUMNS])
    return markdown(["machine", "model"] + OPT_COLUMNS, rows)


def turns_table(reports):
    rows = []
    for label, report in reports.items():
        for model, name in MODELS:
            for row in table(report, model, TURNS):
                rows.append([label, name, row["bucket"], row["tokens (median)"]] + [row[c] for c in TURN_COLUMNS])
    return markdown(["machine", "model", "bucket", "tokens (median)"] + TURN_COLUMNS, rows)


def throughput_table(reports):
    rows = []
    for label, report in reports.items():
        for model, name in MODELS:
            cells = {(r["variant"], int(r["workers"])): r["M tokens/s"] for r in table(report, model, THROUGHPUT) if r["build"] == "z"}
            most = max(workers for _, workers in cells)
            rows.append([label, name, str(most), cells[("smg", 1)], cells[("fastokens", 1)], cells[("smg", most)], cells[("fastokens", most)]])
    headers = ["machine", "model", "all workers", "SMG, 1 worker", "fastokens, 1 worker", "SMG, all workers", "fastokens, all workers"]
    return markdown(headers, rows)


def load_table(reports):
    rows = []
    for label, report in reports.items():
        for model, name in MODELS:
            by_backend = {r["backend"]: r for r in table(report, model, LOAD)}
            smg, fast = by_backend["smg"], by_backend["fastokens"]
            rows.append(
                [label, name, smg["load ms (median)"], fast["load ms (median)"], smg["after a full-concurrency pass"], fast["after a full-concurrency pass"]]
            )
    headers = ["machine", "model", "SMG load ms", "fastokens load ms", "SMG MB after a full pass", "fastokens MB after a full pass"]
    return markdown(headers, rows)


def span(low, high):
    return f"{low}×" if low == high else f"{low}× to {high}×"


def render(reports):
    fast_lo, fast_hi = speedups(reports, FRESH, "fastokens")
    one_lo, one_hi = speedups(reports, FRESH, "fastokens, 1 thread")
    o2_lo, o2_hi = speedups(reports, FRESH, "SMG, all O2")
    tok_lo, tok_hi = speedups(reports, FRESH, "SMG, tokenizers at O2")
    hf_lo, hf_hi = speedups(reports, FRESH, "HF encode_fast")
    ds_lo, ds_hi = speedups(reports, TURNS, "SMG + L0/L1 caches", models={"deepseek-v3.2"})
    qw_lo, qw_hi = speedups(reports, TURNS, "SMG + L0/L1 caches", models={"qwen3"})
    parts = [
        START,
        "<!-- Made by scripts/summarize_results.py from the files in results/. Do not edit by hand. -->",
        "",
        "In short (the smallest and largest speed-up printed in the results files, over both models, all prompt sizes and all three machines):",
        "",
        f"- **fastokens** encodes fresh prompts {span(fast_lo, fast_hi)} faster than SMG as shipped, with the same token ids ({span(one_lo, one_hi)} when it may use only one thread).",
        f"- **SMG's own path at opt-level 2** (`o2`) is {span(o2_lo, o2_hi)} faster than the shipped `opt-level = \"z\"` build. Raising only the `tokenizers` crate to opt-level 2 (`tok`) already gives {span(tok_lo, tok_hi)}.",
        f"- **HF `encode_fast`** (no offsets) gives {span(hf_lo, hf_hi)}, so leaving out offsets saves little.",
        f"- **Multi-turn chats:** turning on SMG's L0/L1 caches gives {span(ds_lo, ds_hi)} for DeepSeek-V3.2 (slower than no cache) and {span(qw_lo, qw_hi)} for Qwen3.",
        "",
        "### Setup of each run",
        "",
        setup_table(reports),
        "",
        "### Token-id parity",
        "",
        "Each row compares one candidate with SMG on 119 inputs (both `add_special_tokens` settings), or on 72 growing-chat turns through the caches. The row counts cover every build and fastokens thread count in the file.",
        "",
        parity_summary(reports),
        "",
    ]
    for model, name in MODELS:
        parts += [
            f"### Fresh prompts, {name}: median ms per prompt (speed-up over SMG as shipped), caches off",
            "",
            fresh_table(reports, model),
            "",
        ]
    parts += [
        "### Which crates the opt-level gain comes from (50k bucket, median ms per prompt)",
        "",
        opt_table(reports),
        "",
        "### Growing chats: median ms per turn (every turn re-sends the whole history)",
        "",
        turns_table(reports),
        "",
        "### Throughput, `z` build: million tokens per second (one pass over fresh prompts)",
        "",
        throughput_table(reports),
        "",
        "### Load time and memory (MB above an empty process)",
        "",
        load_table(reports),
        END,
    ]
    return "\n".join(parts)


def replace_section(readme_text, section):
    start, end = readme_text.index(START), readme_text.index(END) + len(END)
    return readme_text[:start] + section + readme_text[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="replace the section in README.md")
    group.add_argument("--check", action="store_true", help="exit 1 if README.md differs from the results files")
    parser.add_argument("--results", default=str(ROOT / "results"))
    args = parser.parse_args()
    section = render(load_reports(args.results))
    if not (args.write or args.check):
        print(section)
        return
    current = README.read_text(encoding="utf-8")
    updated = replace_section(current, section)
    if args.check:
        if updated != current:
            sys.exit("README.md results section is out of date: run python3 scripts/summarize_results.py --write")
        print("README.md results section matches results/")
        return
    README.write_text(updated, encoding="utf-8")
    print(f"updated {README}")


if __name__ == "__main__":
    main()
