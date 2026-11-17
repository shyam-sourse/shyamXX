# ShyamX — single-host deployment guide

ShyamX is now ONE project: the website (public site + server dashboard + admin
panel) and the Discord bot (+ its FastAPI backend) live in the same repo and run
together on one host, from one `.env` file.

```
shyamx/
├── run.py              ← start here: the single-host launcher
├── .env.example        ← the ONE config file for everything
├── CodeX.py             the bot + its embedded FastAPI (unchanged entrypoint)
├── api/, cogs/, core/…  the bot (unchanged)
├── db/                  bot SQLite databases (unchanged)
└── web/                 the website (TanStack Start), formerly a separate repo
```

## Quick start

```bash
cd shyamx
python run.py --init      # creates .env with generated secrets
nano .env                 # fill in TOKEN, OWNER_IDS, DISCORD_CLIENT_ID/SECRET, PUBLIC_URL
python run.py --build     # npm ci + build the website once
python run.py              # runs the website AND the bot together
```

Open the `PUBLIC_URL` you configured. The bot's API is bound to `127.0.0.1`
only — the browser never talks to it directly; the website does, over
localhost, using `DASHBOARD_API_KEY`.

### Docker

```bash
docker build -t shyamx .
docker run --env-file .env -p 3000:3000 -v $(pwd)/db:/app/db shyamx
```

The image runs `python run.py` as its entrypoint (build step included).

## What `run.py` actually does

It is a small supervisor, not a framework: it starts the website (Node) and the
bot (Python) as two child processes, restarts either one independently with
backoff if it crashes, and never lets one process's crash take down the other.
`--check` validates your `.env` without starting anything; `--init` generates
one with strong secrets; `--build` runs the website's install+build step.

## Reverse proxy / HTTPS

`run.py` serves plain HTTP on `WEB_PORT` (default 3000). Put a reverse proxy
(Caddy, Nginx, Cloudflare) in front for HTTPS — e.g. Caddy:

```
shyamx.example.com {
  reverse_proxy 127.0.0.1:3000
}
```

Set `PUBLIC_URL=https://shyamx.example.com` in `.env` to match.

## A real, hard-won gotcha for anyone extending `web/src/lib/*.server.ts`

**Every `createServerFn(...).handler(...)` call must be written literally at
the `export const` site.** Returning the *whole chain* from a factory/helper
function compiles without error and passes `tsc`, but at runtime the call
silently resolves to `undefined` instead of running — no thrown error, no log,
just `undefined`, which then crashes whatever destructures it. This was found
and fixed across every guild-module and admin-platform server function in this
codebase (see the `getFnHandler`/`writeFnHandler`/`adminGetHandler` pattern in
`web/src/lib/guild-modules.server.ts` and `admin-platform.server.ts`).

```ts
// ❌ Breaks silently at runtime — do not do this:
function makeGetter<T>(path: string) {
  return createServerFn({ method: "GET" }).handler(async () => { ... });
}
export const getThing = makeGetter<Thing>("/thing"); // resolves to undefined!

// ✅ Correct — createServerFn(...).handler(...) written literally here;
// only the HANDLER BODY may come from a shared factory:
function thingHandler<T>(path: string) {
  return async ({ data }: { data: { guildId: string } }) => { ... };
}
export const getThing = createServerFn({ method: "GET" })
  .inputValidator(validateGuildId)
  .handler(thingHandler<Thing>("/thing"));
```

If you add a new module endpoint, copy the pattern already used for the
existing ~25 module functions — never reintroduce the factory-returns-the-
whole-chain shape.

## Environment variables

See `.env.example` — it's the single source of truth and is documented inline.
Legacy variables (`CF_TUNNEL_URL`, `TUNNEL_ENABLED`, etc.) are kept for anyone
still running the bot standalone (without the website) but are not needed here.
