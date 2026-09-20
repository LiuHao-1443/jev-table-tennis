# Human vs JEV · Table Tennis

**English** · [中文](README.zh-CN.md)

> Every single movement of the paddle on the right is decided live by [Jev](https://typesafe.ai),
> TypeSafe's System One decision model. There is no local prediction, no fallback, no "AI assist" —
> what's left on the client is a lookup table and a servo.

In one sentence: **this is an instrument for watching whether a decision model can play table tennis
by itself. It also happens to be fun.**

One HTML file plus a small Python relay. No dependencies, no build step.
You play on the left with a mouse; Jev plays on the right with its head.

```
              ┌─────────────────────────────────┐
   browser ──►│  index.html (Canvas game)        │
              │  · physics, score, rendering     │
              │  · a 4-line servo that pushes    │
              │    the paddle to the commanded y │
              └──────────┬──────────────────────┘
                         │  POST /jev/decide  (state + question only)
              ┌──────────▼──────────────────────┐
              │  server.py (relay, keep-alive)   │
              │  · renders the state as text     │
              │  · asks a multiple-choice question
              │  · the option label IS the pixel │
              │    value — identity lookup       │
              └──────────┬──────────────────────┘
                         │  POST /v1/systemone   ← API key lives only here
              ┌──────────▼──────────────────────┐
              │  api.typesafe.ai                 │
              └─────────────────────────────────┘
```

## What exactly is handed to the model

This is the point of the project: **if all a model can do is read a situation and pick an option,
how well can it play?** So the boundary is drawn very tightly.

| | Who owns it |
| --- | --- |
| Where the ball will land, where to stand | **Jev** — whichever option it picks is where the paddle goes |
| Where to wait while the ball is not incoming | **Jev** |
| The arc of its serve | **Jev** (it picks an arc bucket) |
| The ball-speed cap | A fixed constant, **never derived from measured latency** — otherwise the test conditions could be moved by the thing under test |
| Physics, collisions, scoring, rendering | Local |
| Actually moving the paddle to the commanded y | Local — four lines |

```js
const goalCenter = incoming ? brain.target : brain.recoverTo;
const step = clamp(goalCenter - PH / 2 - jev.y, -limit * dt, limit * dt);
if (brain.online !== false) jev.y += step;      // offline ⇒ it stands still, it never plays for itself
```

**A single decision looks like this.** The relay renders the state as prose and asks one
multiple-choice question:

```text
The ball is at x=600, y=300, with velocity vx=700 px/s and vy=260 px/s. Its radius is 10 px.
The ball's current speed is 227 px/s, and every hit multiplies the speed by 1.100, up to
a maximum of 551 px/s. ... Your machine is at 100% of its top speed on this rally.

Q: Where should the CENTRE of your paddle be when the ball reaches your line?
   a1 → paddle centre at y=178.6      a2 → y=231.9      a3 → y=285.2   ...
```

It answers `a4`, and `a4` *is* `y=338.5` — **the option label and the pixel value are the same
table.** Nothing is converted locally.

Two constraints the API forced on the design (neither was my choice):

- **It does not emit numbers.** `type:"number"` and `type:"numeric"` both come back
  `400 Invalid request.` So "just have it output a pixel coordinate" is a dead end; options are the
  only channel.
- **Finer options are not better.** With 7 bands it scores 6/10; with 40 narrow bands it drops to
  **0/10** — forcing multi-step mental arithmetic makes it collapse. So the `7` in
  `placements_of()` is a measured value, not a guess.

## Quick start

```bash
# 1. provide a key (either way)
export TYPESAFE_API_KEY=your_key
#    or: cp jev.config.example.json jev.config.json  and fill it in

# 2. start the relay
python3 server.py

# 3. open whatever URL it prints
#    http://127.0.0.1:8760/
```

You need Python 3 and nothing else — **no `pip install`**, standard library only.
The page is a single HTML file: no build, no CDN, no frontend dependencies.

## Rules

- **You are on the left, JEV on the right.** 11 points per game, win by 2 after 10:10 with serve
  alternating every point, best of 3 games.
- **The ball keeps speeding up.** The serve starts at 70% of the cap (386 px/s), and **every hit
  multiplies the speed by 1.10** until it reaches the cap (551 px/s). Wall bounces don't speed it up.
  To change the cap:

  ```bash
  python3 server.py --cap 450     # slower, calmer (4 decisions per rally)
  python3 server.py --cap 700     # faster, harder (only 2 decisions)
  ```

  The default cap is not arbitrary — it is back-solved from the **measured decision latency**: a
  single flight has to fit "last decision round trip 0.55s + arm crossing the whole table 0.42s +
  at least one correction opportunity 0.55s" ⇒ `964 / 1.75 ≈ 551 px/s`.
- **It gets asked several times per rally.** During the 1.75s the ball is in flight it re-asks and
  re-corrects, and its final resting position obeys the **last** answer. Press `K` to turn this off
  and compare single-shot vs. closed-loop play.
- **It decides even when the ball isn't coming.** It answers "where should I wait for the next ball"
  instead of standing wherever it happens to be.
- Hitting further from the paddle's centre returns a wider angle. The difficulty setting only changes
  Jev's **actuator speed limit** and its persona prompt, never its "brain".

## Controls

| Action | Key |
| --- | --- |
| Move paddle | mouse / touch drag / `W` `S` / `↑` `↓` |
| Pause, resume | `Space` |
| Restart | `R` |
| Difficulty (easy / normal / hard / grandmaster) | `1` `2` `3` `4` |
| Single-shot vs. closed-loop | `K` |
| Mute | `M` |
| Show/hide the model's commanded target line | `P` |
| Open/close the JEV decision log | `L` |

The HUD shows what it's thinking: the target line carries its chosen landing spot and confidence, the
bottom bar its reaction speed and the current speed cap. The decision log (bottom right) holds **the
full record of every decision** — what it saw, what it was asked, how probability mass was distributed
across the options, how many tokens it cost, and which correction round this was. It survives a page
reload (it is stored server-side).

## Configuration

| Where | What |
| --- | --- |
| `TYPESAFE_API_KEY` env var | Highest priority |
| `jev.config.json` | Copy `jev.config.example.json` and edit; **already in .gitignore** |
| `--mode pure` / `assisted` | Defaults to `pure`; `assisted` is the control version with local helpers |
| `--cap N` | Ball-speed cap (px/s) |
| `--host 127.0.0.1` | Bind loopback only (default `0.0.0.0`, so people on your LAN can play) |
| `--mock-brain` | Swap in a test double — no tokens, no network |

## Playing with other people

The relay listens on `0.0.0.0` and prints your LAN URL at startup; send that URL to anyone in the room.
Nothing has to be configured per player: the client's default relay URL is `location.origin`, so when
someone opens your IP, the page talks to **your** IP rather than to their own `127.0.0.1`.

A keep-alive connection can only carry one request at a time, so the relay runs a **pool of 4
connections**. Measured with three simultaneous players, each player's per-decision median stayed at
the single-player number (~360ms) — no queueing.

## Security

- **The API key lives only inside the `server.py` process.** There is no credential in the page, so
  sniffing the traffic gets you nothing, and it cannot reach git (`jev.config.json` is gitignored and
  guarded by a pre-commit hook in `tests/`).
- **The relay is unauthenticated.** Anyone who can reach the address can spend your tokens. Fine on
  your own LAN, **do not put it on the public internet**.
- The cost is genuinely small: one decision is ~918 input tokens, and at the official $42/Btok with
  free output that is **~$0.00004 per decision**. With the closed loop a rally asks 3–5 times, so a
  full game (a few hundred decisions) costs a few cents.

## Tests

```bash
./tests/run_all.sh
```

**Entirely offline** — every model call is replaced by a stub, so it costs no tokens and touches no
network. Ten checks covering:

- Syntax, UI, decision log
- **Speed ramp**: starts at 70%, ×1.10 per rung, never decreases, never exceeds the cap, stops at it
- **Closed loop**: multiple asks per rally, re-asking measurably improves the landing estimate, and
  the final resting position obeys the last answer
- **Ready position**: only changes the "where to wait" target, never overrides an interception in flight
- **Timeout ≠ offline**: when the API hangs, the paddle keeps executing its last order — it neither
  freezes nor gets misreported as offline
- **Attribution audit**: ~100% hit rate when the model is right, 0% when it is deliberately inverted,
  and not a single pixel of movement while it is offline
- **Pure mode**: confirms nothing but a lookup table and a servo is left locally
- **Stale connection**: a fake server that stalls for 30s ⇒ returns in 1203ms (vs. 30004ms unfixed)

## Measured results (summary)

The full log lives in [`FINDINGS.md`](FINDINGS.md) *(written in Chinese)*, including the approaches
that were **rejected** and the exact command behind every number.

- **Of the ~350ms per step, the model itself thinks for 24ms.** A minimal request takes 313ms vs 337ms
  for a full one; the difference is its thinking time. The rest is network round trip (~200ms) and API
  server-side overhead (~110ms).
- **The biggest single win was connection reuse**: redoing the TLS handshake cost 0.45–1.5s per step;
  switching to keep-alive brought each step down to ~350ms.
- **7 bands is right; 40 bands collapses to 0/10.**
- **The closed loop really corrects**: with a stub that gets more accurate as the ball approaches, the
  first-ask error of 157px drops to 26px by the last ask.
- **Speed and thinking are in direct trade**: at a 551 cap a rally allows 3 decisions; at 332 it
  allowed 5. That trade-off is deliberate.

## Known trade-offs

- The faster Jev plays, the fewer decisions fit into a single rally — speed and decision quality
  cannot both be maximized.
- The relay has no authentication; **LAN only**.
- The speed cap is a constant rather than adaptive, deliberately, so that the test conditions cannot
  be moved by the thing under test.

## License

MIT — see [`LICENSE`](LICENSE).
