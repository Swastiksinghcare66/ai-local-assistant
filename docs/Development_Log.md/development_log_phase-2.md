# ConAI Engineering Journal

> **Author:** Swastik Singh
>
> **Project:** ConAI
>
> **Version:** v0.2
>
> **Status:** In Development

---

# Table of Contents

1. Vision
2. Goals
3. Design Philosophy
4. Why Local AI?
5. Project Structure
6. Engineering Decisions
7. Module Documentation
8. Version Control Strategy
9. Performance Notes
10. Current Architecture
11. Roadmap
12. Lessons Learned

---

# 1. Vision

## Objective

ConAI is a completely local conversational AI assistant designed to become an extensible AI operating system.

Unlike a normal chatbot, ConAI is intended to grow into multiple specialized assistants while sharing the same core architecture.

Future capabilities include:

- Conversational AI
- Research Assistant
- Study Assistant
- Health Companion
- Voice Assistant
- PDF Research
- Memory System
- Multi-Agent AI

The goal is to build one strong foundation instead of creating many separate applications.

---

# 2. Goals

The project follows several engineering goals.

## Primary Goals

- Fully local execution
- Privacy-first
- Modular architecture
- Easy expansion
- Easy debugging
- Easy maintenance

## Non-Goals

The project is **not** intended to become a single monolithic Python script.

Every feature should remain independent.

---

# 3. Design Philosophy

The project follows several software engineering principles.

---

## Principle 1

### Single Responsibility Principle (SRP)

Every module should perform one job.

Good

config.py

↓

Stores configuration.

Bad

config.py

↓

Configuration

↓

Database

↓

Networking

↓

Logging

↓

Memory

---

Reason

Smaller modules are easier to understand, debug and modify.

---

## Principle 2

### Loose Coupling

Modules should depend on interfaces instead of implementations.

Instead of

main.py

↓

Ollama

Use

main.py

↓

llm_client.py

↓

Ollama

Later the inference engine can be changed without affecting the application.

---

## Principle 3

### High Cohesion

All related code should remain together.

Example

Conversation logic belongs inside

conversation.py

Not inside

main.py

---

## Principle 4

### Build for Expansion

Always assume the project will become larger.

Avoid shortcuts that save five minutes today but create weeks of work later.

---

# 4. Why Local AI?

Reasons

- Privacy
- Offline availability
- Low latency
- No API cost
- Full control over models
- Fine-tuning support
- Custom tool integration

---

# 5. Project Structure

Current Structure

```
ConAI/

app/
    __init__.py
    config.py
    prompts.py
    llm_client.py
    main.py
    utils.py

data/

docs/

logs/

scripts/

tests/

requirements.txt
```

---

# Why this structure?

Beginners often create

```
main.py
```

containing everything.

Eventually

```
4000+ lines
```

become impossible to maintain.

Instead every directory has a specific responsibility.

---

# app/

Contains application source code.

---

# data/

Future

- embeddings
- vector databases
- persistent memory

---

# docs/

Documentation.

This file is stored here.

---

# logs/

Conversation logs.

Performance logs.

Error logs.

---

# scripts/

Temporary utilities.

Dataset downloads.

Migration scripts.

Benchmark scripts.

Prototype code.

---

# tests/

Automated testing.

Future unit tests.

Integration tests.

---

# 6. Engineering Decisions

---

## Decision 1

### Create config.py

Problem

Configuration values become scattered throughout the project.

Example

```
model="qwen3:4b"
```

appears inside many files.

Changing the model requires editing multiple files.

---

Solution

Create

```
config.py
```

Store

- MODEL_NAME
- HOST
- TEMPERATURE
- MAX_HISTORY

---

Advantages

- Central configuration
- Easier maintenance
- Easy model switching
- Future environment support

---

Industry Practice

Nearly every large software project centralizes configuration.

---

## Decision 2

### Create prompts.py

Problem

Prompt engineering becomes mixed with application logic.

Example

```
client.chat(
    messages=[
        ...
    ]
)
```

contains a very long prompt.

Changing personality requires editing application code.

---

Solution

Separate prompts into

```
prompts.py
```

Application logic becomes independent from AI behavior.

---

Advantages

- Cleaner architecture
- Easier experimentation
- Multiple personalities
- Prompt versioning

---

Future

Research Prompt

Coding Prompt

Tutor Prompt

Health Prompt

Planner Prompt

---

## Decision 3

### Create llm_client.py

Problem

Every file communicates directly with Ollama.

Future changes become difficult.

---

Solution

Only

```
llm_client.py
```

knows how to talk to Ollama.

Application communicates only with

```
chat()
```

---

Advantages

Easy migration to

- vLLM
- llama.cpp
- LM Studio
- HuggingFace TGI
- OpenAI Compatible APIs

No other module changes.

---

Design Pattern

Adapter Pattern

---

## Decision 4

### Create main.py

Purpose

Application entry point.

Responsibilities

- Start program
- Read input
- Call LLM
- Print response

Responsibilities NOT allowed

- Database logic
- Memory logic
- Networking
- Prompt engineering
- AI implementation

Reason

Keeps application flow simple.

---

## Decision 5

### Create __init__.py

Purpose

Turn

```
app/
```

into a Python package.

Benefits

Allows imports like

```python
from app.config import MODEL_NAME
```

instead of fragile file-relative imports.

---

# 7. Version Control Strategy

---

## Why Git?

Git stores the complete history of the project.

Benefits

- Rollback
- Collaboration
- Backup
- Experiment safely

---

## Why Branches?

Instead of working directly on

```
main
```

new work happens inside

```
feature/core-chat
```

Advantages

- Stable main branch
- Easy rollback
- Parallel development

---

## Why Meaningful Commit Messages?

Bad

```
Update

Fix

Changes
```

Good

```
Initialize ConAI

Add configuration module

Implement modular Ollama client

Create conversation manager

Implement persistent memory
```

Future developers immediately understand project history.

---

# 8. Performance Notes

Current Model

```
qwen3:4b
```

Inference

GPU

RTX 4060 Laptop

Observed

Cold response approximately 7.5 seconds.

Future Optimization

- Streaming responses
- Better prompts
- Context optimization
- Model benchmarking
- Response caching

Performance should always be measured before optimization.

---

# 9. Current Architecture

```
User
 │
 ▼
main.py
 │
 ▼
llm_client.py
 │
 ▼
prompts.py
 │
 ▼
config.py
 │
 ▼
Ollama
 │
 ▼
Qwen3:4B
```

Every layer has one responsibility.

---

# 10. Roadmap

```
Phase 0

Project Setup
✔

↓

Phase 1

Modular Chat Engine
✔

↓

Phase 2

Conversation Manager

↓

Phase 3

Persistent Memory

↓

Phase 4

Vector Database

↓

Phase 5

Research Assistant

↓

Phase 6

Voice Interface

↓

Phase 7

Health Companion

↓

Phase 8

Multi-Agent AI

↓

Phase 9

ConAI v1.0
```

---

# 11. Lessons Learned

Project Organization

- Never build everything in one file.
- Separate configuration from logic.
- Separate prompts from inference.
- Keep modules independent.

Software Engineering

- Use Git from day one.
- Work in feature branches.
- Write meaningful commit messages.
- Document architectural decisions.

AI Engineering

- Prompt engineering should remain separate.
- Model communication should remain abstract.
- Measure performance before optimization.
- Build with future expansion in mind.

---

# 12. Engineering Notes

Every future module added to ConAI should answer these questions.

## Problem

What issue does this module solve?

---

## Solution

How is the problem solved?

---

## Why This Design?

Why was this architecture chosen?

---

## Alternatives Considered

What other approaches were evaluated?

Why were they rejected?

---

## Industry Practice

How do professional AI systems typically solve this problem?

---

## Future Impact

Which upcoming modules depend on this decision?

---

This section must be updated whenever a major architectural change is introduced.
