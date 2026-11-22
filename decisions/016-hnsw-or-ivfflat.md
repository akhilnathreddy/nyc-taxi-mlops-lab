# 016: IVFFlat with 1 list, built after the vectors exist

Stage: S6 · Date: 2026-11-22 · Author: akhilnathreddy · Drafted by agent: yes

## Choice

`rag.chunks.embedding` gets an IVFFlat index for cosine distance, `using ivfflat (embedding vector_cosine_ops) with (lists = 1)`, created by `wiki_embeddings` after the chunks are embedded (`VECTOR_INDEX = "ivfflat"`, `IVFFLAT_LISTS = 1` in `rag.py`). The app orders by `embedding <=> query`, the operator the index serves.

## Rejected alternative

HNSW: a graph index that can be built on an empty table, keeps its recall as chunks are added and deleted, and gives the best recall for the latency. It costs more memory and a slower build, neither of which matters at 16 rows, so the case against it here is weaker than the case against IVFFlat at scale; expect to defend that.

## Why

<!-- Draft from the evidence below: rewrite in your own words, as for 004–006. -->

IVFFlat clusters the vectors present when the index is created into `lists` groups and, at query time, searches the `ivfflat.probes` closest groups (default 1). pgvector's guidance is `lists = rows / 1000` up to a million rows, at least 1. With 16 chunks that's 1 list, so one probe scans every vector: the search is exact, and the index costs almost nothing to build or keep.

What each needs to build: IVFFlat needs data first (built on an empty table, its clusters mean nothing), so `wiki_embeddings` creates it only after embedding; HNSW can be created up front and is updated as rows arrive.

What happens as the wiki changes: IVFFlat's lists are fixed when it's built. New vectors go into the nearest existing list, so as the wiki drifts from what it was at build time, the lists stop matching the data and recall falls (at more than one list) until the index is rebuilt. `create index if not exists` never rebuilds it, so that's a manual step: drop the index and rerun `ingest_wiki` when the wiki grows by orders of magnitude. HNSW doesn't need that.

At a million chunks: HNSW, if the memory is there (the graph is several GB at 768 dimensions), for recall that holds up as the wiki changes. IVFFlat with about 1,000 lists and tuned probes if memory or build time is the constraint, with a scheduled rebuild.

Measured: `ingest_wiki` run b7e91561 embedded 16 chunks and built the index; the second run embedded 0 and left it as it was. Retrieval for the Harbor Line question took 46 ms, embedding the question included.

## What would show this was wrong

- More than about 1,000 chunks with `lists = 1`: every query is still a full scan; time to raise `lists` and rebuild.
- With more than one list, a question whose page exists but isn't retrieved, and is retrieved after a rebuild: the lists had drifted.
- Needing to rebuild the index after every big wiki change: that's HNSW's argument.
