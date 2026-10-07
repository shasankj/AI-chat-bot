# Care Bot Workbook

**Concepts, strategies, problems, and interview preparation for a RAG + MCP + LangGraph application**

This workbook explains every idea we used to build Care Bot, *why* we chose it over the alternatives, the
problems we hit, how we fixed them, what we would do next, and how to talk about all of it in a senior AI
engineering interview. Everything here is grounded in the real project: file names are real, and every number
(hit rates, distances, test counts) was measured on this codebase, not quoted from a blog.

---

## How to use this workbook

| If you want to… | Read |
|---|---|
| Explain the project in 90 seconds | Part 1 |
| Understand a concept deeply (RAG, pgvector, MCP, LangGraph, guardrails…) | Part 2 |
| See why each decision was made, and the alternatives | Part 3 |
| Learn from the bugs and dead ends | Part 4 |
| See the measurements | Part 5 |
| Know what to build next and how | Part 6 |
| Practice answers for interviews | Part 7 |
| Look up a term | Part 8 |
| Deepen your skills with hands-on labs | Part 9 |

Each concept in Part 2 follows the same shape: **What it is → Why it exists → How we used it → What to watch for →
Questions you may be asked.** Read the questions first, try answering aloud, then read the explanation.

**A note on honesty.** Interviewers at senior level respect candidates who say "this was a trade-off, here is what
we measured, here is what it does not do." Part 4 and the "limitations" notes are as important as the successes.
Several things we believed at first turned out wrong (the retrieval distance threshold is *not* a security control;
keyword OR-search made retrieval *worse*; one of our own regex rules blocked 30 real documents). Those stories are
your best interview material.

---

# Part 1. The project in one page

## 1.1 The 90-second pitch

> "Care Bot is an insurance and pharmacy assistant. It answers from three sources: Medicare coverage PDFs and FDA
> drug labels through retrieval-augmented generation on Postgres with pgvector, and a patient's exact records
> through an MCP server with four read-only tools. A LangGraph agent routes each question, runs retrieval and
> tool calls in parallel, and drafts an answer with Claude Haiku. The interesting part is safety: the model is
> wrapped by four layers that are enforced in code, not in prompts: an input guard, fencing of untrusted text, a
> strict prompt, and an output verifier that rejects any answer without a valid citation or with a number that is
> not in the sources. It says 'I don't know' when evidence is missing, never gives medical advice, and identity
> comes from a signed cookie so the model can never choose whose records to read. I measured retrieval quality
> instead of guessing: hybrid search beat vector-only, metadata filtering fixed cross-document leakage, and I wrote
> adversarial tests that found real holes."

## 1.2 What it does, concretely

* **Coverage questions** ("What is prior authorization?") → hybrid RAG over 4 CMS/Medicare PDFs → cited answer.
* **Record questions** ("What is my copay for Ozempic?") → MCP tools over PostgreSQL → cited answer.
* **Drug-information questions** ("What are the side effects of lisinopril?") → RAG restricted to that drug's FDA
  label → label text quoted, with a fixed "not medical advice" notice.
* **Everything else** → fixed refusals ("I'm an AI, not a doctor, consult a doctor or pharmacist"; "I don't know";
  emergency redirect to 911/988) or a safe error message.
* Four roles (guest, patient, pharmacist, admin) with enforced tool allowlists and an append-only audit trail.

## 1.3 The numbers worth memorizing

| Fact | Value |
|---|---|
| Corpus | 4 Medicare PDFs (about 900 chunks) + 13 FDA labels (720 pages, about 1,900 chunks) |
| Embedding model | `BAAI/bge-base-en-v1.5`, 768 dimensions, local ONNX (`fastembed`) |
| Relational data | 4 plans, 13 drugs, 52 coverage rows, 8 patients, 16 prescriptions (synthetic) |
| LLM | Claude Haiku 4.5, `temperature=0`, three small calls per turn (gate, planner, answer) |
| Retrieval, coverage questions (20-question set) | hit@1 **17/20**, hit@5 **18/20** (hybrid) vs 16/20, 17/20 (vector only) |
| Retrieval, FDA labels (19-question set) | hit@5 **19/19**, hit@3 17/19, hit@1 12/19; name-less queries: right-drug share **6% → 100%** with the drug filter |
| Distance gate | `MAX_DISTANCE = 0.47`; in-scope best matches 0.18–0.44, out-of-scope 0.49–0.65 |
| Refusals | about 0.1 s, zero model calls |
| Typical answer latency | 2–6 s (records), up to ~8 s on the first request after startup |
| Guard recall on *fresh* attacks | 6 of 8 (the regex layer is a speed bump, not a wall) |
| Live end-to-end evaluation | **37 of 37** cases behaved as expected (after several rounds of fixes) |
| Tests | **221** backend + 15 frontend, plus a scripted real-Chrome run |

## 1.4 Architecture in words

A React app talks to FastAPI over REST plus one Server-Sent-Events endpoint. FastAPI runs a LangGraph state
machine. The graph's first node is deterministic code (input guard). Its second is a cheap LLM classifier (gate).
Then documents and tools are fetched in parallel, the retrieved text is fenced as untrusted data, a strict prompt
produces a draft, and a code verifier accepts or rejects the draft. Postgres holds both the relational data and
the vectors, so one database serves SQL joins, vector search, keyword search, and the audit log.

---

# Part 2. Concepts in depth

## 2.1 Why LLM applications need more than a prompt

**What goes wrong when you just call an LLM**

| Failure | What it looks like here | Our counter-measure |
|---|---|---|
| **Hallucination** | Invents a copay, a policy rule, a citation | Evidence-only prompt + code verifier + "I don't know" path |
| **Stale/closed knowledge** | Doesn't know *your* plan or *this* patient | RAG and MCP supply the facts at question time |
| **Prompt injection** | "Ignore your rules…" in the user message, or hidden inside a PDF | Layered guards, fencing, stricter-only gate |
| **Over-permission** | Model asked to fetch someone else's record | Identity from session; model never sees an id parameter |
| **Unsafe advice** | Gives dosing or diagnosis | Refusal in code; dosing refused even from labels |
| **Cost and abuse** | Long inputs, floods of requests | Length caps, rate limits, concurrency cap, `max_tokens` |

**The key mental model:** a prompt is a *request* the model may ignore; code around the model is a *guarantee*.
Production safety comes from the second.

**Interview questions**
* *"How do you stop an LLM from hallucinating in a regulated domain?"* Ground it (RAG/tools), require citations,
  verify claims in code against the sources, and give it a safe way to say "I don't know". Measure it.
* *"Why not just tell the model not to give medical advice?"* Because instructions can be overridden or ignored;
  we refuse in deterministic code before the model runs, and again verify afterwards.

## 2.2 Retrieval-Augmented Generation (RAG) end to end

**What it is.** Instead of asking the model to remember facts, you *retrieve* relevant text at question time and
give it to the model as the only allowed evidence. The model becomes a reader and writer, not a memory.

**The pipeline (we built every stage)**

```
OFFLINE (ingestion)                                  ONLINE (every question)
download PDF → extract text per page                 question → embed question
   → clean → chunk → embed each chunk                   → search (vector + keyword) with filters
   → store (text, page, vector, tsvector)               → distance gate → fence → prompt → answer → verify
```

**Why each stage matters (and where it fails)**

| Stage | What can go wrong | Our experience |
|---|---|---|
| Extraction | Page numbers, headers, hyphen breaks, other-language pages pollute text | 78 chunks began with their own page number; fixed |
| Chunking | Too big = blurry vector; too small = no context; cut sentences = broken facts | Sentence-aligned ~1000 chars with sentence overlap |
| Embedding | Wrong model/prefix, or different models for docs vs queries | Same module for both; BGE query prefix via `query_embed` |
| Retrieval | Misses exact terms, returns near-duplicates, wrong document | Hybrid + metadata filters |
| Generation | Ignores sources, mixes in memory, invents numbers | Strict prompt + output verifier |
| Evaluation | "Looks fine" is not a metric | hit@k test sets, live end-to-end cases |

**Interview questions**
* *"Walk me through your RAG pipeline."* (Use the diagram above, then name one failure at each stage.)
* *"How do you know retrieval is good?"* A labelled set of questions with a phrase the right passage must
  contain; report hit@k; compare variants (we compared vector-only vs hybrid vs OR/AND keyword variants).
* *"RAG vs fine-tuning?"* RAG for facts that change or must be cited; fine-tuning for style/format/skills. We needed
  citations and updatable documents, so RAG.

## 2.3 Embeddings

**What they are.** A model maps text to a vector (here 768 numbers) so that texts with similar *meaning* point in
similar directions. Search becomes geometry: find the stored vectors nearest the question's vector.

**Cosine distance vs similarity.** pgvector's `<=>` is **cosine distance** = `1 − cosine similarity`.
`0` = same direction, about `0.3–0.5` = clearly related, above about `0.6` = probably unrelated (for this model and
corpus). BGE models output normalized vectors, so cosine and inner product rank identically. (We verified this on our own model: the vector norm is exactly 1.0000 and cosine similarity equals the dot product.)

**Choosing a model and dimension.** We chose `bge-base-en-v1.5` (768 dimensions, 210 MB) over `bge-small`
(384 dimensions, 67 MB). The trade-off is a few benchmark points of quality against about 3× compute and storage.
Dimensions matter less than the model's quality and your chunking; we decided to **measure instead of argue**.
(Interview-worthy: *the vector column's size is fixed, so changing models later means re-embedding everything*.)

**Details that matter**
* **Query vs passage prefix.** BGE was trained so questions get a short instruction prefix and documents do not.
  `fastembed` exposes `query_embed` and `passage_embed`; using the right one is a free accuracy gain.
* **One model for both sides.** Vectors from different models live in different spaces and cannot be compared.
  That is why `app/rag/embeddings.py` serves both ingestion and retrieval.
* **Local vs API embeddings.** Local = no per-call cost, no data leaving the machine (relevant for health data),
  but you manage the model. Anthropic has no embeddings API, so this was also the practical choice.
* **Environment lesson.** `torch` has no wheel for Intel Macs, so `sentence-transformers` was impossible;
  `fastembed` (ONNX Runtime) installed cleanly. Know your constraints before picking a library.

**Interview questions**
* *"How would you choose an embedding model?"* Evaluate candidates on *your* data with a small labelled set;
  consider dimension (storage/latency), max tokens, language, license, hosting, and domain fit.
* *"What happens if you change the embedding model?"* New column or table, re-embed everything, rebuild the index.
* *"Why can cosine distance be a poor relevance threshold?"* Distances are relative to the model and corpus, off-topic
  text can still be "close" if it shares vocabulary, so you calibrate on real examples (we did) and keep other defenses.

## 2.4 Chunking

**What it is.** Splitting documents into pieces small enough to embed meaningfully and to fit several into a prompt.

**Strategies compared**

| Strategy | Idea | Pros | Cons |
|---|---|---|---|
| Fixed-size characters/tokens | Cut every N | Trivial | Cuts sentences and tables |
| Recursive splitter | Try paragraphs, then sentences, then words | Common default | Still structure-blind |
| **Sentence-aligned + overlap (ours)** | Pack whole sentences to ~1000 chars; repeat trailing sentences | Never breaks a sentence; readable | Ignores headings |
| Semantic chunking | Split where embedding similarity drops | Topic-coherent | Slow, extra tuning |
| Heading-aware / hierarchical | Use document structure; attach the section title | Best citations and context | Needs structure extraction |
| Parent-child ("small to big") | Embed small chunks, return the parent | Precision + context | More machinery |

**Our choices and why**
* **Per page**, never across a page boundary → every chunk has an exact page number, so citations can say "p. 53".
* **~1000 characters (about 170 words)** → big enough for context, small enough to be about one idea.
* **Overlap by whole trailing sentences (≤200 chars)** → a fact straddling two chunks still appears complete in one,
  and chunks start at sentence starts. (Our first version used a character slice and started chunks mid-word.)
* **Cleaning is part of chunking**: drop page-number-only lines at page edges, strip revision stamps like
  `(Rev. 18, Issued: 01-15-16…)`, drop mostly non-Latin pages, and keep line-end hyphens.

**The defects we found by *looking at the data*:** 78 chunks started with their own page number; 82 contained
repeated revision stamps; Arabic and Armenian text from a language-assistance page was being embedded; and our own
"rejoin hyphenated words" rule was *creating* broken words (`cost-⏎sharing` → `costsharing`). We fixed each and
wrote a regression test for each. **Lesson: read your chunks.** Embeddings of garbage retrieve garbage.

**Interview questions**
* *"How did you pick chunk size?"* Started at 1000 characters, inspected real chunks, measured retrieval hit@k;
  I'd tune size/overlap against the eval set (Part 9 lab).
* *"What would you do for tables or scanned PDFs?"* Table-aware extraction (e.g., layout-based parsers) and OCR for
  scans; flag extraction failures instead of silently embedding nothing (our ingest does flag "no extractable text").
* *"What is contextual retrieval?"* Prepend a short, model-written description of where a chunk sits in the document
  before embedding it. A cheap, effective upgrade (Part 6).

## 2.5 pgvector and approximate nearest-neighbor search

**What it is.** A Postgres extension adding a `vector(N)` type, distance operators, and ANN indexes. Using Postgres
means one database for relational facts, vectors, keyword search, and audit, with transactions and SQL joins.

**Operators**

| Operator | Meaning | Use when |
|---|---|---|
| `<=>` | cosine distance | text embeddings (ours) |
| `<->` | Euclidean (L2) | some image/other embeddings |
| `<#>` | negative inner product | normalized vectors, speed |

The index must match the operator class: we built `USING hnsw (embedding vector_cosine_ops)`; a query using a
different operator would not use it.

**HNSW vs IVFFlat**

| | HNSW (ours) | IVFFlat |
|---|---|---|
| Structure | Layered proximity graph | Clusters (lists) |
| Build | Slower, more memory | Faster, needs data present first |
| Recall/speed | Better recall, fast queries | Needs tuning (`lists`, `probes`) |
| Key params | `m`, `ef_construction` (build), `ef_search` (query) | `lists`, `probes` |

**Approximate means approximate.** HNSW trades a little recall for speed. We saw this directly: rewriting a table
(adding a generated column) rebuilt the index and shifted one result from rank 3 to rank 1. For a corpus this small
(thousands of chunks) exact search would also be fast. We use HNSW because it is the realistic production choice
and teaches the right concepts.

**The filtered-ANN pitfall (important!).** An HNSW index finds its nearest ~`ef_search` (default 40) vectors *first*
and applies the `WHERE` clause *afterwards*. If your filter is selective (one drug's label is about 100 of 4,800 chunks),
almost none of those 40 candidates pass, and you get far fewer rows than requested. pgvector 0.8 added
**iterative scan** (`SET hnsw.iterative_scan = relaxed_order`), which keeps walking the graph until enough rows pass.
We set it per query with `SET LOCAL` (transaction-scoped, allowed on our read-only session), together with `hnsw.ef_search = 100` and wrote a test that
a selective filter with an unrelated query still returns `k` rows.

**Interview questions**
* *"HNSW or IVFFlat, and why?"* HNSW for recall and no training step; IVFFlat when build time/memory dominate.
* *"What is `ef_search`?"* The size of the candidate list during search; higher = better recall, slower.
* *"What goes wrong with filtered vector search?"* Post-filtering starves results; fix with iterative scan, a
  partial index, partitioning by the filter column, or a pre-filter + exact search when the filtered set is small.
* *"When would you leave Postgres for a dedicated vector DB?"* Hundreds of millions of vectors, very high QPS, or
  needing features Postgres lacks; until then, one transactional store is simpler and cheaper.

## 2.6 Hybrid search and Reciprocal Rank Fusion

**The problem.** Embeddings capture meaning but blur exact tokens (acronyms like `TrOOP`, drug names, `tier 3`,
dollar amounts). Keyword search is the reverse: exact, but blind to paraphrase.

**Postgres full-text search.** A `tsvector` is preprocessed text (lower-cased, stop words removed, words stemmed).
We store it as a **generated column** (`GENERATED ALWAYS AS (to_tsvector('english', content)) STORED`) so ingestion
code never has to maintain it, and index it with **GIN** (an inverted index: word → chunks).

**Reciprocal Rank Fusion.** Run both searches, then score each chunk `Σ 1/(60 + rank)` across the lists it appears
in. A chunk that ranks well in both rises. RRF needs **no score normalization**, which is why it is the default
(cosine distance and keyword rank live on different scales).

**What we measured, including our own mistake**
* First attempt: OR the question's words in the keyword query. **Result: worse.** hit@1 fell to 13/20 (vector-only
  was 16/20) because common words ("part", "drug") flooded the list and `ts_rank_cd` has no IDF weighting.
* Switched to **AND** (`plainto_tsquery`): precise for distinctive terms, and when nothing matches the list is empty
  so retrieval falls back to pure vector. Result: **17/20**, a modest win (one question), not a miracle.
* We also predicted hybrid would fix a missed "$615" deductible. **Wrong:** keyword search matches terms *in the
  question*, and "615" is in the answer, not the question. Hybrid helps when the question contains the rare term.

**Interview questions**
* *"Why hybrid?"* Different failure modes; fuse them; measure whether it helps on your data.
* *"Why RRF rather than a weighted score sum?"* Scores aren't comparable across retrievers; ranks are.
* *"BM25 vs Postgres `ts_rank`?"* BM25 weights term rarity (IDF) and length; `ts_rank_cd` doesn't. For serious
  keyword search consider `pg_search`/ParadeDB or a search engine; for this scale Postgres FTS is adequate.

## 2.7 Metadata filtering, multiple corpora, and the relevance gate

**Two corpora, one table.** Medicare rules and FDA labels live in the same chunk table. Without separation, a
question about "prior authorization" could retrieve label text, and a question about lisinopril could retrieve
another drug's label. We added `category` (`coverage_policy` / `drug_label`) and `drug_id` to the *source* row and
filter inside the SQL (`JOIN … WHERE s.category = … AND s.drug_id = ANY(…)`).

**Why a metadata filter beats "hoping the embedding helps".** The filter is exact and cheap; it makes whole classes
of error impossible (wrong document, wrong drug) and shrinks the candidate set.

**The relevance gate.** After retrieval we drop chunks whose cosine distance exceeds `MAX_DISTANCE = 0.47`. If
nothing survives, the answer model is never called and the user gets "I don't know". We **calibrated** the value:
in-scope best matches ranged 0.18–0.44, clearly off-topic questions 0.49–0.65, so 0.47 sits in the gap.

**Hard truth we measured.** The gap is thin (0.04) and pharmacy-flavoured but unanswerable questions ("Which
cholesterol medication works best?") scored 0.29–0.44, *inside* the threshold. And of 11 attack prompts that evaded
the regex layer, 10 still passed the gate. **The distance gate detects off-topic text, not unsafe intent.** That
is why safety lives in separate layers.

**Interview questions**
* *"How do you decide a retrieved passage is relevant enough?"* A calibrated distance threshold plus an LLM/verifier
  check, and a refusal path. Never rely on the threshold alone.
* *"How do you prevent cross-document leakage?"* Metadata filters in the query, not in the prompt.

## 2.8 Retrieval upgrades we did *not* use (know when you would)

| Technique | What it does | Would add it when… |
|---|---|---|
| **Cross-encoder reranking** | A second model scores (question, passage) pairs jointly and reorders the top 20–50 | Recall@20 is high but precision@5 is low (relevant text is retrieved but ranked poorly) |
| **Query rewriting** | LLM rewrites the question | We already do this: follow-ups become standalone questions (re-screened before use) |
| **Multi-query retrieval** (**we use it**) | Split a compound question into focused sub-queries, search each, fuse with RRF | One embedding of "advantages AND side effects" matched neither topic well; see 2.8b |
| **HyDE** | Embed a *hypothetical answer* instead of the question | Questions and documents use very different vocabulary |
| **Contextual retrieval** | Prepend a model-written situating sentence to each chunk before embedding | Chunks lose meaning out of context (pronouns, "the above table") |
| **Parent-child retrieval** | Search small chunks, return the larger parent | You need precision *and* context |
| **Semantic cache** | Reuse answers to near-identical questions | High traffic with repetitive questions (not for patient-specific answers) |

Say this in an interview: *"I measured first. Hybrid gave a small gain, filters fixed leakage. The next measured
bottleneck would tell me whether to add a reranker or contextual retrieval, I wouldn't add them speculatively."*

## 2.8b Multi-query retrieval and drug-information mode (worked example)

**The user's question that started this feature:** *"what are the advantages and side effects of Linsinopril?"*

1. **Typo-tolerant drug resolution (plain code).** `resolve_drugs()` matches names and brands against our 13-drug catalog,
   exactly first, then fuzzy (`difflib`, cutoff 0.82, ignoring words under 5 letters), so "Linsinopril" → lisinopril and
   "ibuprofen" → *nothing*. It is deterministic on purpose: it decides which label we may search, so an LLM must not.
2. **Three conditions must all hold** to enter drug mode (the "stricter-only" principle): the input guard saw a general,
   non-personal, info-shaped question; the LLM gate agrees; and a catalog drug was named. Any failure falls back to a
   refusal ("not a doctor") or "I don't know" (unknown drug), never to a looser path.
3. **Metadata-filtered retrieval:** `category = 'drug_label'` and `drug_id = ANY(...)` inside the SQL, plus iterative scan.
4. **Multi-query:** the gate returns up to 3 focused queries ("what is lisinopril used for", "lisinopril side effects").
   Each is **re-screened by the input guard** (model output is untrusted), the original standalone question is always kept,
   all run in parallel, and results are fused with RRF (so a chunk found by several queries rises).
5. **A different system prompt:** summarize the label, neutral voice, no "you", no advice, no dosing, quote numbers exactly.
6. **Fixed notice added by code**, and echoed disclaimers the model pasted inside its answer are stripped so each
   fixed message appears exactly once.

**Why this design is defensible to an interviewer:** information is *quoted from a published document with page
citations*, never generated from the model's memory; the line between information and advice is drawn in code with
tests on both sides; and every relaxation is paired with a control (personal wording, dosing, overdose, unknown drug,
too many drugs all refuse).

**Concepts to be able to explain:** compound-query failure of single embeddings · RRF across *queries* (not only across
retrievers) · re-screening model-generated queries · fuzzy matching vs LLM entity linking · information vs advice.

## 2.9 The Model Context Protocol (MCP)

**What it is.** An open protocol that standardizes how an AI application discovers and calls *tools* (and reads
*resources*, and uses *prompts*) exposed by separate servers. A server advertises tools with names, descriptions
and JSON schemas; a client lists them; the LLM chooses; the client executes and returns results.

**Why not just write Python functions and use function calling?** You can, and for one app it's simpler. MCP earns its
keep when tools are *shared across applications*, written in another language, deployed separately, or when you want
a clean **trust boundary** between "the thing the model drives" and "the thing that touches your data". In Care Bot
the MCP server is a separate process with its own validation and the only SQL in the system.

**Transports.** *stdio*: the client launches the server as a child process and talks over stdin/stdout (ours;
simple, local, no network exposure). *Streamable HTTP*: a networked server (needs real authentication; the MCP
server trusts its caller). **Never `print()` in a stdio server**: stdout *is* the protocol channel.

**Our tools (all read-only, all fixed SQL):** `get_patient_profile`, `list_prescriptions`, `get_drug_coverage`,
`get_plan_details`. No free-form SQL tool exists. Inputs are validated with strict regexes *and* bound as parameters.

**Things we learned the hard way**
* **MCP SDK v2 renamed things** (`FastMCP` → `MCPServer`). We inspected the installed package instead of writing
  from memory. Always check the installed version.
* **Error semantics.** Raise `ToolError` for *anticipated* failures: the message reaches the model and the user.
  Any *other* exception is treated as a crash: the client sees only a generic "Error executing tool X" and the
  traceback stays in server logs (this prevents leaking connection strings). We map validation errors to `ToolError`.
* **The trust boundary lives in the client gateway.** `McpGateway` (a) hides the `member_id` parameter from the model,
  (b) *overwrites* it with the session's patient, (c) only exposes the tools the caller's role may use, and
  (d) re-checks the allowlist on every call even if the model asks for a tool it was never shown.
* **Tool output format affects other layers.** Our output verifier checks `$` amounts by looking for `$5.00` in the
  sources, so tools return money as formatted strings. Raw `5.0` would have made every correct answer look hallucinated.

**Interview questions**
* *"MCP vs function calling vs plugins?"* Function calling is the model API feature; MCP is an interoperability and
  deployment protocol around tools; plugins are vendor-specific. MCP's value is decoupling and reuse.
* *"How do you secure an MCP server?"* Least privilege (read-only DB role), validated inputs, fixed queries,
  authenticate callers if networked, authorize *per role in the client gateway*, audit, and never let the model supply identity.
* *"What are tool annotations?"* Hints (`readOnlyHint`, `destructiveHint`) for clients/UIs; **not** enforcement.
  Real enforcement is the database role.

## 2.10 Agents and LangGraph

**What it is.** LangGraph models an agent as a **graph**: nodes are functions that read and update a shared
`state`; edges (possibly conditional) decide what runs next. Compared with one giant prompt or a free-form
"agent loop", each step is separately testable, and **guards sit between LLM calls where the model cannot skip them**.

**Concepts we used**

| Concept | Where | Why |
|---|---|---|
| **State** (`TypedDict`) | `agent/state.py` | One typed place for everything a turn needs |
| **Reducer** (`Annotated[list, append_history]`) | `history` | Appends and trims instead of overwriting |
| **Conditional edges** | after `input_guard`, `gate`, `build_context` | Route to refusals, retrieval, tools, or the answer |
| **Parallel branches** | `retrieve` ‖ `plan_tools` | Returning a *list* of nodes runs them in the same superstep; `build_context` waits for both |
| **Checkpointer** (`InMemorySaver`) | memory | Conversation state per `thread_id` |
| **Custom stream writer** | `emit(...)` | Progress events for the UI without breaking the graph |
| **Dependency injection** | `build_graph(gateway, llm_factory, retriever)` | Tests swap in fakes |

**Our graph:** `input_guard → gate → (retrieve ‖ plan_tools) → build_context → answer → output_guard → finalize`,
with early exits to `finalize` for refusals and "no evidence".

**Design decisions worth explaining**
1. **Three small LLM calls** (gate, planner, answer) rather than one big one: each has a narrow job, can use a cheap
   model, and the gate sees *only the user's words* so retrieved text cannot steer routing.
2. **Memory on the server, keyed by role + patient + conversation id**, never trusting client-supplied history
   (a forged "assistant" message is an injection vector). Switching patient starts a fresh memory by construction.
3. **Only verified answers and screened questions enter memory**, citations and footers stripped.
4. **The gate is told who is signed in, from the server.** An `<account role=… patient_in_scope=…/>` tag is built from the
   signed session (never from user text), so "their prescriptions" from a pharmacist is recognized as a record lookup
   instead of being refused as medical advice. A user-typed lookalike tag is itself refused as an injection.
5. **Progress streams; tokens do not.** Because the output must be verified *before* the user sees it, streaming raw
   tokens would show text we might have to retract.

**Bugs that teach**
* Nodes receive `config` **only if the parameter is typed `RunnableConfig`**; a `dict` annotation silently meant
  "no config" and crashed the tool node. (The runner's error path made it obvious.)
* With a checkpointer, **state persists across turns**: last turn's `final` would leak into this turn unless the
  runner resets per-turn keys (`fresh_turn`).
* Per-turn lists written by parallel nodes must use *different keys* (`doc_items`, `tool_items`) to avoid conflicts.
* **Structured output from a model can omit fields.** For an off-topic question the model skipped a "required" field and a
  strict Pydantic schema turned that into a user-facing error. Require only what the decision needs (`intent`); default the rest.

**Interview questions**
* *"Why LangGraph over a plain loop or LangChain agents?"* Explicit control flow, typed state, checkpointing,
  parallelism, and inspectability. Safety-critical flows should not be left to a free-form loop.
* *"How do you do human-in-the-loop or retries in LangGraph?"* Interrupts/checkpoints and conditional edges back to a node.
* *"How would you persist memory across restarts?"* A Postgres-backed checkpointer saver with the same `thread_id` scheme.

## 2.11 Guardrails and prompt-injection defense

**Threat model first.** Attackers can speak to the model directly (**direct injection**) or hide instructions in
content the model reads (**indirect injection**, e.g., inside a PDF or a database field). They may want to change
behavior, extract the system prompt, read other users' data, get unsafe advice, or exfiltrate data.

**Defense in depth: four layers, each assuming the previous can fail**

| Layer | Mechanism | Strength | Weakness |
|---|---|---|---|
| 1. Input guard (code) | Unicode normalization, invisible-character stripping, language check, pattern rules for emergency / injection / advice | Deterministic, free, instant | Misses novel phrasing |
| 2. Fencing (code) | Retrieved text wrapped as `<untrusted_document>`, `<`/`>` escaped, injection-like passages dropped | Stops tag break-out and obvious indirect injection | Subtle injections |
| 3. System prompt | Evidence-only, cite everything, no advice, data ≠ instructions | Handles nuance | It's a request, not a guarantee |
| 4. Output guard (code) | Valid citations, `$`/`%` grounded, approved links only, canary check, fixed disclaimer | Catches what slipped through | Only checks what it can check |

**Principles to name in an interview**
* **Fail closed.** Any verification failure returns a canned safe reply, never the model's raw text.
* **Stricter-only gate.** The LLM classifier can *add* refusals; it can never grant what code denied. Drug-information
  mode requires *all* of: layer 1 saw a general info question, the gate agrees, and a catalog drug was named.
* **Least privilege everywhere.** Read-only DB role + read-only session + statement timeout; INSERT-only audit table;
  per-role tool allowlists.
* **The model has no dangerous capability to hijack.** Even a fully jailbroken model can only produce text, which the
  verifier then rejects if uncited or ungrounded.
* **Canary token.** A random string in the system prompt; if it ever appears in output we know the prompt leaked.
* **Privacy by design.** The audit log stores question *length and an 8-character hash*, never the text.

**What we measured (honestly)**
* Regex recall on attacks we hadn't written patterns for: **1 of 12**. After adding generic patterns and testing on
  **8 brand-new attacks** (the first 12 were "contaminated" by our looking at them): **6 of 8**.
* A too-broad pattern flagged **30 of 898** real policy chunks and would have blocked "Can you tell me if my doctor
  accepts my plan?". We tightened it, then added those as permanent tests. **Always test false positives on real data.**
* The retrieval distance gate stopped only **1 of 11** attacks that evaded layer 1, so it is *not* a security control.

**Medical-safety design.** Three categories: *emergency* (redirect to 911/988, because "consult a doctor" is the
wrong answer), *advice* (always refused with the fixed "I'm an AI, not a doctor" text), and *drug information*
(general facts quoted from an FDA label, never personalized, never dosing). Personal wording ("will **I** get…",
"**my** medication") flips a label question into advice. Dosing is refused even though labels contain it.

**Interview questions**
* *"How do you defend against indirect prompt injection?"* Treat all retrieved/tool text as untrusted data: delimit
  and escape it, screen it, keep the model's capabilities minimal, verify outputs, and never let content change
  permissions.
* *"Are regex guardrails enough?"* No, and we measured that. They are layer one of several; use ML classifiers
  (e.g., Prompt Guard-style models) and verification for depth.
* *"How do you evaluate guardrails?"* Adversarial test sets (kept *separate* from the examples used to write rules),
  false-positive tests on real data, and tracking block reasons in production.

## 2.12 Authentication, sessions, RBAC, CSRF, CORS

* **Signed session cookie.** A JWT (HS256) with `role`, `subject`, `exp`, stored in an **HttpOnly** cookie (JavaScript
  can't read it, which limits XSS damage) with **SameSite=Lax** (not attached to cross-site POSTs, which blocks CSRF).
  Tampering invalidates the signature. We tested wrong key, expired, `alg: none`, invented role, and edited payloads.
* **Why a cookie, not `localStorage`?** `localStorage` is readable by any script on the page; HttpOnly is not.
* **CSRF defense in depth.** SameSite=Lax **plus** an `Origin` allow-list check on state-changing requests.
* **CORS.** We proxy `/api` through Vite so the browser sees one origin (no preflights, cookies just work); the
  server still allows only the dev origin with credentials.
* **RBAC.** Roles map to a **tool allowlist** (`ROLE_TOOLS`) and a scope (`subject` patient). The `Access` object is
  frozen and created *only* from the signed session. The LLM, request bodies, and the UI dropdown cannot influence it.
* **The dropdown is a simulated login.** The server turns "sign in as Maria" into a signed cookie; everything after
  that is decided from the cookie. Real systems replace this screen with OIDC/SSO and nothing downstream changes.
* **Request models use `extra="forbid"`**, so `{"question": "...", "member_id": "SUM-200002"}` is rejected (422).

**Interview questions**
* *"How would you do real auth?"* OIDC with an identity provider, short-lived access tokens, server-side session or
  refresh rotation, MFA; keep the same `Access` abstraction.
* *"JWT pitfalls?"* Algorithm confusion (`none`), weak secrets, no expiry, storing tokens in `localStorage`, no revocation
  (mitigate with short TTLs or a server-side session store).

## 2.13 API design: REST, SSE, WebSockets, rate limiting

| | REST only | **SSE (ours)** | WebSocket |
|---|---|---|---|
| Direction | request → response | server → client stream | both ways, persistent |
| Fits one-way progress streams | No live status | **Yes** | Overkill |
| Runs on | HTTP | HTTP | upgraded protocol |
| Reconnect / proxies / auth | trivial | easy | you build it; needs Origin checks |

* **SSE wire format:** `event: name` + `data: {json}` + blank line; lines starting with `:` are comments.
  Browsers' `EventSource` can only `GET` with no body, so the app uses `fetch()` and reads the response stream,
  then a small incremental parser handles events split across network chunks.
* **Disconnects.** The server's generator has a `finally:` that runs on completion, error *and* client abort: it
  releases the concurrency slot and writes the audit row.
* **Rate limiting.** In-memory sliding window (per IP and per session) → `429` with `Retry-After`. **Limit:** per
  process; use Redis for multiple instances. **Load shedding:** a hard cap of 8 concurrent turns → `503`.
* **Error shape.** Every failure is `{"error": "..."}`; validation errors report *where and why* but never echo the
  offending input; unexpected errors are redacted (URLs, keys, passwords) and capped.

**Interview questions**
* *"SSE or WebSockets for an LLM chat?"* SSE when the flow is request→stream; WebSockets when the client must send
  while receiving (voice, collaboration). We stream *progress* because output verification precedes display.
* *"Token bucket vs sliding window?"* Token bucket allows bursts at a steady refill; sliding window is stricter and
  simpler to reason about. Either needs shared storage across instances.

## 2.14 Frontend concepts that mattered

* **Event-sourcing the message.** The chat message is a *pure reducer* `(message, event) → message`, unit-tested.
  Subtlety: `tools` and `retrieve` run **in parallel** on the server, so the UI can't finish the previous stage when
  the next starts; each stage has its own completion signal.
* **Auto-scroll that doesn't fight the user.** Our first version read its own smooth-scroll animation as "the user
  scrolled away" and stopped following, hiding the end of a fast reply. Fix: `ResizeObserver` + instant pinning, and
  re-pin on every new message. (Found only by driving a real browser.)
* **Safe rendering.** `react-markdown` never renders raw HTML; citations are swapped in as components, not HTML strings.
* **Honest errors in the UI.** A dead backend shows an actionable message with a retry button, not an infinite spinner.
* **Accessibility basics.** Labels on controls, `aria-live` for streaming status, focus styles, keyboard send,
  reduced-motion respect.

## 2.15 Testing LLM applications

**The pyramid we used**

| Level | What | Cost | Examples |
|---|---|---|---|
| Unit (pure code) | chunker, parser, reducer, guards, resolver | free | 110+ guardrail cases, SSE parser split mid-event |
| Integration (real DB, fake LLM) | every graph branch, MCP tools, API, auth attacks | free | "gate says medical → no retrieval, no answer-model call" |
| Retrieval evaluation | hit@k, vector vs hybrid, filtered vs unfiltered | embeddings only | `tests/eval_retrieval.py`, `eval_labels.py` |
| Live end-to-end | the real model on realistic and hostile questions | cents | `tests/eval_agent.py` (22 cases) |
| Real-browser run | Chrome via DevTools Protocol, screenshots | cents | sign in, ask, refuse, switch role, mobile |

**Techniques**
* **Dependency injection + fakes** so most behavior (including "the model must *not* be called here") is asserted
  deterministically.
* **Assert negatives**: no patient data in the prompt, no retrieval for unknown drugs, no model call on refusals.
* **Don't grade your own homework.** The 12 attacks we looked at became a contaminated set; we wrote 8 new ones to
  measure recall honestly. Likewise, when two retrieval tests "failed" we checked whether the *test* was wrong
  (it was: the 2026 out-of-pocket cap is `$2,100`, not `$2,000`) before touching the code.
* **Measure false positives** on real data (0 of 898 chunks flagged after the fix).
* **Live evals are smoke tests, not benchmarks**: 22 cases show the design works, not that it is unbreakable.

**Interview questions**
* *"How do you test something non-deterministic?"* Make everything around the model deterministic (DI, fakes, `temperature=0`),
  test the model-dependent parts with labelled sets and thresholds, and track metrics over time.
* *"What would you monitor in production?"* Outcome mix (answered/refused/blocked), block reasons, latency per stage,
  retrieval distances, user feedback, cost per turn, error rates, audit anomalies.

---

# Part 3. Strategy decision records

Each record: **what we chose, what else we considered, why, what it costs, and the evidence.** In an interview,
being able to say *"the alternative was X; I chose Y because…; the trade-off is…"* is what separates senior answers.

| # | Decision | Alternatives | Why we chose it | Trade-off / cost | Evidence |
|---|---|---|---|---|---|
| D1 | **PostgreSQL + pgvector** for vectors *and* relational data | Pinecone / Weaviate / Qdrant / OpenSearch | One transactional store: SQL joins, vectors, full-text, audit, backups; no second system to secure | Not built for billions of vectors | Whole system runs on one DB with three roles |
| D2 | **Direct SQL retrieval** (`<=>`, tsvector, RRF, filters) | LangChain `PGVector` wrapper (original spec) | The wrapper can't express hybrid RRF, metadata joins to a sources table, iterative scan, or our relevance gate | More code we own; LangChain-agnostic | `app/rag/retriever.py` |
| D3 | **Local embeddings**, `bge-base-en-v1.5` (768-d) | `bge-small` (384-d), OpenAI/Voyage API, bigger models | No per-call cost, health text stays local, strong retrieval quality; Anthropic has no embeddings API | ~3× compute/storage vs small; model management | Chose 768 after weighing; measured retrieval afterward |
| D4 | **Sentence-aligned chunks (~1000 chars), per page, sentence overlap** | Fixed windows, recursive, semantic, heading-aware | Readable chunks, exact page numbers for citations, simple and testable | Ignores headings (a known upgrade) | 78 → 1 page-number-led chunks after cleaning |
| D5 | **HNSW, `vector_cosine_ops`** | IVFFlat, exact scan | Best recall/latency without training; the realistic production choice | Approximate; memory; slower build | Results shifted slightly after an index rebuild |
| D6 | **Hybrid search, RRF, keyword AND** | Vector only; weighted sum; keyword OR | Different failure modes; ranks (not scores) are comparable | Small gain on our data; more SQL | hit@1: 17/20 vs 16/20 (vector); OR was 13/20 |
| D7 | **Calibrated distance gate (0.47)** | No gate; LLM-only relevance judgment | Detects "no evidence" cheaply so the answer model is never called | Thin margin; not a safety control | in-scope ≤0.44, off-topic ≥0.49 |
| D8 | **Metadata filters** (`category`, `drug_id`) | Prompt-level "only use the lisinopril label" | Exact, enforced in SQL, shrinks the candidate set | Requires a sources table with metadata | Tests: label queries return only that label |
| D9 | **pgvector iterative scan** | Raise `ef_search`; partial indexes; partition | Fixes filtered-ANN starvation with one setting | Slightly slower filtered queries | Test: selective filter still returns `k` rows |
| D10 | **MCP server + gateway** for patient data | In-process Python tools | Separate process, single place for SQL, clean trust boundary, protocol reuse | More moving parts (child process) | Real stdio subprocess test passes |
| D11 | **No free-form SQL tool**; four fixed tools | "Text-to-SQL" | The model cannot write arbitrary queries; tiny attack surface | Less flexible | SQL-injection attempts rejected, tables unchanged |
| D12 | **LangGraph state machine** | Single prompt; ReAct loop | Guards sit *between* LLM calls; parallel branches; typed state; testable | Learning curve | 40+ branch tests with fake LLMs |
| D13 | **Three small Haiku calls** (gate, planner, answer) | One large call | Narrow jobs; the gate sees only user text; low cost | Extra latency (~1 s per call) | Typical answer 2–6 s |
| D14 | **Stricter-only LLM gate** | Trust the classifier | A model can add refusals but never grant permission code denied | Occasional over-refusal | Drug mode needs layer 1 + gate + catalog drug |
| D15 | **Output verifier, fail closed** (`$` strict, `%` number-only) | Trust the prompt | Catches uncited, invented, or leaking drafts | Strict: blocks derived math | Live eval blocked uncited drafts; label tables needed `%` relaxation |
| D16 | **Fencing + drop injection-like passages** | Pass text raw | Indirect-injection defense | A clever injection may pass | 0/898 false positives after tuning |
| D17 | **REST + SSE; stream progress, not tokens** | WebSockets; token streaming | One-way stream fits; verified-before-shown | No typewriter effect | Live timeline in UI |
| D18 | **HttpOnly signed cookie** | `localStorage` JWT | XSS can't read it; SameSite blocks CSRF | Needs CSRF thinking; cookie logistics | Forged/expired/`alg:none` all 401 |
| D19 | **Server-side memory** keyed `role:patient:conversation` | Client sends history | A client can't forge assistant turns or read another patient's memory | In-memory (lost on restart) | Memory isolation test |
| D20 | **Four roles; admin sees no PHI in chat** | Admin sees everything | Least privilege; "admin ≠ omniscient" | Admin can't debug via chat | Role-isolation API tests |
| D21 | **Append-only audit; hash, not text**; fail-open | Log questions; fail closed | Privacy by design; availability for a demo | Fail-open is wrong for real PHI | `UPDATE` blocked by grants |
| D22 | **Drug-information mode** (labels, quoted, never personal) | Refuse all medical content | Shows RAG over a second corpus; useful and safer than advice | Information vs advice is a blurry line | Personal/dosing refused; unknown drug → "I don't know" |
| D23 | **Claude Haiku 4.5** | Sonnet/Opus | Cost and latency; the system's guards reduce reliance on model strength | Weaker reasoning on hard cases | 22/22 live cases |
| D24 | **Vite proxy** for `/api` | CORS + credentials config | One origin: no preflights, cookie "just works" | Dev-only; prod needs a reverse proxy | Works end to end in Chrome |
| D25 | **In-memory rate limiter/counters** | Redis | No extra infra for a demo | Per-process only | Documented limitation |
| D26 | **Numbered idempotent SQL migrations** run in one transaction with `--dry-run` | ORM auto-migrations; Alembic | Readable, reviewable history; safe re-runs; easy to learn from | Manual ordering | 001–008 committed and re-runnable |
| D27 | **Multi-query retrieval** (gate proposes ≤3 sub-queries, each re-screened; fused with RRF) | Single query; always increase `k` | Compound questions blur one embedding; sub-queries keep each topic | More parallel searches (cheap); sub-queries are model output so need screening | User's question now returns the real adverse reactions |
| D28 | **Gate schema requires only `intent`** | All fields required | Models omit fields they judge irrelevant; strictness caused user-visible errors | Defaults must be safe | 30/33 → 33/33 live cases |
| D29 | **Trustworthy account context for the gate** (`<account role patient_in_scope/>` from the session) and a **fixed refusal** for questions about other people | Let the model guess; free-form refusals | Resolves ambiguous pronouns safely; one clear message instead of confusing prose | A forged tag is possible, so the input guard refuses it | Pharmacist flow fixed; other-person replies consistent; no data leaked in any run |

---

# Part 4. Problems we faced and how we overcame them

Format: **Symptom → Root cause → Fix → Lesson.** These are your "tell me about a hard bug" stories.

## 4.1 Environment and setup

1. **`pip install` failed compiling `cryptography` (Rust).** Intel Mac; the newest release had no prebuilt wheel.
   *Fix:* `--only-binary=cryptography` so pip picks the newest version that has a wheel. *Lesson:* read the error's
   root (a native build) and constrain resolution instead of installing a toolchain.
2. **`torch` not installable.** No Intel-Mac wheels. *Fix:* `fastembed` (ONNX Runtime). *Lesson:* check platform
   constraints before choosing a library.
3. **`SSL: CERTIFICATE_VERIFY_FAILED` from system Python.** python.org installs may lack the CA bundle. *Fix:* use the
   venv's `httpx` (bundles `certifi`). *Lesson:* use the project environment for everything.
4. **"No tables" in the database.** Roles saw an empty `public` schema; the other project's tables lived in
   `healthbot`, and neither role could create schemas. *Fix:* reuse `healthbot`, prefix our tables `hc_`, use
   `IF NOT EXISTS` everywhere. *Lesson:* inspect before you create; never touch what you don't own.

## 4.2 Database

5. **Postgres couldn't infer the type of a `NULL` parameter** (`$1 IS NULL`). *Fix:* `CAST(:sid AS int)`.
   *Lesson:* a bare `NULL` in a prepared statement has no type.
6. **A permission probe seemed to leave a row behind.** Actually the `UPDATE` check failed inside the same transaction
   and rolled back the `INSERT`. *Lesson:* verify, then clean up; transactions roll back as a unit.
7. **Misleading script output.** `run_sql` tried to print the "last result", but multi-statement scripts return only the
   first statement's result. *Fix:* removed the claim; added a separate count check. *Lesson:* don't comment what you
   haven't verified.

## 4.3 Ingestion and chunking

8. **Dirty chunks.** 78 began with their own page number, 82 repeated a revision stamp, Arabic/Armenian text was
   embedded. *Root cause:* extraction output taken at face value. *Fix:* edge-only page-number stripping, stamp
   removal, non-Latin filtering at page and chunk level, regression tests. *Lesson:* **read your chunks.**
9. **We created broken words ourselves.** Rejoining `cost-⏎sharing` into `costsharing`. Real line-end hyphens in these
   PDFs are almost always real hyphens (`non-formulary`, URLs). *Fix:* keep the hyphen. *Lesson:* a "cleaning" rule is
   a hypothesis; measure it on the real text.
10. **Picking FDA labels.** The brand label for metformin doesn't exist on DailyMed; the first metformin label I chose
    was **extended-release** (patients take immediate-release); `Prilosec` returned only the OTC drug-facts label; a
    ProAir HFA search found nothing from Teva. *Fix:* verified each candidate's title and first page, switched to an
    IR generic, a generic omeprazole labeler, and Teva's albuterol HFA. *Lesson:* never trust a search result's name;
    open the document.

## 4.4 Retrieval

11. **Two "failing" retrieval tests were wrong, not the system.** The 2026 Part D out-of-pocket cap is `$2,100`, not
    `$2,000`; "formulary exception" was too literal for a consumer-wording answer. We investigated before touching code.
    *Lesson:* when a test fails, first ask whether the test is right.
12. **Hybrid made things worse.** OR-ing keywords: hit@1 13/20 vs 16/20 vector-only. *Root cause:* common words
    dominate without IDF weighting. *Fix:* AND semantics with fallback to vector. *Lesson:* every "improvement" needs a
    before/after number.
13. **A wrong prediction.** We said hybrid would fix a missing "$615" answer. It didn't, because the number was in the
    answer, not the question. *Lesson:* understand *what* each retriever matches on.
14. **Approximate results moved.** After a table rewrite rebuilt the HNSW index, one question's rank changed. *Lesson:*
    ANN is approximate; don't treat exact ranks as stable.
15. **The distance gate isn't a security control.** 10 of 11 evasive attacks passed it. *Fix:* treat it as relevance
    only; rely on other layers for safety.
16. **Filtered ANN starvation** (anticipated from pgvector docs, then tested): selective `WHERE` after an HNSW scan can
    return too few rows. *Fix:* iterative scan per query, plus a test.

## 4.5 Guardrails

17. **Regex recall was poor on new attacks (1 of 12).** *Fix:* generic patterns, then evaluated on **8 fresh** attacks
    (6 of 8). *Lesson:* once you've looked at a test set, it's training data. Keep a held-out set.
18. **A rule was too broad.** A "you … doctor" role-play pattern flagged 30 real chunks and would have refused "Can you
    tell me if my doctor accepts my plan?". *Fix:* require an *assignment* ("you're a physician", "act as my pharmacist").
    Measured 0/898 afterwards. *Lesson:* test guards against real, benign text.
19. **Information vs advice.** The original spec ("never consult as a doctor") conflicted with a reasonable question
    ("what are the side effects of lisinopril?"). We split the intents: general label facts allowed (RAG over
    labels), personal/dosing/diagnosis refused. *Fix included* personal-wording detection and ignoring polite "tell me".
20. **Keyword "info-shaped" could misroute coverage questions** ("warnings about prior authorization", "pharmacy
    benefits"). *Design fix:* info-shaped is only a *flag*; drug mode requires a catalog drug **and** the gate's
    agreement, and the reverse case (gate says in-scope) simply continues as a coverage question.

## 4.6 MCP

21. **The SDK API had changed** (MCP 2.x). `FastMCP` → `MCPServer`. *Fix:* read the installed package.
22. **Our helpful validation messages were masked** as "Error executing tool X". *Root cause:* only `ToolError` is
    surfaced; other exceptions are treated as crashes. *Fix:* raise `ToolError` for anticipated failures.
23. **Layers interacting.** Tools returned `5.0`; the output verifier looks for `$5.00`, so correct answers looked
    hallucinated. *Fix:* tools return formatted money; added a cross-layer test. *Lesson:* test the seams between
    components, not only the components.

## 4.7 Agent and API

24. **`config` never arrived in a node.** LangGraph injects it only if typed `RunnableConfig`. *Lesson:* framework
    magic keys off annotations.
25. **Turn-to-turn state leakage.** A checkpointer persists everything; last turn's `final` would reappear. *Fix:*
    `fresh_turn` resets per-turn keys; test asserts it.
26. **Muddled "unknown drug" reply** (canned "I don't know" plus an explanation). *Fix:* tell the model that a tool
    result saying "not found" *is* evidence and should be stated plainly.
27. **Asking for another patient's records ended in "I don't know".** Safe (nothing leaked), but unhelpful: the output
    guard blocked an uncited reply. We left the guard strict and noted a UX improvement (a specific refusal).
28. **`Ctrl+C` didn't stop the launcher in a test.** Background jobs from a non-interactive shell ignore SIGINT; the
    launcher itself was fine (SIGTERM cleanup left nothing running). *Lesson:* a failing test can be a test-harness issue.

## 4.8 Frontend and tooling

29. **"503 proxy error" on every call.** The backend wasn't running; Vite reports a dead proxy target as a gateway
    error, and the landing page spun forever because we swallowed the error. *Fix:* actionable message with retry,
    `./dev.sh`, and tests for the message. *Lesson:* design the failure state, not just the success state.
30. **Scroll bug found only in a real browser.** Our "stay at bottom" logic misread its own smooth-scroll as the user
    scrolling away. *Fix:* `ResizeObserver` + instant pinning. *Lesson:* some bugs only exist in a browser; automate one.
31. **Browser-automation gotchas.** CSS `text-transform: uppercase` changes `innerText`; headless Chrome follows the OS
    dark theme; a persisted cookie skipped the sign-in screen; Chrome took longer to start than our wait loop.
32. **Lint caught real smells.** `setState` inside an effect (derive the tab instead), unstable hook dependencies.

## 4.9 Drug-information mode

33. **FDA tables print `3.5` under a `(%)` header, not `3.5%`.** Our `%` grounding check would have blocked correct
    quotes. *Fix:* percentages are grounded if the *number* appears anywhere in the sources (invented numbers still blocked).
34. **Ingestion is CPU-bound** (~60 chunks/minute for 1,900 chunks). *Fix:* ran in the background while building the
    rest; ingestion is idempotent and commits per document.

35. **Filtering "did nothing" in our own evaluation.** Unfiltered, category-only and drug-filtered scored identically
    (every question already named the drug). *Fix:* we stopped claiming it improved ranking, then measured the scenarios where
    it must matter: name-less queries (**6% → 100%** right-drug share) and coverage questions polluted by label text (3/100
    passages). *Lesson:* report the measurement you got, then test the claim you believe separately.
36. **A cited, safe answer that was still poor.** The compound question retrieved pharmacology and overdosage passages, not
    the adverse-reactions section. *Root cause:* one embedding for two topics. *Fix:* multi-query retrieval with RRF.
37. **Stacked disclaimers.** The model pasted our refusal sentence inside a longer answer; code then added the notice and
    footer, giving three. *Fix:* strip echoed fixed messages and add each exactly once in code.
38. **"Does lisinopril cause hair loss?" was refused.** A legitimate label question the info patterns didn't cover.
    *Fix:* add "does/can X cause Y" (still refused when personal: "my cough").
39. **A regression caused by a prompt edit.** Adding the sub-query instructions made the model omit `needs_policy_docs` on
    off-topic questions; the strict schema raised `ValidationError` (3 live cases went from pass to error). *Fix:* only `intent`
    required; safe defaults. *Lesson:* **re-run the live evaluation after every prompt change.**
40. **A flaky test from real concurrency.** Sub-queries run in parallel threads, so a fake retriever recorded them in a random
    order and `assert queries == [...]` failed only sometimes (and only in the full run). *Fix:* assert on sorted values; the
    production fusion is deterministic because `asyncio.gather` returns results in input order. *Lesson:* never assert the order
    of a concurrent operation.
41. **An evaluation script broke because the UI changed.** The browser script waited for "a `<details>` element" to mean "the
    answer is ready"; the new grouped sidebar added its own `<details>`. *Fix:* scope the selector to the chat area.
42. **Wrong-looking label choices.** See problem 10: verify the document, not the search result's name.
43. **A documented sample question didn't work.** While verifying the README's examples against the live system, a pharmacist
    with no patient selected asking "What are their prescriptions?" was refused as *medical advice*. *Root cause:* without
    context the gate resolved ambiguity toward refusal (the stricter-only rule doing exactly what we built it to do, on the wrong
    input). *Fix:* tell the gate the role and whether a patient is in scope (from the signed session); refuse a user-typed fake
    `<account/>` tag; add live regression cases. *Lesson:* **test your documentation**: every example you publish is a claim.
44. **I introduced a silent control-character bug.** A patch script wrote `\b` inside a normal Python string, which became a
    *backspace character* instead of the regex word boundary, so a whole injection pattern stopped matching. Tests caught it
    (5 failures) and a `SyntaxWarning` pointed at it. *Fix:* restore `\b`, scan all source files for stray control characters.
    *Lesson:* use raw strings for regexes, and treat warnings as signals.
45. **"LEAKED Okafor" in the live evaluation.** A privacy check failed, so we investigated before anything else: no data of
    James's appeared; the refusal merely repeated the name from the question. *But* the wording ("the data I retrieved is for a
    *different patient*") was confusing. *Fix:* a fixed `OTHER_PERSON` refusal, and the evaluation now checks for the other
    patient's *data* (his drug and plan), not his name. *Lesson:* make the assertion match the real harm.
46. **Classification varies between runs even at `temperature=0`.** "Show me Maria's prescriptions" (as admin) was `access` in
    one run and `injection` in another. Both are safe refusals. *Lesson:* assert on the *set* of acceptable safe outcomes plus
    "nothing leaked", not on one exact label.

---

# Part 5. The evidence: everything we measured

All numbers below were produced by scripts in this repository (`backend/tests/`). Re-run them yourself; if a number
changes, your data or model changed. **Quote these in interviews, and always say what the sample size was.**

## 5.1 Retrieval over the coverage documents (20 questions)

14 questions about concepts ("What is step therapy?") plus 6 whose wording contains a rare term (`TrOOP`, `HPMS`, `P&T`,
`DUR`, `LIS`, "Selected Drug Subsidy"). A hit means the top-k contains a passage with a phrase we know is right.

| Setup | hit@1 | hit@3 | hit@5 |
|---|---|---|---|
| Vector only | 16/20 | 17/20 | 17/20 |
| Hybrid, keyword **OR** | 13/20 | 16/20 | 17/20 |
| Hybrid, keyword OR, half weight | 13/20 | 17/20 | 17/20 |
| **Hybrid, keyword AND (shipped)** | **17/20** | **18/20** | **18/20** |

Reading it: the first hybrid attempt was *worse* than vector-only at the top rank; requiring all keywords fixed it. The
gain over vector-only is one question: modest, so claim it modestly. Two questions never hit: both are about numbers
that live inside long passages about other topics (a known weakness of dense retrieval).

## 5.2 The distance gate (relevance threshold)

| Group | Nearest-passage cosine distance |
|---|---|
| In-scope questions (20) | 0.177 – 0.442 |
| Clearly off-topic (6) | 0.489 – 0.651 |
| Pharmacy-flavoured but not in the PDFs (5) | 0.285 – 0.436 |
| **Chosen gate** | **0.47** |

The gap between in- and out-of-scope is only 0.047, and the "pharmacy-flavoured" group sits *inside* the threshold. Of 11
adversarial prompts that evaded the regex layer, 10 still passed the gate. **The gate measures topical similarity, not
safety.**

## 5.3 Retrieval over the FDA labels (19 questions)

13 labels, 720 pages, **1,931 chunks**. Questions cover uses, side effects, warnings, boxed warnings and mechanism.

| Setup | hit@1 | hit@3 | hit@5 | Share of top-5 from the right drug |
|---|---|---|---|---|
| A. Unfiltered | 12/19 | 17/19 | 19/19 | 100% |
| B. Category filter | 12/19 | 17/19 | 19/19 | 100% |
| C. Category + drug filter (shipped) | 12/19 | 17/19 | 19/19 | 100% |

**Surprise:** filtering changed nothing *on this set*, because every question contains the drug's name and the search
finds the right label by itself. We did not claim otherwise; we tested the scenarios where filtering should matter:

| Scenario | Without drug filter | With drug filter |
|---|---|---|
| **Name-less queries** ("What are the warnings?" after a follow-up rewrite): share of top-5 from the right label | **6%** | **100%** |
| **Coverage questions, no category filter**: label text in the top-5 | 3 of 100 passages (2 of 20 questions) | 0 |

So: filtering is a *guarantee*, not a ranking improvement, and its value shows when the query lacks the name.
Nearest label passages were close (0.136 – 0.298), well inside the 0.47 gate. Rank-1 accuracy (12/19) is the weak
spot: the next levers are a reranker and heading-aware chunking.

**Multi-query retrieval, before and after** (the user's own question, "advantages and side effects of Linsinopril"):

| | Passages retrieved | Answer |
|---|---|---|
| Single query | Pharmacology, clinical studies, overdosage | Missed the Adverse Reactions section |
| **Three focused queries fused with RRF** | Includes label p. 9 (adverse reactions) | Headache 3.8%, dizziness 3.5%, cough 2.5%, hypotension, ATLAS trial figures, all from the label |

## 5.4 Chunk cleaning (coverage documents)

| Defect | Before | After |
|---|---|---|
| Chunks beginning with their own page number | 78 | 1 |
| Repeated revision stamps `(Rev. 18, Issued: …)` | 82 | 0 |
| Non-Latin letters (language-assistance page) | embedded; 306 letters still in 3 chunks after the first fix | 0 |
| Words glued by our hyphen rule / broken URLs | present | 0 |
| Total coverage chunks | 949 | 898 (272 + 209 + 407 + 10) |

## 5.5 Guardrails

| Measurement | Result |
|---|---|
| Layer-1 recall on 12 novel attacks (before tuning) | 1 / 12 |
| Layer-1 recall on 8 *fresh* attacks (after tuning, held out) | 6 / 8 |
| False positives on the 898 real coverage chunks (before / after fixing one broad pattern) | 30 → **0** |
| Attacks that evaded layer 1 yet passed the distance gate | 10 / 11 |
| Info-vs-advice behavior (18 hand-checked questions) | 18 / 18 as designed |
| Forged / expired / `alg:none` / edited / invented-role cookies rejected | 6 / 6 |
| SQL-injection attempts against MCP tools rejected, tables unchanged | 5 / 5 |

## 5.6 Live end-to-end evaluation (real Claude Haiku, real database, real MCP subprocess)

| Run | Result | What we learned |
|---|---|---|
| First (22 cases) | 22 / 22 | Muddled "unknown drug" reply → prompt fix |
| With drug-information cases (33 cases) | 30 / 33 | Old "side effects → refuse" expectation outdated by design; "does X cause Y" wrongly refused; compound question answered poorly |
| After multi-query, echo-stripping, "cause" pattern | 30 / 33 | **New regression:** the gate omitted a required field on off-topic questions → ValidationError |
| After making only `intent` required | **33 / 33** | Schema tolerance is a correctness feature |
| Added 4 role-flow cases (37 cases); verified README samples live | 36 / 37 | A pharmacist asking "their prescriptions" had been refused as medical advice (fixed with session context); a privacy check flagged only an echoed *name* (fixed message + data-based check) |
| **Final code** | **37 / 37** | |

Typical latency: refusals 0.0–0.1 s (no model call); off-topic 0.6–1.2 s (one small call); record answers 2.5–5.5 s;
drug-information answers 3–6 s; the first request after startup 8–10 s (model load).

## 5.7 Test inventory

| File | Tests | Covers |
|---|---|---|
| `test_guardrails.py` | 110 | input guard (attacks, advice, info, personal wording), fencing, prompt, output guard |
| `test_agent.py` | 47 | every graph branch with fake LLMs, roles, memory, errors, drug mode, multi-query |
| `test_api.py` | 20 | cookies, forged tokens, CSRF, CORS, role isolation, rate limits, SSE, errors |
| `test_drugs.py` | 16 | name/brand/typo resolution, no invented drugs |
| `test_mcp.py` | 14 | tools, hostile input, read-only DB, gateway trust boundary, real stdio |
| `test_chunking.py` | 7 | one regression per chunking defect |
| `test_label_retrieval.py` | 7 | metadata filters, iterative scan, keyword match (needs ingested labels) |
| **Backend total** | **221** | |
| Frontend (`core.test.ts`, `api.test.ts`) | 15 | SSE parser, state reducer, API error messages |

Code size: about 2,600 lines of backend Python, 1,700 lines of tests, 500 lines of SQL migrations, 1,700 lines of
frontend TypeScript.

## 5.8 Data and ingestion facts

* Relational: 4 plans, 13 drugs, 52 coverage rows (plan × drug), 8 patients, 16 prescriptions. All synthetic.
* Coverage corpus: 4 PDFs (83 + 53 + 122 + 4 pages), 898 chunks, embedded in a few minutes.
* Label corpus: 13 PDFs, 720 pages, 1,931 chunks; **about 80 chunks per minute on CPU** (about 23 minutes), run in the
  background; ingestion is idempotent (SHA-256 skip) and commits one document at a time.
* Embedding model 210 MB (`bge-base`) vs 67 MB (`bge-small`); vector column `vector(768)`.

---

# Part 6. What more can be done, and how

Ordered roughly by value-for-effort. Each item states the **problem it solves**, the **approach**, and **how you'd
verify it worked**.

## 6.1 Retrieval quality
| Upgrade | Problem it solves | Approach | Verify |
|---|---|---|---|
| **Heading-aware chunking** | Chunks lose their section ("6.1 Clinical Trials") | Detect numbered/ALL-CAPS headings while extracting; add a `section` column; prepend `Section: …` to the text that is embedded; show the section in citations | Re-run `eval_labels.py`; expect better hit@1 for "warnings/side effects" |
| **Cross-encoder reranker** | Right passage retrieved but ranked 3rd–10th | Retrieve top 30, rerank with a cross-encoder (e.g., `bge-reranker`), keep 5 | precision@5 and hit@1 before/after; measure added latency |
| **Contextual retrieval** | Chunks that depend on surrounding text | One Haiku call per chunk at ingestion to write a 1–2 sentence context; embed `context + chunk` | hit@k on questions that previously missed |
| **Label section routing** | "Side effects" should search section 6, "warnings" section 5 | Classify the question into a label section; filter by the stored section | Fewer irrelevant passages in drug mode |
| **Fresher data** | Labels and policies change | Scheduled job: compare SHA-256, re-ingest changed documents, record a version | Ingestion log shows "changed → re-embedded" |
| **Tune the gate per corpus** | Label questions may have a different distance profile | Calibrate a separate `MAX_DISTANCE` for `drug_label` using `eval_labels.py` | In/out-of-scope distance histograms |

## 6.2 Safety and security
| Upgrade | Approach |
|---|---|
| **ML injection/jailbreak classifier** | Add a small classifier model (Prompt-Guard-style) as another stricter-only layer; log its score; compare with regex on a held-out attack set |
| **Fail-closed audit for PHI** | If the audit insert fails for a patient-data access, abort the turn (a transaction around "audit then answer") |
| **Real authentication** | OIDC/SSO, short-lived tokens, rotating refresh, MFA; keep `Access` as the abstraction |
| **PII/PHI redaction in logs & prompts** | Detect names/IDs before logging; never send more patient fields than the question needs (minimum necessary) |
| **Secrets management** | Move `.env` secrets to a secrets manager; give the MCP process only the read-only URL (separate service account), not the owner URL or the API key |
| **Sentence-level verification** | Verify each claim against its cited passage (NLI model or LLM-judge), not only that a citation exists |
| **Stronger number grounding** | Extend the `$`/`%` check to refill counts, strengths, durations, tiers |
| **Better refusals** | Distinct, helpful messages (e.g., "I can only show *your* records") instead of a generic "I don't know" after an uncited draft |

## 6.3 Scale and operations
| Upgrade | Approach |
|---|---|
| **Postgres checkpointer** | LangGraph Postgres saver so memory survives restarts and works across instances |
| **Redis** | Shared rate limiting, concurrency counters, and a semantic cache for *non-personal* questions |
| **Observability** | OpenTelemetry traces per node; LangSmith/Langfuse for prompts and outputs; metrics: p50/p95 latency per stage, outcome mix, block reasons, retrieval distance distribution, cost per turn |
| **Anthropic prompt caching** | Cache the large static system prompt and, in drug mode, repeated label context to cut cost and latency |
| **Model routing** | Haiku by default; escalate to a larger model only for ambiguous gate decisions; measure the quality/cost trade |
| **pgvector at scale** | Tune `m`/`ef_construction`/`ef_search`; partial indexes or partitions by category; consider `pgvectorscale` or a dedicated store beyond tens of millions of vectors |
| **Deployment** | Docker images (API, MCP, frontend), a reverse proxy with TLS and `X-Forwarded-For` from a trusted proxy only, `COOKIE_SECURE=true`, CI running pytest + Vitest + lint + build |
| **Cost controls** | Per-user daily token budget, prompt/response size caps, alerts on spend |

## 6.4 Product
Streaming with **post-hoc verification** (stream a sentence only after it passes the verifier) · feedback buttons feeding
an evaluation set · multilingual support (needs multilingual embeddings and prompts) · OCR for scanned documents ·
voice input (this is where WebSockets would earn their place) · a "compare two drugs' labels" view · citations that
open the PDF to the exact page (already links `#page=N`) with the passage highlighted.

## 6.5 Evaluation maturity
* Grow the retrieval set from 20 to 200+ questions, versioned in the repo, with **MRR** and **nDCG** alongside hit@k.
* An **LLM-as-judge** faithfulness/answer-relevance score (RAGAS-style), spot-checked against human labels.
* A separate, *never-looked-at* attack set; track attack success rate per release.
* Run all of the above in CI and fail the build on regressions.

---

# Part 7. Interview preparation

## 7.1 Scripts to rehearse

**30 seconds.** "I built a healthcare insurance and pharmacy assistant with RAG over Postgres/pgvector, an MCP server for
patient records, and a LangGraph agent. The core idea is that safety is enforced in code around the model: input guards,
untrusted-text fencing, a strict prompt, and an output verifier that rejects uncited or ungrounded answers. I measured
retrieval and attack resistance and fixed what the measurements exposed."

**5-minute deep dive (talk track).**
1. *Problem:* answers must be cited, exact for patient data, and never medical advice.
2. *Data:* three knowledge sources and why each uses a different retrieval path (RAG vs MCP).
3. *Pipeline:* ingestion → chunking → embeddings → pgvector HNSW + tsvector → RRF → filters → gate.
4. *Agent:* LangGraph nodes, parallel branches, stricter-only gate, memory scoping.
5. *Safety:* four layers, fail-closed, least privilege, identity from the session.
6. *Evidence:* hybrid vs vector numbers, the threshold-isn't-security finding, the 30-chunk false-positive bug.
7. *Trade-offs and next steps:* reranking, Postgres checkpointer, fail-closed audit, real auth.

**Follow-up you should expect:** "What was the hardest bug?" (Pick one from Part 4: the scroll bug, the OR-keyword
regression, or the cross-layer money-format bug.) "What would you do differently?" (Heading-aware chunking from the
start; a held-out attack set from day one; a Postgres checkpointer.)

## 7.2 Question bank with model answers

### RAG and retrieval
1. **Why chunk documents?** An embedding is one vector per text; a whole manual becomes a blurry average and won't fit
   in a prompt. Chunks ≈ one idea each. We use ~1000 chars, sentence-aligned, per page, with sentence overlap.
2. **How did you choose chunk size and overlap?** Start from a reasonable default, inspect chunks, measure hit@k,
   adjust. Overlap prevents a fact from being split across a boundary.
3. **Cosine vs dot product vs Euclidean?** For normalized embeddings they rank the same. We use cosine distance (`<=>`).
4. **Explain HNSW.** A multi-layer proximity graph; search descends from sparse top layers to dense bottom layers.
   `m`/`ef_construction` shape the build; `ef_search` is the query-time candidate list: recall vs speed.
5. **What is the filtered-ANN problem?** The index returns nearest candidates before the `WHERE` filter, so selective
   filters starve results. Fix: iterative scan (pgvector ≥ 0.8), partial indexes/partitions, or exact search for small sets.
6. **Hybrid search: when and how?** When both meaning and exact terms matter. Run vector and keyword searches and fuse
   with RRF `Σ 1/(k + rank)`. Measure; ours helped modestly and OR-keywords hurt.
7. **How do you evaluate retrieval?** Labelled questions with an expected phrase; hit@k, MRR, precision; compare variants;
   separately evaluate the "no answer" case via out-of-scope questions and distance distributions.
8. **How do you set a relevance threshold?** Plot best-match distance for in-scope vs out-of-scope questions, pick a
   value in the gap, then recheck periodically. Expect a thin margin and don't treat it as safety.
9. **Reranking?** A cross-encoder rescoring top-N; use when recall@N is fine but precision@k isn't. Not needed yet; I'd
   measure first.
10. **How do you handle documents that change?** Hash each file, re-ingest on change in one transaction, keep a
    `verified_on` and `ingested_at`, schedule the job.
11. **How do you reduce hallucination in RAG?** Evidence-only prompt, citations, a verifier that checks them, numeric
    grounding, a refusal path when evidence is missing, `temperature=0`.
12. **What are the limits of vector search?** Exact numbers and rare tokens, negation, multi-hop reasoning, very short queries.

### Postgres / pgvector / data
13. **Why Postgres for vectors?** One transactional system for relational data, vectors, full-text, audit, with SQL
    joins and familiar operations; avoids data sync between systems.
14. **Generated columns?** `GENERATED ALWAYS AS (…) STORED` keeps `tsvector` in sync automatically, so ingestion never
    has to know about it.
15. **How is least privilege applied to the DB?** Separate owner and app roles; app role has SELECT (and INSERT only on the
    audit table); session `default_transaction_read_only`; `statement_timeout`; fixed parameterized queries.
16. **Why numbered idempotent migrations?** Reviewable history, safe re-runs (`IF NOT EXISTS`, `ON CONFLICT`), one
    transaction per file, `--dry-run` to rehearse.
17. **How do you prevent SQL injection?** Bound parameters everywhere, strict input regexes, no free-form SQL tool,
    read-only role as the last line.

### MCP and agents
18. **What problem does MCP solve?** A standard, language-agnostic way to expose tools/resources to AI apps, enabling
    reuse and a clean trust boundary.
19. **How do you stop the model from choosing whose data to read?** The tool schema omits the id; the gateway injects
    the session's patient and re-checks the role allowlist on every call.
20. **Why LangGraph?** Explicit, typed, testable control flow with checkpointing and parallelism; guards between LLM calls.
21. **How does state work and what is a reducer?** Nodes return partial updates; a reducer defines how an update merges
    (append vs overwrite). Ours appends and trims `history`.
22. **How do parallel branches work?** A conditional edge returns multiple node names; they run in the same superstep
    and the join node runs once afterwards.
23. **How do you handle conversation memory safely?** Server-side checkpointer keyed by `role:patient:conversation`;
    store only screened input and verified output; reset per-turn fields.
24. **Single agent vs multi-agent?** We use a pipeline of specialized single-purpose LLM calls with deterministic
    glue. Multi-agent adds cost and unpredictability; use it when subtasks truly need autonomy.

### Drug-information mode and multi-query retrieval
12a. **How can a medical bot discuss drugs without giving advice?** Quote an official label for a named drug (information),
     refuse personal wording, dosing, overdose and "should I" questions (advice), add a fixed notice in code, and require three
     independent conditions before the label path opens.
12b. **What is multi-query retrieval?** Split a compound question into focused sub-queries, search each, fuse with RRF. We saw a
     single query return pharmacology and overdosage for "advantages and side effects" and miss the adverse-reactions section.
12c. **Why resolve the drug name in code instead of asking the LLM?** It chooses which document is searchable, so it must be
     deterministic and unable to invent a drug: fuzzy matching against our own catalog can't.
12d. **Your metadata filter didn't change hit@k. Why keep it?** It's a guarantee, not a ranking tweak. Measured: name-less queries
     return the right drug's label 6% of the time without it and 100% with it; unfiltered coverage searches leak label text 3%.
12f. **How did you find that a documented example was broken?** I ran every sample question in the README against the live system
     before publishing it. One (a pharmacist asking "their prescriptions") was refused as medical advice. I added session context to the
     classifier, tests, and live regression cases. Documentation is a set of claims; verify them.
12e. **A prompt change broke three cases. What did you do?** Reproduced it, read the raw tool call (a required field was omitted),
     made only `intent` required, added tests, and re-ran the live evaluation. Lesson: re-run evals after every prompt edit.

### Safety and security
25. **Direct vs indirect injection?** Direct: attacker types it. Indirect: hidden in data the model reads. Defense: treat
    data as untrusted (fence, escape, screen), minimal capabilities, verify output.
26. **Why is a distance threshold not a safety control?** It measures topical similarity; attack text about "instructions"
    or "doctor" sits near policy text. We measured 10 of 11 evasive attacks passing it.
27. **Why "stricter-only" for the LLM gate?** So a manipulated classifier can't loosen restrictions; code decides what's
    allowed and the model can only narrow it.
28. **What is fail-closed?** On any verification failure respond with a safe canned reply, never raw model output.
29. **How do you let a bot discuss drugs without giving advice?** Distinguish information (quote an official label for a
    named drug, no personalization, no dosing, fixed disclaimer) from advice (refused). Personal wording flips it.
30. **How would you test guardrails honestly?** Held-out attacks, false-positive tests on real data, and tracking block
    reasons in production. Our first set became training data once we saw it.
31. **How do you protect PHI?** Minimum necessary data per tool, role scoping, audit trail, hash-not-text logging,
    redacted errors, encryption in transit (`sslmode=require`), and (for production) fail-closed audit and HIPAA review.
32. **What is a canary token?** A random string planted in the system prompt; if it appears in output, the prompt leaked.

### API, auth, frontend
33. **SSE vs WebSockets for chat?** SSE for server→client streams over plain HTTP; WebSockets for bidirectional.
34. **Why not stream tokens?** Output must be verified before display; unverified tokens could expose rejected text.
    Production could verify sentence by sentence.
35. **How do you secure the session?** Signed JWT in an HttpOnly, SameSite cookie with expiry; Origin check; strict CORS;
    `extra="forbid"` request models; rate limits.
36. **How do you handle a client disconnect mid-stream?** The generator's `finally` releases resources and audits the
    aborted turn; the AbortController closes the connection from the browser.
37. **Why a reducer for chat state in React?** Streams are event sequences; a pure `(state, event) → state` function is
    testable and avoids race-prone mutable updates.

### Evaluation and operations
38. **What do you track in production?** Outcome mix, block reasons, per-stage latency, retrieval distance, cost per
    turn, error rate, user feedback, audit anomalies.
39. **How would you cut cost?** Prompt caching, cheaper model for gate/planner, shorter contexts (fewer chunks), semantic
    cache for non-personal questions, early refusals before any model call (already 0.1 s and free).
40. **How would you scale 100×?** Stateless API behind a load balancer; Redis for limits/cache; Postgres checkpointer;
    read replicas for retrieval; tune HNSW; queue/limit concurrent LLM calls; observability and autoscaling.

## 7.3 System-design prompts to practice

1. **"Design a clinical-policy Q&A assistant for 1M members."** Cover: ingestion pipeline and versioning, chunking and
   embeddings, vector + keyword retrieval, per-tenant filtering, PHI handling, auth/RBAC, audit, rate limiting,
   evaluation, monitoring, cost, failure modes, human escalation.
2. **"Your RAG answers are wrong 15% of the time. Debug it."** Build an eval set → separate retrieval failures
   (hit@k) from generation failures (faithfulness) → inspect chunks → test hybrid/rerank/filters → tighten prompt and
   verifier → monitor.
3. **"How do you stop prompt injection in a tool-using agent?"** Capabilities minimization, data/instruction separation,
   least privilege, confirmation for risky actions, output validation, monitoring.
4. **"Add write actions (refill requests) safely."** Separate write tools with explicit user confirmation, idempotency
   keys, role checks, audit-before-act, rate limits, and no model-chosen identifiers.

## 7.4 Behavioral stories (STAR) from this project

* **The regression I introduced and caught.** *Situation:* improving search. *Task:* add keyword search. *Action:* first
  version OR-ed words; I measured and it dropped hit@1 from 16/20 to 13/20; tried variants side by side; shipped AND with
  vector fallback. *Result:* 17/20 and a habit of before/after numbers.
* **The guard that blocked real documents.** Found 30/898 false positives by scanning the corpus; tightened the pattern;
  added permanent tests. Lesson: test controls against real benign data.
* **A wrong prediction.** I claimed hybrid search would fix an exact-number miss; it couldn't, because the number was in the
  answer, not the question. I corrected it openly and explained what each retriever matches on.
* **Bug only a browser found.** Auto-scroll hiding the last reply; wrote a Chrome-driven run, found the cause (own smooth-scroll
  events), fixed with `ResizeObserver`.
* **Scope change handled well.** The spec said "never discuss medicine"; a natural user question needed drug information.
  I laid out the options and risks, got a decision, and built a constrained mode with stricter-only checks and tests.

## 7.5 Trick questions and honest answers

* *"Is your bot HIPAA compliant?"* No. It uses synthetic data and simulated auth. I can list what production needs:
  BAAs, real identity, fail-closed audit, encryption at rest, access reviews, retention policy, breach procedures.
* *"Did you evaluate with a held-out set?"* Retrieval: a labelled set I wrote (20 questions). Attacks: first set was
  contaminated; a fresh set of 8 measured 6 of 8 recall. I'd expand both.
* *"Why not LangChain's PGVector?"* It can't express our hybrid fusion, joins to a sources table, filters with iterative
  scan, or gate; ~100 lines of SQL give full control and testability.
* *"Why Haiku?"* Cost/latency; the verifier and guards reduce dependence on model strength. I'd benchmark a larger model
  on the gate and answer steps before deciding.
* *"What breaks first at scale?"* In-memory limits and memory (not shared across instances), embedding on CPU, HNSW build
  time, and LLM concurrency/cost.

## 7.6 Numbers and phrases to have ready

`0.47` distance gate · `768` dimensions · `HNSW` + `ef_search` · iterative scan (`relaxed_order`) · RRF `k=60` ·
`~1000`-char chunks with sentence overlap · hybrid `17/20` vs vector `16/20` hit@1 · `0` of `898` false positives ·
`1/12` then `6/8` guard recall · refusals `~0.1 s` · four layers · stricter-only · fail closed · identity from the cookie ·
append-only audit · 221 + 15 tests · labels: hit@5 `19/19`, name-less right-drug share `6% → 100%` · live eval `37/37`.

---

# Part 8. Glossary

**ANN** approximate nearest neighbor search · **Audit log** record of who accessed what · **Canary** secret string that reveals a
prompt leak · **Chunk** a piece of a document that is embedded and retrieved · **Citation** reference like `[S1]` tying a claim
to a source · **Cosine distance** `1 − cosine similarity` · **CSRF** forged cross-site request using a victim's cookie · **Embedding**
vector representing meaning · **Fail closed** deny/refuse on error · **Fencing** wrapping untrusted text as data · **Filtered ANN**
vector search with a `WHERE` clause · **Gate** the intent/routing classifier · **GIN** inverted index for full-text · **Grounding**
tying output to evidence · **Guardrail** a control constraining model behavior · **HNSW** graph-based ANN index · **HyDE** embed a
hypothetical answer · **Indirect injection** malicious instructions inside retrieved data · **Iterative scan** pgvector feature that
keeps searching until filters are satisfied · **JWT** signed token · **LangGraph** state-machine framework for agents · **MCP** Model
Context Protocol · **Metadata filter** exact filter on document attributes · **MRR/nDCG/hit@k** retrieval metrics · **PHI** protected
health information · **RAG** retrieval-augmented generation · **Reducer** function merging a state update · **RRF** reciprocal rank
fusion · **SSE** server-sent events · **Stricter-only** a component that can add restrictions but never remove them · **tsvector** Postgres
preprocessed text for search.

---

# Part 9. Hands-on labs (learn by changing the system)

Each lab: change one thing, measure, write down what happened.

1. **Chunk size experiment.** Try 600 / 1000 / 1500 characters. Re-ingest one document, run `eval_retrieval.py`. Which wins and why?
2. **Vector vs hybrid.** In `tests/eval_retrieval.py`, add 10 questions with rare terms (acronyms, codes). Does hybrid's margin grow?
3. **Break the threshold.** Move `MAX_DISTANCE` to 0.40 and 0.55. What happens to the in-scope hit rate and to out-of-scope leakage?
4. **Write a new guard rule + its tests.** Add a pattern for a phrase you invent; write 3 attacks and 3 benign sentences; scan the 898 chunks for false positives.
5. **Add a drug.** Add a drug to `hc_drugs`, find its DailyMed label, add a source row, ingest, add an `eval_labels` case.
6. **Heading-aware chunking.** Detect section headings in labels, store `section`, prepend it before embedding, and measure `eval_labels.py` again.
7. **Add a reranker.** Rerank the top 30 with a cross-encoder; compare precision@5 and added latency.
8. **Fail-closed audit.** Make a chat turn abort if its audit insert fails; write the test.
9. **Redis rate limiter.** Replace the in-memory limiter; run two server processes and verify limits are shared.
10. **New role.** Add a "support agent" role that sees plan and coverage but not prescriptions; add role tests.
11. **Red-team yourself.** Write 20 new attacks; run them through `check_input` and then the live agent; categorize what got through and which layer caught it.
12. **Explain-it-back.** Without notes, draw the architecture and narrate one turn (guest asks a coverage question, then a patient asks for their copay).

---

# Appendix A. File-by-file map

| Path | What it does |
|---|---|
| `backend/db/001–008_*.sql` | Schema, synthetic data, vector tables, sources, keyword index, audit log, categories, FDA label sources |
| `backend/app/config.py`, `db.py` | Typed settings; read-only, owner and audit engines |
| `backend/app/rag/chunking.py` | Cleaning + sentence-aligned chunker |
| `backend/app/rag/embeddings.py` | Local embedding model, query vs passage |
| `backend/app/rag/retriever.py` | Hybrid search, RRF, metadata filters, iterative scan, gate |
| `backend/app/rag/drugs.py` | Fuzzy drug-name resolver over the catalog |
| `backend/mcp_server/queries.py` / `server.py` | The only patient-data SQL; MCP tools |
| `backend/app/mcp_client.py` | Gateway: hides identity, injects session, enforces allowlist |
| `backend/app/guardrails/*` | Input guard, fencing, prompts, output guard, fixed messages |
| `backend/app/agent/*` | LangGraph state, nodes, graph, runner, helper prompts |
| `backend/app/auth/*` | Roles and tool allowlists; signed sessions |
| `backend/app/main.py` | REST + SSE, rate limiting, audit, errors |
| `backend/scripts/*` | `run_sql`, `ingest`, `check_*`, `search_cli`, `chat_cli`, `mcp_demo` |
| `backend/tests/*` | Unit/integration tests and evaluation scripts |
| `frontend/src/*` | `api.ts`, `sse.ts`, `chatState.ts`, hooks, components |
| `dev.sh` | One-command launcher |

# Appendix B. Command cheat sheet

```bash
./dev.sh                                                        # run everything
cd backend && ../.venv/bin/python -m pytest -q                  # tests
../.venv/bin/python -m scripts.run_sql db/00X_file.sql --dry-run
../.venv/bin/python -m scripts.ingest --category drug_label
../.venv/bin/python -m scripts.search_cli "What is step therapy?"
../.venv/bin/python -m scripts.chat_cli EHP-100001
../.venv/bin/python -m tests.eval_retrieval | tests.eval_labels | tests.eval_agent
cd frontend && npm test && npx tsc -b && npx oxlint && npm run build
```

# Appendix C. SQL cookbook (the queries behind the system)

```sql
-- 1) nearest chunks by cosine distance (uses the HNSW index)
SELECT chunk_id, embedding <=> :q AS distance
FROM hc_policy_chunks ORDER BY embedding <=> :q LIMIT 5;

-- 2) metadata-filtered vector search (iterative scan lets selective filters still return k rows)
SET LOCAL hnsw.iterative_scan = 'relaxed_order';
SELECT c.chunk_id, c.embedding <=> :q AS distance
FROM hc_policy_chunks c JOIN hc_policy_sources s USING (source_id)
WHERE s.category = 'drug_label' AND s.drug_id = ANY(:drug_ids)
ORDER BY c.embedding <=> :q LIMIT 5;

-- 3) keyword search with AND semantics, ranked
SELECT chunk_id FROM hc_policy_chunks
WHERE content_tsv @@ plainto_tsquery('english', :question)
ORDER BY ts_rank_cd(content_tsv, plainto_tsquery('english', :question)) DESC LIMIT 20;

-- 4) fusion: score = Σ 1/(60 + rank) across both ranked lists (see app/rag/retriever.py for the full CTE)

-- 5) a plan's copay for a patient's drug (the join through a composite key needs ALL key columns)
SELECT d.generic_name, c.tier, c.copay
FROM hc_prescriptions rx
JOIN hc_patients pt ON pt.patient_id = rx.patient_id
JOIN hc_drugs d ON d.drug_id = rx.drug_id
JOIN hc_plan_drug_coverage c ON c.drug_id = rx.drug_id AND c.plan_id = pt.plan_id
WHERE pt.member_id = :m AND rx.status = 'active';
```
