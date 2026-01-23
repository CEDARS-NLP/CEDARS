# LLM Multi-Document Context Approaches

## Team Summary

Beyond the sliding window approach, there are a few strategies from recent clinical NLP research worth considering. The simplest is a **fixed count window** (e.g., 3-5 notes before/after the keyword-matched note) - easy to implement and handles most cases where evidence is spread across adjacent notes. A step up is a **time-based window** (e.g., notes within 7 days) which works well when events have known temporal bounds. More sophisticated is **keyword-guided retrieval** where, when we find a note with "bleeding," we also pull in any notes mentioning related concepts like "transfusion," "hemoglobin," or "blood products" regardless of their position in the timeline - this catches evidence that might be temporally distant but clinically relevant. The most advanced approach from the literature is **RAG (Retrieval-Augmented Generation)** which dynamically retrieves the most relevant notes based on semantic similarity, but this adds significant complexity. My suggestion: start with the fixed count window since it's simple and covers most scenarios, then we can add keyword-guided retrieval for related concepts if we find we're missing events with scattered evidence.

---

## Detailed Comparison

| Approach | Best For | Complexity | Implementation |
|----------|----------|------------|----------------|
| **Fixed window (by count)** | Simple cases, predictable note patterns | Low | Pull X notes before/after by date |
| **Time-based window** | Events with known temporal bounds (e.g., 48-hour post-op bleeding) | Low | Pull notes within X days |
| **Keyword-guided retrieval** | When related concepts are known (bleeding → transfusion, Hgb, etc.) | Medium | Define related keyword sets per event type |
| **Entity-based RAG** | Complex events with scattered evidence | High | Semantic search over note embeddings |

## Research References

- **CLI-RAG (2025)**: Hierarchical chunking with dual-stage retrieval for clinical documents
- **CLEAR (2025)**: Clinical Entity Augmented Retrieval - F1 0.90 with 70% fewer tokens
- **EMERGE (2024)**: RAG-driven enhancement using knowledge graphs (PrimeKG)
- **MedBrowseComp (2025)**: Multi-hop reasoning across fragmented clinical information

## Recommended Starting Point

1. Implement fixed count window (configurable: X notes before, Y notes after)
2. Order notes by `text_date` for the patient
3. Concatenate context notes with clear delimiters for the LLM
4. Add project setting: "Context window size" (0 = single note only)
5. Future enhancement: Add keyword-guided retrieval for related concepts
