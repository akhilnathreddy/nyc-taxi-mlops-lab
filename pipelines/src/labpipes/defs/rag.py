"""S6: the wiki RAG branch, in the `rag` database on RDS (pgvector), on a daily schedule.

- wiki_pages: the published pages from the ops wiki (resource `wiki`: labpipes/wiki.py). Store each
  page's ETag and send it next time: an unchanged page then costs a 304 and no body.
- wiki_chunks: split changed pages with labpipes.chunking.chunk_markdown (chunk size and overlap are
  decision 015) and store the chunks; use Chunk.content_hash as the id so unchanged text keeps it.
- wiki_embeddings: embed only the chunks that have no vector yet (resource `embed`: nomic-embed-text,
  768 dimensions) and store them as pgvector `vector(768)`, with an index (HNSW or IVFFlat: decision 016).
- A blocking check that every chunk has a vector, and a schedule (and a job you can run by hand with
  scripts/dagster-run.sh) for the three.
The RDS admin connection comes from the `rag` resource (RagStore.connect); `create extension vector`
works there. Copy asset and check shapes from pipelines/reference/patterns.py.

Tables (schema `rag`):
  pages   one row per published page: its last ETag and body, and which ETag and chunk settings its
          chunks were made from (so a changed page, or changed chunk settings, gets re-chunked).
  chunks  id = Chunk.content_hash(page_id): the same text on the same page keeps its id, and so its
          vector. embedding is NULL until wiki_embeddings fills it.
The app's retrieval (app/src/rideapp/assistant.py) reads rag.chunks joined with rag.pages.
"""

from datetime import datetime, timezone

import dagster as dg

from labpipes.chunking import chunk_markdown
from labpipes.resources import LlmEmbed, RagStore, WikiApi

# Decision 015: chunk size and overlap, in estimated tokens (chunking.estimate_tokens). None fails closed:
# wiki_chunks refuses to run until you've chosen.
CHUNK_MAX_TOKENS: int | None = 256  # every page (62-181 tokens today) is one chunk
CHUNK_OVERLAP_TOKENS: int | None = 0  # nothing is split today, so overlap would only repeat text

# Decision 016: "hnsw" or "ivfflat". None fails closed: wiki_embeddings refuses to build an index.
VECTOR_INDEX: str | None = "ivfflat"
# ivfflat only: how many lists (clusters). pgvector's guidance is rows / 1000 up to 1M rows, at least 1:
# 16 chunks today gives 1, so every query scans every vector (exact). The index is built once, from the
# vectors present at the time; rebuild it (drop it and rerun) when the wiki grows by orders of magnitude.
IVFFLAT_LISTS: int | None = 1

DIMENSIONS = 768  # nomic-embed-text-v1.5; never change without re-embedding every chunk

SCHEMA = f"""
create extension if not exists vector;
create schema if not exists rag;
create table if not exists rag.pages (
    id            text primary key,
    title         text not null,
    updated_at    text not null,
    etag          text not null,
    body          text not null,
    fetched_at    timestamptz not null,
    chunked_etag  text,
    chunked_with  text
);
create table if not exists rag.chunks (
    id         text primary key,
    page_id    text not null references rag.pages (id) on delete cascade,
    idx        integer not null,
    heading    text not null,
    content    text not null,
    tokens     integer not null,
    embedding  vector({DIMENSIONS})
);
create index if not exists chunks_page_id on rag.chunks (page_id);
"""


def chunk_settings() -> str:
    if CHUNK_MAX_TOKENS is None or CHUNK_OVERLAP_TOKENS is None:
        raise dg.Failure("chunk size and overlap aren't chosen yet: set CHUNK_MAX_TOKENS and CHUNK_OVERLAP_TOKENS (decision 015)")
    return f"max={CHUNK_MAX_TOKENS},overlap={CHUNK_OVERLAP_TOKENS}"


def index_sql() -> str:
    """The vector index for cosine distance (the app orders by `embedding <=> query`)."""
    if VECTOR_INDEX == "hnsw":
        return "create index if not exists chunks_embedding_hnsw on rag.chunks using hnsw (embedding vector_cosine_ops)"
    if VECTOR_INDEX == "ivfflat":
        if not IVFFLAT_LISTS or IVFFLAT_LISTS < 1:
            raise dg.Failure("IVFFLAT_LISTS must be a positive number for an ivfflat index (decision 016)")
        return f"create index if not exists chunks_embedding_ivfflat on rag.chunks using ivfflat (embedding vector_cosine_ops) with (lists = {int(IVFFLAT_LISTS)})"
    raise dg.Failure(f"VECTOR_INDEX must be 'hnsw' or 'ivfflat', not {VECTOR_INDEX!r} (decision 016)")


def plan_chunk_changes(stored_ids: set[str], new_ids: list[str]) -> tuple[list[str], list[str]]:
    """Which chunk ids to add and which to delete when a page is re-chunked. Unchanged ids stay (with
    their vectors)."""
    new = set(new_ids)
    return [i for i in new_ids if i not in stored_ids], sorted(stored_ids - new)


def vector_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


@dg.asset(group_name="rag", kinds={"postgres"}, description="The ops wiki's published pages, fetched with conditional GETs.")
def wiki_pages(context: dg.AssetExecutionContext, wiki: WikiApi, rag: RagStore) -> dg.MaterializeResult:
    client = wiki.client()
    refs = client.pages()
    conn = rag.connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(SCHEMA)
            cur.execute("select id, etag from rag.pages")
            stored = dict(cur.fetchall())
        fetched = unchanged = 0
        now = datetime.now(timezone.utc)
        for ref in refs:
            page = client.page(ref.id, stored.get(ref.id))
            if page is None:  # 304: same ETag, no body
                unchanged += 1
                continue
            fetched += 1
            with conn, conn.cursor() as cur:
                cur.execute(
                    "insert into rag.pages (id, title, updated_at, etag, body, fetched_at) values (%s, %s, %s, %s, %s, %s) "
                    "on conflict (id) do update set title = excluded.title, updated_at = excluded.updated_at, "
                    "etag = excluded.etag, body = excluded.body, fetched_at = excluded.fetched_at",
                    (page.id, page.title, page.updated_at, page.etag, page.body, now),
                )
        removed = sorted(set(stored) - {r.id for r in refs})
        if removed:  # unpublished: its chunks go with it (on delete cascade)
            with conn, conn.cursor() as cur:
                cur.execute("delete from rag.pages where id = any(%s)", (removed,))
    finally:
        conn.close()
    context.log.info(f"{len(refs)} pages listed: {fetched} fetched, {unchanged} unchanged (304), {len(removed)} removed")
    return dg.MaterializeResult(metadata={
        "pages_listed": dg.MetadataValue.int(len(refs)),
        "pages_fetched": dg.MetadataValue.int(fetched),
        "pages_unchanged": dg.MetadataValue.int(unchanged),
        "pages_removed": dg.MetadataValue.int(len(removed)),
    })


@dg.asset(group_name="rag", kinds={"postgres"}, deps=[wiki_pages],
          description="Chunks of the pages that changed (or whose chunk settings changed), ids by content hash.")
def wiki_chunks(context: dg.AssetExecutionContext, rag: RagStore) -> dg.MaterializeResult:
    settings = chunk_settings()
    conn = rag.connect()
    pages_chunked = added = deleted = 0
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "select id, title, body, etag from rag.pages "
                "where chunked_etag is distinct from etag or chunked_with is distinct from %s",
                (settings,),
            )
            todo = cur.fetchall()
        for page_id, title, body, etag in todo:
            chunks = chunk_markdown(title, body, CHUNK_MAX_TOKENS, CHUNK_OVERLAP_TOKENS)
            by_id = {c.content_hash(page_id): c for c in chunks}
            with conn, conn.cursor() as cur:  # one transaction per page
                cur.execute("select id from rag.chunks where page_id = %s", (page_id,))
                to_add, to_delete = plan_chunk_changes({r[0] for r in cur.fetchall()}, list(by_id))
                if to_delete:
                    cur.execute("delete from rag.chunks where id = any(%s)", (to_delete,))
                for cid in to_add:
                    c = by_id[cid]
                    cur.execute(
                        "insert into rag.chunks (id, page_id, idx, heading, content, tokens) values (%s, %s, %s, %s, %s, %s) "
                        "on conflict (id) do nothing",
                        (cid, page_id, c.index, c.heading, c.text, c.tokens),
                    )
                # Kept chunks may have moved within the page.
                for cid, c in by_id.items():
                    cur.execute("update rag.chunks set idx = %s where id = %s and idx <> %s", (c.index, cid, c.index))
                cur.execute("update rag.pages set chunked_etag = %s, chunked_with = %s where id = %s", (etag, settings, page_id))
            pages_chunked += 1
            added += len(to_add)
            deleted += len(to_delete)
        with conn, conn.cursor() as cur:
            cur.execute("select count(*), coalesce(max(tokens), 0), coalesce(round(avg(tokens)), 0) from rag.chunks")
            total, max_tokens, avg_tokens = cur.fetchone()
    finally:
        conn.close()
    context.log.info(f"{pages_chunked} pages chunked ({settings}): {added} chunks added, {deleted} removed, {total} in total")
    return dg.MaterializeResult(metadata={
        "chunk_settings": dg.MetadataValue.text(settings),
        "pages_chunked": dg.MetadataValue.int(pages_chunked),
        "chunks_added": dg.MetadataValue.int(added),
        "chunks_removed": dg.MetadataValue.int(deleted),
        "chunks_total": dg.MetadataValue.int(int(total)),
        "chunk_tokens_max": dg.MetadataValue.int(int(max_tokens)),
        "chunk_tokens_avg": dg.MetadataValue.int(int(avg_tokens)),
    })


@dg.asset(group_name="rag", kinds={"postgres"}, deps=[wiki_chunks],
          description="Vectors for the chunks that don't have one yet (nomic-embed-text, 768 dimensions), and the vector index.")
def wiki_embeddings(context: dg.AssetExecutionContext, embed: LlmEmbed, rag: RagStore) -> dg.MaterializeResult:
    create_index = index_sql()  # fail before embedding anything if decision 016 isn't made
    conn = rag.connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("select id, content from rag.chunks where embedding is null order by page_id, idx")
            todo = cur.fetchall()
        embedded = 0
        for i in range(0, len(todo), embed.batch):
            batch = todo[i : i + embed.batch]
            vectors = embed.embed_documents([content for _, content in batch])  # adds "search_document: "
            with conn, conn.cursor() as cur:
                for (cid, _), v in zip(batch, vectors, strict=True):
                    cur.execute("update rag.chunks set embedding = %s::vector where id = %s", (vector_literal(v), cid))
            embedded += len(batch)
        with conn, conn.cursor() as cur:
            cur.execute(create_index)
            cur.execute("select count(*), count(embedding) from rag.chunks")
            total, with_vector = cur.fetchone()
    finally:
        conn.close()
    context.log.info(f"{embedded} chunks embedded; {with_vector} of {total} have a vector")
    return dg.MaterializeResult(metadata={
        "chunks_embedded": dg.MetadataValue.int(embedded),
        "chunks_with_vector": dg.MetadataValue.int(int(with_vector)),
        "chunks_total": dg.MetadataValue.int(int(total)),
        "index": dg.MetadataValue.text(VECTOR_INDEX or "none"),
    })


@dg.asset_check(asset=wiki_embeddings, blocking=True, description="Every chunk has a vector, and there is at least one chunk.")
def every_chunk_embedded(context: dg.AssetCheckExecutionContext, rag: RagStore) -> dg.AssetCheckResult:
    conn = rag.connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("select count(*), count(*) filter (where embedding is null) from rag.chunks")
            total, missing = cur.fetchone()
    finally:
        conn.close()
    return dg.AssetCheckResult(
        passed=int(total) > 0 and int(missing) == 0,
        severity=dg.AssetCheckSeverity.ERROR,
        description=f"{missing} of {total} chunks without a vector",
        metadata={"chunks_total": dg.MetadataValue.int(int(total)), "chunks_missing_vector": dg.MetadataValue.int(int(missing))},
    )


ingest_wiki = dg.define_asset_job(
    "ingest_wiki",
    selection=dg.AssetSelection.assets(wiki_pages, wiki_chunks, wiki_embeddings),
    description="Fetch changed wiki pages, chunk them, embed the new chunks (S6).",
)

# Daily at 05:00 UTC (10:30 IST): inside the lab session, after the morning restore (S4), because the
# hosts only run while a Learner Lab session is up. Change it if your sessions run at other times.
ingest_wiki_daily = dg.ScheduleDefinition(job=ingest_wiki, cron_schedule="0 5 * * *", execution_timezone="UTC",
                                          default_status=dg.DefaultScheduleStatus.RUNNING)
