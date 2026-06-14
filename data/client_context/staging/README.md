# Client Context Staging

Place reviewed, sanitized client onboarding summaries here as `.jsonl`.

Each line should be one client profile with short, non-sensitive fields only:

```json
{"client_slug":"example-client","client_name":"Example Client","business_summary":"Short public-safe summary.","primary_goals":["Grow organic revenue"],"seo_priorities":["Improve collection page visibility"],"target_audience":"Short audience summary.","key_products_or_services":["Primary service"],"important_pages":["/collections/example"],"brand_tone":"Concise tone guidance.","constraints_or_risks":["Short operational risk"],"approval_preferences":"Short approval preference.","reporting_expectations":"Short reporting expectation.","agent_context_summary":"One short briefing sentence for agents.","source_drive_file_id":"opaqueDriveFileId123","source_drive_file_name":"Reviewed onboarding summary","source_modified_at":"2026-06-12T00:00:00+00:00","review_status":"reviewed","confidence":0.8}
```

Do not stage raw onboarding form bodies, contact details, emails, phone numbers, credentials, Drive comments, permissions, or long copied answers.
