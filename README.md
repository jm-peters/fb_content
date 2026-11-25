# fb_content

The weekly GitHub Actions workflow requires these Actions secrets:
`GEMINI_API_KEY`, `PIXABAY_API_KEY`, `FB_PAGE_ID`, and `FB_PAGE_ACCESS_TOKEN`.
Add them under the repository's **Settings → Secrets and variables → Actions**,
or grant this repository access to the organization secrets. The workflow passes
them to the Python process as environment variables and checks that they are
available before starting.

No local `.env` file is needed in GitHub Actions. For local runs, the application
reads the same values directly from the process environment; it does not load
`.env` files automatically. Reel scene backgrounds are selected from Pixabay
using each scene's visual prompt.
