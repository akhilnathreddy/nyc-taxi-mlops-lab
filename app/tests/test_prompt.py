"""S6: the prompt keeps a fixed, cacheable prefix, with everything that varies in the user turn."""

import asyncio

import rideapp.assistant as a


def chunk(i: int, title: str = "Harbor Line") -> a.Chunk:
    return a.Chunk(id=f"c{i}", page_id="harbor-line", title=title, content=f"{title} > Fees\n\nexcerpt {i}", score=0.9 - i / 10)


def test_system_prompt_is_the_same_for_every_question():
    m1 = a.build_messages("How much is the surcharge?", [chunk(0), chunk(1)])
    m2 = a.build_messages("When does service start?", [chunk(2, "Hours")])
    assert m1[0] == m2[0] == {"role": "system", "content": a.SYSTEM_PROMPT}
    assert [m["role"] for m in m1] == ["system", "user"]


def test_excerpts_go_in_the_user_turn_best_first_then_the_question():
    user = a.build_messages("How much is the surcharge?", [chunk(0), chunk(1)])[1]["content"]
    assert user.index("excerpt 0") < user.index("excerpt 1") < user.index("Question: How much is the surcharge?")
    assert "[Harbor Line]" in user


def test_no_chunks_is_just_the_question():
    assert a.build_messages("hi", [])[1] == {"role": "user", "content": "hi"}


def test_no_retrieval_until_top_k_is_chosen(monkeypatch):
    monkeypatch.setattr(a, "TOP_K", 0)
    assert asyncio.run(a.retrieve([0.0] * 768)) == []
