from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest

from scripts.load_screaming_frog_export import CrawlExportMetadata, build_export_payload


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [",".join(header)]
    lines.extend(",".join(row) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class ScreamingFrogExportLoaderTest(unittest.TestCase):
    def meta(self, export_dir: Path, *, crawl_scope: str = "partial_scope", scope_ref: str | None = "homepage", min_urls: int = 100) -> CrawlExportMetadata:
        return CrawlExportMetadata(
            export_dir=export_dir,
            client_slug="melani-the-label",
            client_name="Melani the Label",
            crawl_id="melani-test-crawl",
            run_id="melani-test-crawl",
            crawl_date=date(2026, 6, 14),
            crawl_trigger="post_task",
            crawl_scope=crawl_scope,
            scope_ref=scope_ref,
            start_url="https://melanithelabel.com",
            min_urls=min_urls,
            ingested_at="2026-06-14T00:00:00+00:00",
        )

    def test_parser_preserves_raw_json_and_maps_known_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_csv(
                root / "internal_all.csv",
                ["Address", "Status Code", "Indexability", "Title 1", "Meta Description 1", "H1-1", "Word Count"],
                [["https://example.com/", "200", "Indexable", "Home", "Desc", "Heading", "450"]],
            )
            write_csv(
                root / "issues_overview_report.csv",
                ["Issue Name", "Issue Type", "Issue Priority", "URLs"],
                [["Page Titles: Below 30 Characters", "Opportunity", "Medium", "1"]],
            )
            write_csv(
                root / "all_inlinks.csv",
                ["Type", "Source", "Destination", "Anchor", "Status Code"],
                [["Hyperlink", "https://example.com/", "https://example.com/products", "Products", "200"]],
            )
            write_csv(root / "custom_report.csv", ["Custom Field", "Address"], [["kept", "https://example.com/custom"]])

            payload = build_export_payload(self.meta(root))

        self.assertTrue(payload.coverage_valid)
        self.assertEqual(len(payload.url_rows), 1)
        self.assertEqual(len(payload.issue_rows), 1)
        self.assertEqual(len(payload.link_rows), 1)
        self.assertEqual(len(payload.export_rows), 4)
        self.assertEqual(payload.url_rows[0]["raw_row_json"]["Title 1"], "Home")
        self.assertEqual(payload.issue_rows[0]["issue_name"], "Page Titles: Below 30 Characters")
        self.assertEqual(payload.link_rows[0]["destination_url"], "https://example.com/products")
        self.assertIn("custom_report.csv", payload.row_counts)
        custom = [row for row in payload.export_rows if row["source_file"] == "custom_report.csv"][0]
        self.assertEqual(custom["raw_row_json"]["Custom Field"], "kept")

    def test_full_site_low_coverage_stores_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_csv(root / "internal_all.csv", ["Address", "Status Code"], [["https://example.com/", "200"]])
            payload = build_export_payload(self.meta(root, crawl_scope="full_site", scope_ref=None, min_urls=100))

        self.assertFalse(payload.coverage_valid)
        self.assertEqual(payload.run_row["crawl_status"], "coverage_failed")
        self.assertEqual(payload.url_rows, [])
        self.assertEqual(payload.export_rows, [])

    def test_partial_scope_requires_scope_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_csv(root / "internal_all.csv", ["Address", "Status Code"], [["https://example.com/", "200"]])
            with self.assertRaises(ValueError):
                build_export_payload(self.meta(root, crawl_scope="partial_scope", scope_ref=None))

    def test_rejects_raw_page_content_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_csv(root / "raw_html_export.csv", ["Address", "Raw HTML"], [["https://example.com/", "<html>"]])
            write_csv(root / "internal_all.csv", ["Address", "Status Code"], [["https://example.com/", "200"]])
            payload = build_export_payload(self.meta(root))

        self.assertIn("raw_html_export.csv", payload.blocked_files)
        self.assertEqual(len(payload.export_rows), 1)


if __name__ == "__main__":
    unittest.main()
