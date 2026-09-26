# Betrayer Framework

**Betrayer** is a Python web application framework designed with an **LLM-first architecture**.

The primary goal is not to reproduce every feature of existing frameworks, but to make application development **easy for LLM coding agents** while remaining practical and understandable for human developers.

> **Build the framework so an LLM can use it without having to understand its internal implementation.**

## Status

🚧 **Active Development — Not Production Ready**

Betrayer is still being developed and its APIs, architecture, generators, and conventions may change.

The framework is currently focused on establishing its core architecture and an LLM-friendly development workflow.

## What Betrayer Is

Betrayer is a modular Python web framework providing building blocks for application development, including:

* Application and bootstrap lifecycle
* Configuration and environment management
* Module system
* Service layer
* Database and data layer
* Migration system
* HTTP resources and APIs
* CRUD resources
* CLI and code generators
* Infrastructure services
* Validation and diagnostics
* Testing support
* Realtime / WebSocket support
* Background jobs and scheduling
* LLM-oriented framework metadata and capabilities

The framework is designed around clear boundaries between these components so that they can evolve independently.

## LLM-First

The most important design principle of Betrayer is **LLM-first development**.

An LLM should not need to inspect the framework's source code every time it wants to use a feature.

For example, an agent should be able to understand:

```text
Create a CRUD resource
```

from a concise capability/contract description and then use it directly.

It should **not** need to:

```text
find class
→ open source file
→ inspect implementation
→ trace dependencies
→ understand internal architecture
→ figure out how to call it
```

Instead:

```text
discover capability
→ understand contract
→ call capability
→ receive structured result
```

This makes the framework easier for both autonomous coding agents and human developers.

## Design Principles

Betrayer is being developed around several principles:

1. **LLM First**
   Framework capabilities should be directly consumable by coding agents.

2. **Convention Over Investigation**
   Common tasks should have one obvious way to accomplish them.

3. **Minimal Context**
   An agent should not need to read large portions of the framework to perform normal tasks.

4. **Structured Interfaces**
   Commands, capabilities, errors, and results should be machine-readable whenever practical.

5. **Modular Architecture**
   Components should remain replaceable and independently maintainable.

6. **Batteries Included Where Useful**
   Common application infrastructure should be provided instead of forcing agents to recreate it.

7. **Framework, Not Agent**
   Betrayer provides capabilities and contracts. The LLM remains responsible for reasoning and deciding what to do.

8. **Human Compatible**
   Although optimized for LLM agents, applications built with Betrayer should remain understandable and maintainable by humans.

## Current Architecture

The framework is being built around a layered application model:

```text
Application
    │
    ├── Core / Bootstrap
    │
    ├── Module
    │
    ├── Web / Resource
    │
    ├── Service
    │
    ├── Repository / Data
    │
    └── Database
```

Additional infrastructure such as jobs, queues, scheduling, events, caching, validation, diagnostics, and realtime communication is being developed around these core layers.

## CLI

Betrayer provides a CLI for creating and managing application components.

Examples:

```bash
bet create myapp

bet make module users

bet make service user

bet make resource user

bet make crud product
```

The CLI and generators are intended to produce useful application code rather than merely empty boilerplate.

## Development Philosophy

Betrayer is **not trying to win by having the most features**.

The main question behind every feature is:

> **Does this make an LLM agent faster, more reliable, and less dependent on inspecting framework internals?**

A feature that adds complexity without improving the development workflow is not automatically valuable.

The long-term goal is a framework where an agent can build an application through a small number of predictable operations:

```text
Understand the application requirement
        ↓
Discover available capabilities
        ↓
Use the framework contracts
        ↓
Generate / modify application code
        ↓
Run and validate
        ↓
Diagnose and fix
```

without repeatedly reverse-engineering the framework itself.

## Relationship With Coding Agents

Betrayer is framework-agnostic from the perspective of the coding agent.

A coding agent such as AETHER should be able to use Betrayer through its documented capabilities and contracts without requiring special knowledge of Betrayer's internal source code.

The goal is:

```text
Agent
  │
  │ generic capability / contract
  ▼
Betrayer
  │
  ▼
Application
```

rather than coupling the agent directly to Betrayer's internal classes.

## Development Roadmap

The project is being developed incrementally.

Current major areas include:

* Core Foundation
* Configuration
* Database
* Migration
* Module System
* Service Layer
* CLI & Generators
* Resource / API
* Database E2E & ORM
* Golden Path Integration
* Validation & Request Pipeline
* Testing System
* Diagnostics & Developer Tools
* Events / Jobs / Queue / Scheduler
* WebSocket / Realtime
* Application Essentials
* LLM Intelligence
* Architecture Guard
* Framework Discoverability
* Final Integration & LLM Benchmark

The roadmap is intentionally focused on **LLM usability and development efficiency**, rather than simply matching the feature list of existing frameworks.

## Project Status

Betrayer is currently **under active development**.

Some parts of the framework are already implemented and tested, while other major subsystems are still being built.

Therefore:

* APIs may change.
* Architecture may evolve.
* Some features are incomplete.
* Production use is not recommended yet.

The repository represents an evolving framework rather than a finished stable release.

---

**Betrayer Framework**

*A Python web framework designed to be easy for LLMs to use.*
