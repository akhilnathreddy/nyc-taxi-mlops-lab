"""S6: the RAG branch's pure parts, without RDS, the wiki or the LLM host."""

import dagster as dg
import pytest

from labpipes.chunking import chunk_markdown
from labpipes.defs import rag


def test_unchanged_chunks_keep_their_ids_and_only_the_edit_is_new():
    before = "## Fees\n\nThe Harbor Line surcharge is $4.50.\n\n## Hours\n\nService starts at 06:00."
    after = "## Fees\n\nThe Harbor Line surcharge is $5.00.\n\n## Hours\n\nService starts at 06:00."
    old = [c.content_hash("harbor") for c in chunk_markdown("Harbor Line", before, 200, 0)]
    new = [c.content_hash("harbor") for c in chunk_markdown("Harbor Line", after, 200, 0)]
    add, delete = rag.plan_chunk_changes(set(old), new)
    assert len(add) == 1 and len(delete) == 1  # only the Fees chunk changed
    assert set(new) - set(add) == set(old) - set(delete)  # the Hours chunk keeps its id (and its vector)
    assert rag.plan_chunk_changes(set(new), new) == ([], [])  # re-chunking the same page changes nothing


def test_decisions_fail_closed(monkeypatch):
    monkeypatch.setattr(rag, "CHUNK_MAX_TOKENS", None)
    with pytest.raises(dg.Failure, match="decision 015"):
        rag.chunk_settings()
    monkeypatch.setattr(rag, "VECTOR_INDEX", None)
    with pytest.raises(dg.Failure, match="decision 016"):
        rag.index_sql()
    monkeypatch.setattr(rag, "VECTOR_INDEX", "ivfflat")
    monkeypatch.setattr(rag, "IVFFLAT_LISTS", None)
    with pytest.raises(dg.Failure, match="IVFFLAT_LISTS"):
        rag.index_sql()


def test_index_uses_cosine_distance(monkeypatch):
    monkeypatch.setattr(rag, "VECTOR_INDEX", "hnsw")
    assert "using hnsw (embedding vector_cosine_ops)" in rag.index_sql()
    monkeypatch.setattr(rag, "VECTOR_INDEX", "ivfflat")
    monkeypatch.setattr(rag, "IVFFLAT_LISTS", 10)
    assert "using ivfflat (embedding vector_cosine_ops) with (lists = 10)" in rag.index_sql()


def test_vector_literal_round_trips():
    assert rag.vector_literal([0.5, -1.0, 1e-9]) == "[0.5,-1,1e-09]"


def test_job_and_schedule_cover_the_three_assets():
    defs = dg.Definitions(assets=[rag.wiki_pages, rag.wiki_chunks, rag.wiki_embeddings], asset_checks=[rag.every_chunk_embedded],
                          jobs=[rag.ingest_wiki], schedules=[rag.ingest_wiki_daily],
                          resources={"wiki": rag.WikiApi(), "embed": rag.LlmEmbed(llm_host="x"), "rag": rag.RagStore()})
    nodes = set(defs.get_job_def("ingest_wiki").graph.node_dict)
    assert {"wiki_pages", "wiki_chunks", "wiki_embeddings"} <= nodes
    assert rag.ingest_wiki_daily.job_name == "ingest_wiki"
