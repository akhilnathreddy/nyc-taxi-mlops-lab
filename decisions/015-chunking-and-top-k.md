# 015: Chunks of 256 tokens with no overlap (one chunk per page today), top-k 3

Stage: S6 · Date: 2026-11-22 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

`pipelines/src/labpipes/defs/rag.py`: `CHUNK_MAX_TOKENS = 256`, `CHUNK_OVERLAP_TOKENS = 0`. `app/src/rideapp/assistant.py`: `TOP_K = 3`, the three chunks closest to the question by cosine distance, best first, in the user turn after a fixed system prompt.

## Rejected alternative

128 tokens with 16 of overlap: smaller chunks, so less prompt per chunk, but on this wiki it splits the two longest pages in two (19 chunks instead of 16). A rule and its exception can then land in different chunks, and with top-k 3 one of the halves can lose its place to another page.

## Why

<!-- Draft from the evidence below: rewrite in your own words, as for 004–006. -->

Measured on the wiki (16 published pages, with `labpipes.chunking`):

| | |
| --- | --- |
| Page length (estimated tokens) | 62 to 181, median 91, 1,546 in total |
| Sections per page | 1 (no page has a second heading) |

| Max tokens / overlap | Chunks | Average | Largest | Sections split |
| --- | --- | --- | --- | --- |
| 128 / 0 or 16 | 19 | 88-90 | 133-144 | 2 |
| 256 / 0 (chosen) | 16 | 101 | 188 | 0 |
| 256-512 / any overlap | 16 | 101 | 188 | 0 |

At 256 every page is one chunk, so a chunk is always a whole policy with its title on top, and overlap has nothing to repeat (from 256 up, overlap changes nothing today). 256 rather than 512 keeps a chunk's cost bounded if a page grows: about 11 s of prompt reading per chunk on the LLM host.

Top-k 3 is a latency budget as much as a recall one: three chunks are about 33 s of prompt reading. On the first real question ("How much is the Harbor Line surcharge, and when does it apply?") the right page ranked first at cosine similarity 0.87, the next two at 0.70 and 0.66 (public TLC surcharges, airport fees), and generation took 43 s. The answer ($4.25, trips ending at Pier 76 or the Hudson Yards ferry landing, after the metered fare, not in the ETA, FIN-118) matched the page on every fact. Without the wiki, the same question got "I don't know" and a citation to a page that doesn't exist ("[Harbor Line Surcharge Policy]"): the system prompt stops the model inventing the fee, not inventing a source.

Top-k 2 would save about 11 s, but a question worded far from its page's title (the glossary, the FAQ, the runbook all mention fees and ETAs) can push the right page to third; top-k 4 costs another 11 s for a fourth page that, with 16 short pages, is usually unrelated.

## What would show this was wrong

- A question about a wiki-only policy whose page isn't among the three sources (recall too low for top-k 3), or is there but ranked below unrelated pages.
- A page growing past 256 tokens and getting split (`chunk_tokens_max` or `chunks_total` in `wiki_chunks`' metadata going up): then overlap starts to matter.
- Answers taking longer than the app's 150 s timeout under load.
