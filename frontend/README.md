# MarketGraph frontend

This is the standalone Next.js App Router frontend. It uses the TRACK wireframe
as its visual reference and calls the authenticated Platform API through a
same-origin rewrite, so browser requests stay under `/api` and do not need CORS.

Copy `.env.example` to `.env.local` if the Platform API is not at
`http://127.0.0.1:8002`. Then run:

```powershell
npm.cmd install
npm.cmd run dev
```

Open `http://localhost:3000`. The app asks for an operator-provisioned Platform
token. It keeps the token in page memory only; reloads require entering it again.
In Compose, the Platform API is available to the host at `http://127.0.0.1:8002`.
Research and discovery jobs are processed by the separately hosted agent, so a
job remains queued until that service claims it.
