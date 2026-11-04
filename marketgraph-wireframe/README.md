# MarketGraph wireframe

Interactive static website prototype for MarketGraph. No installation or build is required.

## Start on Windows

Extract the ZIP, open PowerShell inside the extracted marketgraph-wireframe folder, and run:

```powershell
py -m http.server 8000 --directory dist
```

Open http://localhost:8000/ in your browser. Stop the server with Ctrl+C. On other systems use `python3 -m http.server 8000 --directory dist`. External fonts and source links require internet access.

## Main screens

- `dist/index.html`: landing page
- `/auth/`: sign-in and signup screen layouts
- `/demo/#dashboard`: workspace and role preview
- `/demo/#catalog`: explore stocks; `/demo/#stock/RELIANCE` opens a stock page
- `/demo/#watchlists`: saved and active watchlists
- `/demo/#alerts`: sample stock and derivatives opportunity layouts
- `/demo/#profile`: account, plan and usage, and market data
- `/demo/#admin-dashboard`: developer preview; select Professionals to add, search, or update sample professionals

## Scope

This is an interactive UI prototype, not a production app. Data, financial figures, alerts and accounts are examples. Edits are stored locally in your browser. No real authentication, agent, continuous monitoring, broker tokens, trading, checkout, or backend data services are connected. Free and Pro plans are manually assigned in the demo; professional verification is separate. No Three.js is used.

Run optional checks from this folder using `node tests/management-wireframe.cjs`, `node tests/role-wireframe.cjs`, and `node tests/financial-layout.cjs`. These test prototype behavior with DOM stubs and are not browser visual tests.
