# gBlock Designer

A small app you run on your own computer, in your web browser, that:

1. **Designs a gBlock** from named primers arranged into pairs. You tell it the fragment length (the sequence between each pair's own primers) for each pair, and it works out every gap between primers automatically — no need to add up lengths by hand. Supports simple forward+reverse pairs, or more complex layouts like two forward primers sharing one reverse primer, or fully nested primer pairs.
2. **Checks the primers line up correctly** against the sequence it built, with a clear side-by-side diagram.
3. **Runs a real BLAST search** against NCBI's database, to see if your new sequence accidentally matches something that already exists.
4. **Runs a local complexity check** that mimics the kinds of problems IDT's own ordering tool looks for (GC content, repeated letters, repeated chunks, hairpins) — no login or internet needed for this step, and it finishes instantly. A "Try to fix flagged issues" button will automatically re-roll the random parts of the sequence until the issues clear up (where that's actually possible — see the note below).

Step 4 is a stand-in, not the real thing — it always ends with a reminder and a link to paste your sequence into IDT's actual site before you order, since IDT's real tool may catch things this simplified version doesn't.

## How the sequence is put together

You define two things:

**Primers** — every primer you're using, entered once each, with a name (e.g. "F1"), a direction (Forward/Reverse), and its sequence.

**Primer pairs** — pick a forward and a reverse primer from the list above, and enter that specific pair's fragment length. Fragment length here means the sequence strictly *between* that pair's own two primers — it does not include the length of those two primers themselves. If a different primer happens to sit physically in between (like a second forward primer nested inside), that other primer's length does count, since it's part of what's actually in between. A primer can be reused across multiple pairs just by picking it again — that's how you build shared-primer or nested layouts.

Simple example, one pair:

```
[30bp flank] [F1] [gap, worked out automatically] [reverse complement of R1] [30bp flank]
```

Two forward primers sharing one reverse primer (e.g. nested PCR, giving two different amplicon sizes off one construct) — just add F1, F2 and R, then create two pairs: (F1, R) and (F2, R), each with its own fragment length:

```
[30bp flank] [F1] [gap A] [F2] [gap B] [reverse complement of R] [30bp flank]
```

Fully independent primers (F1/R1 and F2/R2, sharing no primer with each other) — the app checks whether F2/R2 physically fits inside F1/R1's gap (with at least 5bp free on each side). If it fits, it's nested — with the leftover space split evenly on both sides, noted plainly in the result:

```
[30bp flank] [F1] [gap A] [F2] [gap B] [reverse complement of R2] [gap C] [reverse complement of R1] [30bp flank]
```

If it doesn't fit, the app places them one after another instead, with a fixed 30bp gap between the two independent groups:

```
[30bp flank] [F1] [reverse complement of R1] [30bp gap] [F2] [reverse complement of R2] [30bp flank]
```

A few notes:
- **You don't need to list primers in the "correct" order, and you don't need to decide nesting yourself.** If two or more primers share a pair (like one reverse primer shared by two forwards), the app works out their correct left-to-right arrangement from the fragment lengths directly. For independent pairs that share no primer at all, the app checks whether one can physically fit inside a gap of another (with at least 5bp free on each side) and nests it there if so; if nothing fits anywhere, it places them one after another with a fixed 30bp gap between them instead. Either way, you'll see which choice it made and why in the results table.
- Reverse primers are automatically converted to their reverse complement before being placed, since that's the strand they actually bind on the top strand of the finished sequence.
- Your primers are always used exactly as typed — only the gaps and flanks are randomly generated.
- **Every primer must be used in at least one pair** — the app won't let you add a lone forward or reverse primer with nothing to pair it with.
- **Setting the target GC%** — you can either type in a target GC% yourself, or tick "I have a specific target sequence" and paste in the sequence your primers were originally designed against. If you do the latter, the app works out that sequence's own GC% and uses it automatically for the random filler, so your gBlock's overall makeup matches your real target.
- **A compact diagram appears under the sequence** summarising the whole layout at a glance, e.g. `Flanking (30bp) | ITS1F | 77 | ITS1 | 44 | ITS2 | Flanking (30bp)` — primer names alternating with the gap length (in bp) before the next one. The detailed table below it still has the exact sequence for every piece, if you need that.

## Degenerate (ambiguous) bases in primers

Primers can contain IUPAC degenerate codes — R, Y, S, W, K, M, B, D, H, V, N — each representing more than one possible base (e.g. R means "A or G"). Only real IUPAC letters are accepted in a primer sequence; anything else is filtered out as you type.

A gBlock, unlike a primer, has to be one single exact sequence — it can't actually contain a wobble position. So every degenerate base gets resolved down to one real base before the gBlock is built. There are two ways this happens:

- **Automatic (the default)** — the "Automatically substitute degenerate bases" checkbox is on by default. Each degenerate code is resolved using this table, which favours A/T over G/C (since a lower GC content is generally easier to synthesize):

  | Code | Means | Used for gBlock | Code | Means | Used for gBlock |
  |------|-------|------------------|------|-------|------------------|
  | R | A or G | A | B | C, G or T | T |
  | Y | C or T | T | D | A, G or T | A |
  | S | G or C | G | H | A, C or T | A |
  | W | A or T | A | V | A, C or G | A |
  | K | G or T | T | N | any base | A |
  | M | A or C | A | | | |

  This is a reasonable one-size-fits-all default, but it's exactly that — a default. It doesn't know anything about your actual target sequence or the real base distribution in your primer set, so it may not be the right choice for every situation (e.g. if a degenerate position in your primer set isn't really an even split in practice).

- **Manual** — untick the checkbox, and before designing, the app lists every single degenerate position across all your primers individually (not just once per letter — if the same code shows up at different positions, or in different primers, each occurrence gets its own choice), with a dropdown of the real bases that code can mean. You pick the base for each one yourself. This is the better option whenever the automatic A/T-favouring default doesn't reflect your actual target sequence or primer set.

Either way, the **alignment section** shows you exactly what happened: it aligns your *original* primer (degenerate codes and all) against the finished gBlock using IUPAC-aware matching, so a degenerate base is correctly shown as matching wherever the gBlock's chosen base is one of the options that code allows — and lists a plain-language note under the alignment for every position that was substituted, e.g. "Position 4 (5'→3'): R (A/G) was set to A for this gBlock."


You'll need Python installed (3.9 or newer). Then, in a terminal, from inside this folder:

```bash
python3 -m venv venv
source venv/bin/activate        # on Windows, use: venv\Scripts\activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Open the new `.env` file in any text editor if you want to set `NCBI_EMAIL` — this is optional (see the comment in the file for why), so you can leave it blank and everything still works.

## Running it

```bash
python3 backend/app.py
```

Then open your browser to **http://127.0.0.1:5000**

That's it — no accounts, no logins, nothing else to configure.

## A few things worth knowing

- **BLAST takes a while.** This is a real search against NCBI's live database, not a shortcut — it can take anywhere from 30 seconds to a few minutes. The page will keep checking in the background and update itself when it's done; you don't need to keep clicking anything.
- **The complexity check is a simplified copy, not the real IDT tool.** I built it by reading IDT's own published guidance on what causes problems, but IDT's actual screening software is not public, so it may be stricter or catch different things. Always double check on their site before you order — the app links you straight there.
- **The "fix" button can't do the impossible.** If your target GC% is itself close to or past IDT's window limits (below 30% or above 60% for any 100bp stretch), re-rolling the random sequence won't help — every random draw at that target will run into the same wall. In that situation, the app tells you plainly and suggests adjusting your target GC% instead of quietly failing after lots of attempts.
- **Nothing is sent anywhere for the complexity check.** It runs as plain Python code on your own machine.
- **Gaps in the results table aren't labeled or explained inline anymore** — every gap comes from one of three situations: "computed" (pinned down exactly by a pair's fragment length), "nested" (an independent group was fitted inside another one's gap, with any leftover space split evenly, minimum 5bp each side), or "sequential" (two independent groups couldn't be nested, so a fixed 30bp gap was used instead). See "How the sequence is put together" above for the full explanation of when each happens.

## Making it publicly accessible

You can run this locally (above) or put it on the internet so anyone with the link can use it, without needing to install anything themselves. I can't create hosting accounts or actually click "deploy" on your behalf — that part happens on your end — but the app is already set up to make it straightforward. Here's what to know before you do it, then how.

**What changes when it's public, and what's already handled:**

- **No login, open to anyone with the link** — that was your call, and it's the simplest option. The trade-off: everyone's BLAST searches go out under this one app's identity as far as NCBI is concerned. To keep that from becoming a problem:
  - Only 2 BLAST searches run at once; anyone else's search waits its turn rather than piling on. You'll see "Waiting for a free BLAST slot..." if that happens.
  - Finished BLAST results are automatically cleared out after an hour, so memory doesn't slowly fill up over time.
- **Flask's debug mode is off by default now**, and must stay off. It was fine for local development, but it lets anyone who triggers a server error run code on the machine — a serious problem if the server is reachable from the internet. Don't set `FLASK_DEBUG=1` anywhere public.
- **The app must run as a single process** (one "worker"). The BLAST search tracking and the 2-at-a-time limit above both live in that process's memory — if a host runs multiple copies of the app to handle more traffic, those copies wouldn't share that memory, and things would behave inconsistently (a search started on one copy might never be found when you check on it). The `Procfile` (see below) already pins this to one worker, so as long as you don't change that setting on your hosting platform, this isn't something you need to think about further.
- **NCBI_EMAIL is worth setting for a public deployment**, even though it's optional. One person using this locally sends occasional traffic; a public link could plausibly get more use, so giving NCBI a contact is a reasonable courtesy (see `.env.example` for why).

**Deploying to Render (free, no credit card needed):**

Render was chosen here because it deploys straight from a GitHub repo with no server setup on your end. Railway and Fly.io work similarly if you'd rather use one of those instead — the same `Procfile` and environment variables apply, just set up through their dashboards instead.

1. **Put this project on GitHub.** If you don't already have it in a repo: create a new (can be private or public) repository on GitHub, then push this folder to it.
2. **Sign up at [render.com](https://render.com)** (GitHub login is the easiest option) — no credit card required for the free tier.
3. In the Render dashboard, click **New > Web Service**, and connect the GitHub repository you just created.
4. Render should auto-detect Python and find the `Procfile`. If it asks you to fill in commands manually instead, use:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn --chdir backend --workers 1 --threads 8 --timeout 120 --bind 0.0.0.0:$PORT app:app`
5. Under **Environment**, add `NCBI_EMAIL` (optional, your contact email) if you want it. Don't add `FLASK_DEBUG` at all, or set it to `0`.
6. Click **Create Web Service**. The first build takes a few minutes; once it finishes you'll get a live `https://your-app-name.onrender.com` URL.
7. **One quirk of Render's free tier:** the app goes to sleep after 15 minutes with no visitors, and takes about a minute to wake back up on the next request. That's normal, not a bug — the first person to visit after a quiet period just has to wait a bit longer for the page to load.

From then on, pushing new commits to the connected GitHub branch automatically redeploys the app.

- **This can now run either locally or as a shared public site** — pick whichever fits how you're using it.

