"""Tests for summarize_results.py. Run: python3 -m unittest -v test_summarize_results"""

import re
import unittest

import summarize_results as sr


class SummarizeResultsTest(unittest.TestCase):
    def setUp(self):
        self.reports = sr.load_reports(sr.ROOT / "results")
        self.section = sr.render(self.reports)
        self.files = {label: (sr.ROOT / "results" / name).read_text(encoding="utf-8") for label, name in sr.MACHINES}

    def test_readme_matches_the_results_files(self):
        readme = sr.README.read_text(encoding="utf-8")
        self.assertEqual(
            sr.replace_section(readme, self.section), readme, "README.md is out of date: run python3 scripts/summarize_results.py --write"
        )

    def test_every_number_in_a_table_is_copied_from_its_results_file(self):
        checked = 0
        for line in self.section.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not line.startswith("| ") or cells[0] not in self.files:
                continue
            if len(cells) == 3 and cells[1].isdigit():
                continue  # parity row counts: counted here, not measured
            for cell in cells[1:]:
                if re.search(r"\d", cell) and not cell.startswith("["):
                    self.assertIn(cell, self.files[cells[0]], line)
                    checked += 1
        self.assertGreater(checked, 300)

    def test_summary_speedups_are_printed_in_the_files(self):
        for prefix, column in [(sr.FRESH, "fastokens"), (sr.FRESH, "SMG, all O2"), (sr.TURNS, "SMG + L0/L1 caches")]:
            low, high = sr.speedups(self.reports, prefix, column)
            self.assertLessEqual(float(low), float(high))
            for value in (low, high):
                self.assertTrue(any(f"({value}×)" in text for text in self.files.values()), value)

    def test_parity_has_no_mismatch_in_any_file(self):
        table = sr.parity_summary(self.reports)
        for label in self.files:
            self.assertRegex(table, rf"\| {re.escape(label)} \| \d+ \| 0 \|")

    def test_parse_report_reads_setup_and_tables(self):
        text = "\n".join(
            [
                "# Encode benchmark results (x)",
                "## Setup",
                "- **machine**: m1",
                "## qwen3",
                "### Encode latency on fresh prompts, median ms",
                "| bucket | SMG as shipped |",
                "|---|---|",
                "| 2k | 2.65 |",
            ]
        )
        report = sr.parse_report(text)
        self.assertEqual(report["setup"], {"machine": "m1"})
        self.assertEqual(sr.table(report, "qwen3", sr.FRESH), [{"bucket": "2k", "SMG as shipped": "2.65"}])


if __name__ == "__main__":
    unittest.main()
