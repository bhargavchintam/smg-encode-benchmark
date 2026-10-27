# smg-encode-benchmark

[![CI](https://github.com/bhargavchintam/smg-encode-benchmark/actions/workflows/ci.yml/badge.svg)](https://github.com/bhargavchintam/smg-encode-benchmark/actions/workflows/ci.yml)

A benchmark of the tokenizer encode step in [SMG (Shepherd Model Gateway)](https://github.com/smg-project/smg), an LLM gateway written in Rust. It measures how fast SMG turns a rendered chat prompt into token ids, as shipped and with faster options, and it checks that every option returns exactly the same ids as SMG.

I wrote this in September 2026 in my fork of SMG and moved it here as a standalone repository. The results in [`results/`](results/) are the files committed in the fork. Every measured number in this README is copied from those files.

## What it measures, and why

A gateway encodes every prompt on the CPU before the model sees it. In a long chat, every user turn sends the whole history again, so the same work grows with the conversation. Agent prompts with tool schemas and files are often tens of thousands of tokens. So the encode step sits on the request path of every call.

At the time of these runs, SMG built its whole release binary with `opt-level = "z"` (optimise for size), and that included the tokenizer crates. The benchmark asks three questions:

1. How much faster is SMG's own encode path when the hot crates are built for speed instead of size?
2. Is a faster encoder ([fastokens](https://crates.io/crates/fastokens)) a drop-in, meaning the same token ids and not only a good speed?
3. Do SMG's L0/L1 tokenizer caches help when a chat grows turn by turn?

### Encoders compared

| variant | what it is |
|---|---|
| `smg` | `HuggingFaceTokenizer::encode` from SMG's `llm-tokenizer` crate, as shipped (full HF `encode`, offsets included) |
| `hf_encode` / `hf_encode_fast` | the raw HF `tokenizers` `encode` / `encode_fast` (SMG only reads the ids) |
| `fastokens` | [fastokens](https://crates.io/crates/fastokens) 0.3.2, built from `tokenizer.json` alone |
| `smg_cached` / `fastokens_cached` | the same encoders behind SMG's L0 + L1 caches (multi-turn runs) |

### Builds of the same code

| build | what it is |
|---|---|
| `z` | SMG's release profile as shipped (`opt-level = "z"`) |
| `tok` | `z`, plus opt-level 2 for `tokenizers` |
| `toksys` | `tok`, plus opt-level 2 for `onig` and `onig_sys` |
| `hotdeps` | `z`, plus opt-level 2 for every crate on HF's encode path |
| `o2` | everything at opt-level 2 (upper bound) |

### Models and prompts

- Tokenizers of `Qwen/Qwen3-4B-Instruct-2507` and `deepseek-ai/DeepSeek-V3.2`, at the revisions pinned in [`scripts/pins.json`](scripts/pins.json). Every download is checked against a sha256.
- Prompts are rendered with SMG's own chat templates, in four size buckets named `100`, `2k`, `16k` and `50k` (about 400 bytes to 200 KB of text; the tables show each bucket's median token count) and five kinds: code, prose, Chinese text, JSON and a mix. The text comes from SMG's own Rust sources and docs, and from a public-domain Chinese novel (Project Gutenberg #23962). The corpus builder is deterministic, so anyone can rebuild the same prompts and check them by sha256.
- A stress set covers base64, minified JSON, emoji ZWJ sequences, combining marks, literal special tokens, and 60–140 KB slices that cross fastokens' 64 KiB parallel threshold.

### How the numbers are made

- **Parity is a gate.** Every candidate is compared with SMG's ids for `add_special_tokens` false (chat) and true (embeddings), on all rendered prompts, on the stress set, on growing chats replayed through SMG's caches, and for fastokens at several thread counts. Two controls check the harness itself: SMG against itself must show 0 mismatches, and a copy that drops the last id must mismatch on every non-empty input.
- **Fresh prompts are the headline.** Each encoder first encodes a separate warm-up corpus (same sources, different random draws). Its caches then hold common word pieces, as on a gateway that has served similar traffic, but the timed prompts are new to the process. Exact repeats are timed separately.
- **Timing:** caches are off unless the label says so. Each leg is one process with one encode per prompt per variant, and the variant order rotates per prompt. Builds alternate in a palindromic order (`z tok toksys hotdeps o2 o2 hotdeps ...`) so slow drift hits every build equally. Per prompt the median over legs is taken, then the median per bucket. CPU time counts all threads, because fastokens can split one large prompt across cores.
- **Throughput:** one pass over a larger corpus with N workers on one shared queue, so every prompt is encoded exactly once.
- **Memory:** peak RSS after loading each encoder, and after a full-concurrency throughput pass.
- **Environment:** the allocator is jemalloc, as in the gateway. `PCRE2_SYS_STATIC=1` builds the bundled PCRE2, so every machine runs the same PCRE2 code.

## Results

"SMG as shipped" means SMG at commit [`33dd6c4e`](https://github.com/smg-project/smg/commit/33dd6c4e717b0370d09f0817de82d10a5a50ec6e) (26 September 2026), with its release profile at `opt-level = "z"`. A number in brackets is the speed-up over SMG as shipped in the same file. The one exception is "fastokens, 1 thread", which is compared with SMG timed in the same one-thread process.

Please read the numbers with these limits in mind:

- The Apple M4 run was on battery power (Low Power Mode off), as its setup line says.
- The Linux runs used GitHub-hosted runners (virtual machines with 4 logical CPUs, as their setup lines show).
- Compare columns within one machine. Comparing absolute times across machines says little.
- The results files also have p90 tables, CPU time per prompt, run-to-run spread and exact-repeat tables.

<!-- results:start -->
<!-- Made by scripts/summarize_results.py from the files in results/. Do not edit by hand. -->

In short (the smallest and largest speed-up printed in the results files, over both models, all prompt sizes and all three machines):

- **fastokens** encodes fresh prompts 4.0× to 18.1× faster than SMG as shipped, with the same token ids (5.4× to 12.2× when it may use only one thread).
- **SMG's own path at opt-level 2** (`o2`) is 1.5× to 1.9× faster than the shipped `opt-level = "z"` build. Raising only the `tokenizers` crate to opt-level 2 (`tok`) already gives 1.4× to 1.6×.
- **HF `encode_fast`** (no offsets) gives 1.0× to 1.1×, so leaving out offsets saves little.
- **Multi-turn chats:** turning on SMG's L0/L1 caches gives 0.7× to 0.8× for DeepSeek-V3.2 (slower than no cache) and 1.0× for Qwen3.

### Setup of each run

| machine | file | CPU | OS | power | rustc | timing legs |
|---|---|---|---|---|---|---|
| Apple M4 | [2026-09-27-mac-m4.md](results/2026-09-27-mac-m4.md) | Apple M4 (4 P-cores, 10 logical, 16 GiB) | macOS 27.0 | battery, Low Power Mode off | rustc 1.97.1 (8bab26f4f 2026-07-14) (Homebrew) | 10 legs per build, 1 round per leg, palindromic build order |
| Linux x86_64 | [2026-09-28-gha-linux-x86_64.md](results/2026-09-28-gha-linux-x86_64.md) | AMD EPYC 7763 64-Core Processor (4 logical, x86_64) | Linux 6.17.0-1022-azure | n/a | rustc 1.98.0 (88d9e12ae 2026-08-18) | 6 legs per build, 1 round per leg, palindromic build order |
| Linux arm64 | [2026-09-28-gha-linux-arm64.md](results/2026-09-28-gha-linux-arm64.md) | Neoverse-N2 (4 logical, aarch64) | Linux 6.17.0-1022-azure | n/a | rustc 1.98.0 (88d9e12ae 2026-08-18) | 6 legs per build, 1 round per leg, palindromic build order |

### Token-id parity

Each row compares one candidate with SMG on 119 inputs (both `add_special_tokens` settings), or on 72 growing-chat turns through the caches. The row counts cover every build and fastokens thread count in the file.

| machine | parity rows (both models) | rows with any mismatch |
|---|---|---|
| Apple M4 | 92 | 0 |
| Linux x86_64 | 92 | 0 |
| Linux arm64 | 92 | 0 |

### Fresh prompts, Qwen3-4B: median ms per prompt (speed-up over SMG as shipped), caches off

| machine | bucket | tokens (median) | SMG as shipped | SMG, all O2 | HF encode_fast | fastokens | fastokens, 1 thread |
|---|---|---|---|---|---|---|---|
| Apple M4 | 100 | 128 | 0.12 | 0.07 (1.8×) | 0.11 (1.1×) | 0.02 (7.7×) | 0.01 (10.3×) |
| Apple M4 | 2k | 3,043 | 2.65 | 1.42 (1.9×) | 2.65 (1.0×) | 0.28 (9.5×) | 0.21 (12.2×) |
| Apple M4 | 16k | 20,374 | 17.70 | 9.62 (1.8×) | 18.01 (1.0×) | 1.30 (13.6×) | 1.50 (11.6×) |
| Apple M4 | 50k | 63,446 | 53.17 | 28.72 (1.9×) | 53.14 (1.0×) | 2.94 (18.1×) | 4.56 (11.6×) |
| Linux x86_64 | 100 | 128 | 0.21 | 0.14 (1.5×) | 0.18 (1.1×) | 0.03 (7.2×) | 0.02 (8.6×) |
| Linux x86_64 | 2k | 3,043 | 4.21 | 2.73 (1.5×) | 4.11 (1.0×) | 0.46 (9.1×) | 0.41 (10.1×) |
| Linux x86_64 | 16k | 20,374 | 28.48 | 18.52 (1.5×) | 28.33 (1.0×) | 2.64 (10.8×) | 2.78 (9.8×) |
| Linux x86_64 | 50k | 63,446 | 87.50 | 56.58 (1.5×) | 86.09 (1.0×) | 6.17 (14.2×) | 8.72 (9.8×) |
| Linux arm64 | 100 | 128 | 0.25 | 0.16 (1.6×) | 0.24 (1.0×) | 0.04 (5.6×) | 0.03 (8.8×) |
| Linux arm64 | 2k | 3,043 | 4.87 | 2.95 (1.7×) | 4.80 (1.0×) | 0.60 (8.1×) | 0.45 (10.7×) |
| Linux arm64 | 16k | 20,374 | 31.93 | 19.99 (1.6×) | 31.79 (1.0×) | 2.60 (12.3×) | 2.68 (11.6×) |
| Linux arm64 | 50k | 63,446 | 94.02 | 59.59 (1.6×) | 92.75 (1.0×) | 5.49 (17.1×) | 8.11 (11.6×) |

### Fresh prompts, DeepSeek-V3.2: median ms per prompt (speed-up over SMG as shipped), caches off

| machine | bucket | tokens (median) | SMG as shipped | SMG, all O2 | HF encode_fast | fastokens | fastokens, 1 thread |
|---|---|---|---|---|---|---|---|
| Apple M4 | 100 | 109 | 0.12 | 0.07 (1.7×) | 0.11 (1.1×) | 0.02 (6.6×) | 0.02 (6.5×) |
| Apple M4 | 2k | 2,930 | 2.74 | 1.56 (1.8×) | 2.69 (1.0×) | 0.36 (7.5×) | 0.35 (7.6×) |
| Apple M4 | 16k | 18,922 | 17.25 | 9.94 (1.7×) | 17.40 (1.0×) | 2.17 (7.9×) | 2.49 (6.9×) |
| Apple M4 | 50k | 58,296 | 51.49 | 30.05 (1.7×) | 51.54 (1.0×) | 5.85 (8.8×) | 7.49 (6.9×) |
| Linux x86_64 | 100 | 109 | 0.20 | 0.13 (1.5×) | 0.18 (1.1×) | 0.03 (6.5×) | 0.03 (6.2×) |
| Linux x86_64 | 2k | 2,930 | 4.42 | 2.89 (1.5×) | 4.32 (1.0×) | 0.59 (7.5×) | 0.58 (7.4×) |
| Linux x86_64 | 16k | 18,922 | 27.41 | 18.05 (1.5×) | 27.18 (1.0×) | 3.84 (7.1×) | 3.87 (6.9×) |
| Linux x86_64 | 50k | 58,296 | 84.89 | 56.72 (1.5×) | 83.44 (1.0×) | 10.58 (8.0×) | 11.85 (7.1×) |
| Linux arm64 | 100 | 109 | 0.25 | 0.16 (1.6×) | 0.25 (1.0×) | 0.06 (4.0×) | 0.04 (5.4×) |
| Linux arm64 | 2k | 2,930 | 5.28 | 3.33 (1.6×) | 5.15 (1.0×) | 0.92 (5.7×) | 0.80 (6.3×) |
| Linux arm64 | 16k | 18,922 | 31.57 | 20.40 (1.5×) | 30.75 (1.0×) | 3.81 (8.3×) | 4.20 (7.2×) |
| Linux arm64 | 50k | 58,296 | 95.36 | 60.85 (1.6×) | 92.10 (1.0×) | 10.08 (9.5×) | 12.07 (7.6×) |

### Which crates the opt-level gain comes from (50k bucket, median ms per prompt)

| machine | model | SMG as shipped | SMG, tokenizers at O2 | SMG, tokenizers+onig at O2 | SMG, HF hot deps at O2 | SMG, all O2 |
|---|---|---|---|---|---|---|
| Apple M4 | Qwen3-4B | 53.17 | 33.92 (1.6×) | 32.59 (1.6×) | 32.05 (1.7×) | 28.72 (1.9×) |
| Apple M4 | DeepSeek-V3.2 | 51.49 | 34.49 (1.5×) | 33.35 (1.5×) | 33.08 (1.6×) | 30.05 (1.7×) |
| Linux x86_64 | Qwen3-4B | 87.50 | 61.95 (1.4×) | 60.92 (1.4×) | 61.72 (1.4×) | 56.58 (1.5×) |
| Linux x86_64 | DeepSeek-V3.2 | 84.89 | 62.61 (1.4×) | 61.20 (1.4×) | 61.79 (1.4×) | 56.72 (1.5×) |
| Linux arm64 | Qwen3-4B | 94.02 | 65.54 (1.4×) | 63.18 (1.5×) | 62.99 (1.5×) | 59.59 (1.6×) |
| Linux arm64 | DeepSeek-V3.2 | 95.36 | 66.22 (1.4×) | 65.01 (1.5×) | 65.21 (1.5×) | 60.85 (1.6×) |

### Growing chats: median ms per turn (every turn re-sends the whole history)

| machine | model | bucket | tokens (median) | SMG as shipped | SMG + L0/L1 caches | fastokens | fastokens + L0/L1 caches |
|---|---|---|---|---|---|---|---|
| Apple M4 | Qwen3-4B | 16k | 12,877 | 11.25 | 11.22 (1.0×) | 1.34 (8.4×) | 1.58 (7.1×) |
| Apple M4 | Qwen3-4B | 50k | 32,136 | 29.18 | 29.60 (1.0×) | 2.11 (13.8×) | 2.71 (10.8×) |
| Apple M4 | DeepSeek-V3.2 | 16k | 12,158 | 10.76 | 13.13 (0.8×) | 1.54 (7.0×) | 4.31 (2.5×) |
| Apple M4 | DeepSeek-V3.2 | 50k | 30,766 | 29.69 | 37.81 (0.8×) | 2.87 (10.3×) | 11.08 (2.7×) |
| Linux x86_64 | Qwen3-4B | 16k | 12,877 | 18.16 | 18.06 (1.0×) | 2.26 (8.0×) | 2.61 (7.0×) |
| Linux x86_64 | Qwen3-4B | 50k | 32,136 | 47.37 | 47.33 (1.0×) | 4.11 (11.5×) | 5.04 (9.4×) |
| Linux x86_64 | DeepSeek-V3.2 | 16k | 12,158 | 17.14 | 24.31 (0.7×) | 2.56 (6.7×) | 9.00 (1.9×) |
| Linux x86_64 | DeepSeek-V3.2 | 50k | 30,766 | 47.26 | 67.14 (0.7×) | 5.30 (8.9×) | 25.00 (1.9×) |
| Linux arm64 | Qwen3-4B | 16k | 12,877 | 19.81 | 20.10 (1.0×) | 2.40 (8.2×) | 2.72 (7.3×) |
| Linux arm64 | Qwen3-4B | 50k | 32,136 | 49.02 | 49.90 (1.0×) | 3.70 (13.3×) | 4.42 (11.1×) |
| Linux arm64 | DeepSeek-V3.2 | 16k | 12,158 | 19.89 | 27.12 (0.7×) | 3.10 (6.4×) | 10.14 (2.0×) |
| Linux arm64 | DeepSeek-V3.2 | 50k | 30,766 | 52.08 | 71.03 (0.7×) | 5.09 (10.2×) | 22.47 (2.3×) |

### Throughput, `z` build: million tokens per second (one pass over fresh prompts)

| machine | model | all workers | SMG, 1 worker | fastokens, 1 worker | SMG, all workers | fastokens, all workers |
|---|---|---|---|---|---|---|
| Apple M4 | Qwen3-4B | 10 | 1.08 | 13.47 | 7.01 | 47.76 |
| Apple M4 | DeepSeek-V3.2 | 10 | 1.04 | 8.71 | 6.73 | 39.99 |
| Linux x86_64 | Qwen3-4B | 4 | 0.68 | 7.96 | 1.57 | 15.38 |
| Linux x86_64 | DeepSeek-V3.2 | 4 | 0.64 | 5.54 | 1.48 | 11.56 |
| Linux arm64 | Qwen3-4B | 4 | 0.64 | 7.60 | 2.48 | 20.01 |
| Linux arm64 | DeepSeek-V3.2 | 4 | 0.60 | 4.96 | 2.33 | 13.53 |

### Load time and memory (MB above an empty process)

| machine | model | SMG load ms | fastokens load ms | SMG MB after a full pass | fastokens MB after a full pass |
|---|---|---|---|---|---|
| Apple M4 | Qwen3-4B | 173 | 460 | 600 | 322 |
| Apple M4 | DeepSeek-V3.2 | 117 | 375 | 544 | 293 |
| Linux x86_64 | Qwen3-4B | 294 | 743 | 381 | 293 |
| Linux x86_64 | DeepSeek-V3.2 | 188 | 568 | 322 | 245 |
| Linux arm64 | Qwen3-4B | 427 | 1015 | 342 | 262 |
| Linux arm64 | DeepSeek-V3.2 | 273 | 794 | 307 | 256 |
<!-- results:end -->

## Run it yourself

You need Rust (the committed runs used rustc 1.97 and 1.98), Python 3.8 or newer (standard library only), git, curl and a C compiler (onig, PCRE2 and jemalloc are built from source). On Linux, `/usr/bin/time` from the GNU `time` package is used for peak memory.

```bash
git clone https://github.com/bhargavchintam/smg-encode-benchmark.git
cd smg-encode-benchmark
DATA="$HOME/encode-bench-data"   # any folder outside this repository

# 1. Tokenizer files at the revisions in scripts/pins.json (sha256-checked)
python3 scripts/fetch_models.py --out "$DATA/models"

# 2. Text for the prompts: SMG's sources at commit 33dd6c4e, and a
#    public-domain Chinese novel (Project Gutenberg #23962)
git clone --filter=blob:none https://github.com/smg-project/smg.git "$DATA/smg-src"
git -C "$DATA/smg-src" checkout --detach 33dd6c4e717b0370d09f0817de82d10a5a50ec6e
mkdir -p "$DATA/sources"
CJK="$DATA/sources/gutenberg-23962-xiyouji.txt"
curl -sSfL -o "$CJK" https://www.gutenberg.org/ebooks/23962.txt.utf-8
echo "af3c9e408c0c58595b666ed9981b6fa1e9343f4bbc78309b1cb0818c32fc1f58  $CJK" | shasum -a 256 -c -

# 3. Three corpora: timed, warm-up and throughput
python3 scripts/build_corpus.py --repo "$DATA/smg-src" --cjk "$CJK" --out "$DATA/corpus"
python3 scripts/build_corpus.py --repo "$DATA/smg-src" --cjk "$CJK" --out "$DATA/corpus-warmup" --seed 99 --per-bucket 20 --stress-slices 3
python3 scripts/build_corpus.py --repo "$DATA/smg-src" --cjk "$CJK" --out "$DATA/corpus-throughput" --seed 7 --per-bucket 100 --stress-slices 3

# Optional: check that you got the same prompts as the committed results
shasum -a 256 -c - <<EOF
b5050a08bf6775c3c2666658ac0ee7dad765d9f1a4c1088325042f0054e5b887  $DATA/corpus/conversations.jsonl
d53964f8a38c1a7beebcffb7fad973f84b2c51cb2100ffcd903ba577096d4797  $DATA/corpus-warmup/conversations.jsonl
3de5bd7ff4378daabe38d5af4fb9399b6d598fe4e45070eaa317688672c335f3  $DATA/corpus-throughput/conversations.jsonl
EOF

# 4. Build the five variants, then run parity, timing, multi-turn,
#    throughput and memory, and write results.md.
#    On a Mac, plug in (or pass --allow-battery).
python3 scripts/run_bench.py --data "$DATA" --legs 10
```

The report lands in `$DATA/results/<run-id>/results.md`, next to the raw CSV and JSON files. To run it on GitHub-hosted Linux runners instead, start the manual **Encode benchmark** workflow ([`.github/workflows/encode-bench.yml`](.github/workflows/encode-bench.yml)). The two Linux results files came from that workflow.

You can also call the harness directly. `cargo build --release` gives `target/release/encode_backends`, with the subcommands `render`, `parity`, `time`, `turns`, `throughput` and `load`. The doc comment at the top of [`src/main.rs`](src/main.rs) lists their options.

### Tests

- Harness: `cargo test`. One test needs a downloaded model: set `ENCODE_BENCH_MODEL_DIR` to a model folder and run `cargo test -- --include-ignored`.
- Scripts: `cd scripts && python3 -m unittest`. This also checks that the results section of this README still matches the files in `results/` (`python3 scripts/summarize_results.py --write` rebuilds it).

Local check: on 27 October 2026, on an Apple M4 Mac with cargo 1.98.1, `cargo build --release`, `cargo test` and `cargo clippy --all-targets -- -D warnings` all passed (13 tests passed, and the one that needs a model was skipped). I did not run the full benchmark again from this repository; the results are the ones made in the fork.

## Context

The harness and results come from two branches of my fork, [bhargavchintam/smg](https://github.com/bhargavchintam/smg), made on 27–28 September 2026:

- [`bhargavchintam/fast-encode-bench`](https://github.com/bhargavchintam/smg/tree/bhargavchintam/fast-encode-bench): 15 commits with the harness, the scripts, the CI workflow and the three results files.
- [`bhargavchintam/fast-encode-bench-l1-fix`](https://github.com/bhargavchintam/smg/tree/bhargavchintam/fast-encode-bench-l1-fix): the same work plus one change to SMG's L1 cache, which finds special-token boundaries in one pass (16 commits).

Upstream SMG later shipped related changes:

- [smg-project/smg#2768](https://github.com/smg-project/smg/pull/2768) (merged 5 October 2026): the image, tokenizer and routing-tree crates are built at opt-level 3.
- [smg-project/smg#3385](https://github.com/smg-project/smg/pull/3385) (merged 13 October 2026): the L1 prefix cache finds its boundaries in one pass over the input.
- [smg-project/smg#3715](https://github.com/smg-project/smg/pull/3715) (merged 16 October 2026): the whole release profile moves from `opt-level = "z"` to `opt-level = 3`.

So "SMG as shipped" in these results is SMG before those changes. This repository is a write-up of my measurements. It does not claim credit for the upstream changes.

## Changes from the fork

The code is the same as in the fork, with only the changes needed to build it on its own:

- `src/main.rs` is the fork's `crates/tokenizer/examples/encode_backends.rs`, now a binary that depends on `llm-tokenizer` 1.8.0 from crates.io instead of SMG's workspace. I compared the published 1.8.0 crate with SMG at commit 33dd6c4e: the encode and cache code is the same, and the only differences are reasoning-effort settings (a new `native_reasoning_effort_off_values` trait method, and detection of Hy4 chat templates). So the harness no longer forwards `native_reasoning_effort_off_values`, because 1.8.0's `Tokenizer` trait does not have it.
- `Cargo.toml` copies SMG's release profile from commit 33dd6c4e, so the `z` build matches. `Cargo.lock` was started from the fork's lock file, so every dependency keeps the version used for the results (for example `tokenizers` 0.23.1 and `fastokens` 0.3.2).
- `.cargo/config.toml` is the fork's file (SMG's settings plus `PCRE2_SYS_STATIC=1`), with a comment added.
- The scripts use the new paths. `run_bench.py` builds `--bin encode_backends`, and its setup section records this repository's commit (`bench_commit`) and the `llm-tokenizer` version, instead of `smg_commit`.
- New: `scripts/summarize_results.py`, which builds the results section of this README, and the `CI` workflow, which builds the harness and runs both test suites.
- Not included: the one-pass L1 change from the `fast-encode-bench-l1-fix` branch. It changes SMG's library, not the benchmark, and none of the results files were made with it.

The first commit of this repository has the fork's files copied without changes, so a diff against that commit shows exactly what changed.

## Layout

```text
src/main.rs        the harness (render, parity, time, turns, throughput, load)
scripts/           corpus builder, model fetcher, driver, table maker, and their tests
results/           the three committed results files
.github/workflows/ CI (build and tests) and the manual benchmark workflow
```

## Credits and license

This benchmark measures SMG's `llm-tokenizer` crate, and it reuses SMG's release profile and build settings. SMG is made by the [smg-project](https://github.com/smg-project/smg) team and is licensed under the Apache License 2.0. The encoders compared are [Hugging Face tokenizers](https://github.com/huggingface/tokenizers) and [fastokens](https://github.com/crusoecloud/fastokens).

This repository is licensed under the Apache License 2.0, the same as SMG. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
