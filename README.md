# fb_content

The weekly GitHub Actions workflow requires these Actions secrets:
`GEMINI_API_KEY`, `PIXABAY_API_KEY`, `FB_PAGE_ID`, and `FB_PAGE_ACCESS_TOKEN`.
Add them under the repository's **Settings → Secrets and variables → Actions**,
or grant this repository access to the organization secrets. The workflow passes
them to the Python process as environment variables and checks that they are
available before starting.

Content generation defaults to `gemini-3.8-flash`. If Google reports that a model
is unavailable, the generator tries `gemini-3.6-flash` and then
`gemini-3.5-flash-lite`. Set `GEMINI_MODEL` to override the first model.

Completed posts are saved to `data/weekly_content_plan.progress.json` as they
are generated. If generation is interrupted, the workflow commits that progress
and checks for resumable work every six hours; completed posts are reused rather
than generated again. A Gemini 429 stops the current attempt immediately so the
next scheduled retry can resume after quota becomes available. The checkpoint
is removed after the full weekly workflow succeeds.

No local `.env` file is needed in GitHub Actions. For local runs, the application
reads the same values directly from the process environment; it does not load
`.env` files automatically. Reel scene backgrounds are selected from Pixabay
using each scene's visual prompt.
