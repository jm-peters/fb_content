# fb_content

The daily GitHub Actions workflow requires these Actions secrets:
`GEMINI_API_KEY`, `PIXABAY_API_KEY`, `FB_PAGE_ID`, and `FB_PAGE_ACCESS_TOKEN`.
Add them under the repository's **Settings → Secrets and variables → Actions**,
or grant this repository access to the organization secrets. The workflow passes
them to the Python process as environment variables and checks that they are
available before starting.

The workflow runs once daily at 4:00 PM EAT Monday through Friday, 9:00 AM EAT
Saturday, and 3:00 PM EAT Sunday. It generates and schedules only that day's
post. Content generation defaults to `gemini-3.8-flash`, then falls back to
`gemini-3.6-flash` and `gemini-3.5-flash-lite`; retryable 429 and server errors
use exponential backoff starting at two seconds. Set `GEMINI_MODEL` to override
the first model.

The generator uses Google Search grounding for Sunday's AI and tech news digest.
Previously scheduled posts in `history.json` are detected before generating
another post for the same date, and the workflow commits the updated history.

No local `.env` file is needed in GitHub Actions. For local runs, the application
reads the same values directly from the process environment; it does not load
`.env` files automatically. Reel scene backgrounds are selected from Pixabay
using each scene's visual prompt.
