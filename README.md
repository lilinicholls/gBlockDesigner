# gBlock Designer

1. **Designs a gBlock** from named primers arranged into pairs. You tell it the amplicon length for each pair, and it automatically calculates every gap between primers. Supports simple forward + reverse pairs or more complex layouts such as nested primer pairs.
2. **Checks the primers line up correctly** against the sequence it built, with a clear side-by-side diagram.
3. **Runs a BLAST search** against NCBI's database, to see if your new sequence accidentally matches something that already exists.
4. **Runs a local complexity check** based on the criteria laid out in IDT's ordering tool. 

https://gblockdesigner.onrender.com/

## How the sequence is generated: 

Start by entering your **primer** name (e.g. "F1"), direction (Forward/Reverse), and its sequence for all primers. 

Select **primer pairs** by selecting a forward and a reverse primer from the list above, and enter that specific pair's fragment length. 

Fragment length here means the sequence strictly *between* that pair's own two primers. If a different primer happens to sit physically in between (like a second forward primer nested inside), that other primer's length counts towards the fragment length, since it's part of what's actually in between. A primer can be reused across multiple pairs just by picking it again for shared-primer sets.

One pair:
```
[30bp flank] [F1] [gap, worked out automatically] [reverse complement of R1] [30bp flank]
```
Two forward primers sharing one reverse primer:
```
[30bp flank] [F1] [gap A] [F2] [gap B] [reverse complement of R] [30bp flank]
```
Fully independent primer sets. 
```
[30bp flank] [F1] [gap A] [F2] [gap B] [reverse complement of R2] [gap C] [reverse complement of R1] [30bp flank]
```
For independent steps, the app checks whether F2/R2 physically fits inside F1/R1's gap (with at least 5bp free on each side). If it fits, it's nested. If it doesn't fit, the app places them one after another instead, with a fixed 30bp gap between the two independent groups:
```
[30bp flank] [F1] [reverse complement of R1] [30bp gap] [F2] [reverse complement of R2] [30bp flank]
```


A few notes:
- If two or more primers share a pair (like one reverse primer shared by two forwards), the app works out their correct left-to-right arrangement from the fragment lengths directly.
- For independent pairs that share no primer at all, the app checks whether one can physically fit inside a gap of another (with at least 5bp free on each side) and nests it there if so. If nothing fits anywhere, it places them one after another with a fixed 30bp gap between them instead. Either way, you'll see which choice it made and why in the results table.
- Reverse primers are automatically converted to their reverse complement before being placed, since that's the strand they actually bind to the top strand of the finished sequence.
- **Every primer must be used in at least one pair** and the app won't let you add a lone forward or reverse primer with nothing to pair it with.

### Setting the target GC%

You can either type in a target % yourself, or select "I have a specific target sequence" and paste in the target sequence your primers were originally designed for. If you do put in a target sequence, the app calculates that sequence's GC% and automatically uses it for the random filler, so your gBlock's overall makeup matches your real target.

### Degenerate bases in primers

Primers can contain IUPAC degenerate codes: R, Y, S, W, K, M, B, D, H, V, N 

A gBlock cannot have degenerate bases; it has to be one sequence. Each degenerate base is replaced with a single base before the gBlock is built. There are two ways this happens:

- **Automatic**
The "Automatically substitute degenerate bases" checkbox is on by default. Each degenerate code is resolved using this table, which favours A/T over G/C (since a lower GC content is generally easier to synthesise):

  | Code | Means | Used for gBlock | Code | Means | Used for gBlock |
  |------|-------|------------------|------|-------|------------------|
  | R | A or G | A | B | C, G or T | T |
  | Y | C or T | T | D | A, G or T | A |
  | S | G or C | G | H | A, C or T | A |
  | W | A or T | A | V | A, C or G | A |
  | K | G or T | T | N | any base | A |
  | M | A or C | A | | | |

However, this may not be the most suitable substitution for your  target sequence or the real base distribution in your primer set. If this is the case, you can manually set what to change the base to.

- **Manual**
Untick the checkbox to see the list of all degenerate positions for each primer individually (not just once per letter). Use the dropdown to pick the base for each one. 

All degenerate base substitutions are shown in the **alignment section**. 



### A few other notes 

- **BLAST takes a while.** This is a real search against NCBI's live database, so it can take anywhere from 30 seconds to a few minutes. The page will keep checking in the background and update itself when it's done; you don't need to keep clicking anything.
- **The complexity check is a simplified copy, not the real IDT tool.** It was built by reading IDT's own published guidance on what causes problems, but IDT's actual screening software is not public, so it may be stricter or catch different things. Always double-check on their site before you order. The step for this has a link to the IDT site. 
- **The "fix" button can't do the impossible.** If your target GC% is itself close to or past IDT's window limits (below 30% or above 60% for any 100bp stretch), re-generating the random sequence won't help. In that situation, the app tells you plainly and suggests adjusting your target GC%, rather than quietly failing after many attempts.



## Running the Program Locally 
You'll need Python installed (3.9 or newer). Then, in a terminal, from inside this folder:

```bash
python3 -m venv venv
source venv/bin/activate        # on Windows, use: venv\Scripts\activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Open the new `.env` file in any text editor if you want to set `NCBI_EMAIL` — this is optional (see the comment in the file for why), so you can leave it blank and everything still works.

### Running it

```bash
python3 backend/app.py
```

Then open your browser to **http://127.0.0.1:5000**
