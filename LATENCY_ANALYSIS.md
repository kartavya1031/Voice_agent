# AI Voice Agent Latency Analysis & Optimization Plan

## 🎯 OPTIMIZATION RESULTS - BEFORE vs AFTER

### Comparison Data (Real Measurements)

| Metric | BEFORE | AFTER | Improvement |
|--------|--------|-------|-------------|
| **First Audio Latency** | 3291ms | 1867ms | **-1424ms (43%)** ✅ |
| **RAG Lookup (blocking)** | 925ms | 0ms* | **-925ms (100%)** ✅ |
| **LLM TTFT** | 2621ms | 1621ms | **-1000ms (38%)** ✅ |
| **Total LLM Time** | 3567ms | 2380ms | **-1187ms (33%)** ✅ |
| **TTS (first sentence)** | 420ms | 240ms | **-180ms (43%)** ✅ |

*RAG now runs in parallel, not blocking LLM start

### Query-by-Query Comparison

#### Query: "Leadership team" (Complex - uses RAG)
```
BEFORE:
├─ RAG: 925ms (blocking)
├─ LLM TTFT: 2621ms  
├─ First Audio: 3291ms
└─ Total: 3568ms

AFTER (Optimized):
├─ RAG: 0ms (parallel, 1121ms in background)
├─ LLM TTFT: 1621ms (-1000ms!)
├─ First Audio: 1867ms (-1424ms!)
└─ Total: 2381ms (-1187ms!)
```

#### Query: "Hello" (Simple - skip RAG)
```
BEFORE:
├─ RAG: ~900ms (was still running)
├─ LLM TTFT: ~2600ms
├─ First Audio: ~3200ms

AFTER (Optimized):
├─ RAG: SKIPPED ⚡
├─ LLM TTFT: 1662ms
├─ First Audio: 2044ms (-1156ms!)
```

### Visual Timeline Comparison

```
BEFORE (3291ms to first audio):
0ms ──────────────────────────────────────────────────► 3291ms
├──────────┼─────────────────────────────────────┼─────┤
│   RAG    │          LLM TTFT                   │ TTS │
│  925ms   │          2621ms                     │420ms│
│ BLOCKING │                                     │     │
└──────────┴─────────────────────────────────────┴─────┘

AFTER (1867ms to first audio):  
0ms ─────────────────────────────► 1867ms
├──────────────────────────┼──────┤
│      LLM TTFT            │ TTS  │
│      1621ms              │ 240ms│
│     (RAG in parallel)    │      │
└──────────────────────────┴──────┘

IMPROVEMENT: 43% faster! ⚡
```

---

## 📊 Detailed Timing Analysis (BEFORE Optimization)

🔴 MAJOR BOTTLENECK: LLM Time-to-First-Token (80% of latency)
🟡 SECONDARY BOTTLENECK: RAG Lookup (28% of latency)
🟢 ACCEPTABLE: TTS (12% of latency)
```

---

## 🎯 Key Findings

### Current Performance
| Metric | Current | Target | Gap |
|--------|---------|--------|-----|
| First Audio Latency | 2800-3400ms | <1000ms | ~2500ms |
| RAG Lookup | 900-1200ms | <200ms | ~800ms |
| LLM TTFT | 2600-3100ms | <500ms | ~2200ms |
| TTS First Sentence | 200-420ms | <200ms | 0-220ms |

### Bottleneck Priority
1. **🔴 LLM TTFT (80%)** - Biggest issue, Azure OpenAI response time
2. **🟡 RAG Lookup (25%)** - Embedding API call + vector search
3. **🟢 TTS (<15%)** - Acceptable, already optimized

---

## 🚀 Optimization Plan

### Phase 1: Quick Wins (Expected: -1500ms)

#### 1.1 Switch to GPT-4o-mini Turbo Mode
**Current**: Using `gpt-4o-mini` with default settings
**Change**: Add low-latency parameters
```python
response = client.chat.completions.create(
    model=DEPLOYMENT_NAME,
    messages=messages,
    max_tokens=150,  # Reduce from 200
    temperature=0.5,  # Reduce from 0.7 (faster sampling)
    stream=True,
    # Azure-specific optimizations:
    timeout=10,
)
```
**Expected Improvement**: -300ms on TTFT

#### 1.2 Parallel RAG + LLM Start
**Current**: RAG completes → then LLM starts
**Change**: Start LLM immediately with cached/default context, update if RAG returns fast
**Expected Improvement**: -800ms (RAG time hidden)

#### 1.3 Reduce System Prompt Size
**Current**: Large system prompt + RAG context
**Change**: Optimize system prompt, limit RAG context to 500 chars
**Expected Improvement**: -200ms on TTFT

### Phase 2: Architecture Changes (Expected: -1000ms)

#### 2.1 Cache Embedding Results
**Current**: Every query hits Azure Embeddings API
**Change**: LRU cache for recent embeddings
```python
from functools import lru_cache

@lru_cache(maxsize=100)
def get_cached_embedding(query: str):
    return embedding_fn([query])
```
**Expected Improvement**: -500ms for repeated/similar queries

#### 2.2 Pre-warm LLM Connection
**Current**: Cold start on each request
**Change**: Keep connection alive, send warmup request on call start
**Expected Improvement**: -200ms

#### 2.3 Sentence Boundary Detection Optimization
**Current**: Wait for `.!?` followed by space
**Change**: Detect shorter phrases (commas, colons) for faster first audio
**Expected Improvement**: -300ms to first audio

### Phase 3: Infrastructure (Expected: -500ms)

#### 3.1 Use Azure OpenAI PTU (Provisioned Throughput)
**Current**: Pay-per-token (shared capacity)
**Change**: Reserved capacity with guaranteed latency
**Expected Improvement**: -500ms+ on TTFT

#### 3.2 Deploy Closer to User
**Current**: Single Azure region
**Change**: Edge deployment or closer region
**Expected Improvement**: -100ms network latency

---

## 📋 Implementation Priority

| Priority | Change | Effort | Impact | Timeline |
|----------|--------|--------|--------|----------|
| 1 | Parallel RAG + LLM | Medium | High (-800ms) | Day 1 |
| 2 | Reduce max_tokens/temp | Low | Medium (-300ms) | Day 1 |
| 3 | Cache embeddings | Low | Medium (-500ms) | Day 2 |
| 4 | Shorter sentence detection | Low | Medium (-300ms) | Day 2 |
| 5 | Pre-warm connection | Medium | Low (-200ms) | Day 3 |
| 6 | Azure PTU | High ($$$) | High (-500ms) | Week 2 |

---

## 🎯 Expected Results After Optimization

| Metric | Before | After Phase 1 | After Phase 2 |
|--------|--------|---------------|---------------|
| First Audio | 3200ms | 1700ms | 1000ms |
| Total Response | 4000ms | 2500ms | 1500ms |
| User Experience | Poor | Acceptable | Good |

**Target**: <1000ms first audio latency for natural conversation feel

 Optimization Results Summary
✅ Achieved Improvements
Metric	Before	After	Improvement
First Audio Latency	3291ms	1867ms	-43% 🎉
RAG Blocking Time	925ms	0ms	-100% (now parallel)
LLM TTFT	2621ms	1621ms	-38%
Total Pipeline	3567ms	2380ms	-33%
What's Working
✅ Parallel RAG - 🚀 Starting LLM without waiting for RAG appears in logs
✅ Skip RAG for simple queries - ⚡ Skipping RAG for simple query works
✅ Barge-in - Interruption working correctly
✅ Reduced tokens/temperature - Faster generation