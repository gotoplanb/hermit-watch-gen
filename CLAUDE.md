# Hermit Watch — Claude Instructions

## This is a public GitHub repository

Never commit secrets, tokens, credentials, or URLs that expose infrastructure to this repo. Specifically:

- No real values for `READ_TOKEN`, `WRITE_TOKEN`, or any API keys in any committed file
- No ngrok tunnel URLs in committed files (they reveal live infrastructure)
- No Sumo Logic, Anthropic, or other third-party credentials
- `docs/` is version-controlled and public — use placeholders like `YOUR_WRITE_TOKEN` there

Real values live in `.env` only, which is gitignored. Before every commit, check that no secrets have crept into tracked files.
