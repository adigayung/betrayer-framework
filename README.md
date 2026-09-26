# Betrayer Framework

**Betrayer** is a **general-purpose Python application framework designed with an LLM-first architecture**.

Betrayer is not limited to web applications. It provides a common application foundation that can be used to build different kinds of software — from CLI tools and APIs to web applications, workers, automation systems, AI applications, and other application types.

> **Build applications with less code, less reasoning, fewer tool calls, fewer tokens, and less ambiguity.**

## Status

**Active Development — Not Production Ready**

Betrayer is currently under active development. Core architecture and capabilities are still evolving.

The current implementation focuses on establishing the foundation and proving the framework through real application workflows, especially application structure, CLI, database, migration, resource/API, and code generation.

---

## What is Betrayer?

Betrayer is an **application framework**, not a framework tied to one type of application.

A project built with Betrayer can choose the capabilities it needs.

For example:

```text
Bersuara
├── CLI
├── API
├── Web UI
├── Worker
├── Scheduler
├── AI / ML
└── Storage
```

Another project may only need:

```text
MyTool
└── CLI
```

Or:

```text
MyService
├── API
└── Worker
```

The framework does not require every application to use HTTP, a database, or a web interface.

Web and database capabilities are simply some of the capabilities currently being developed.

---

## Why LLM-First?

Betrayer is designed primarily to make application development easier for **LLMs and coding agents**.

Traditional frameworks are often designed around human developers navigating documentation, source code, abstractions, and configuration.

Betrayer takes a different approach.

The framework should expose clear, predictable capabilities so an LLM can do this:

```text
Requirement
    ↓
Discover capability
    ↓
Understand contract
    ↓
Use capability
    ↓
Get structured result
```

Instead of:

```text
Requirement
    ↓
List files
    ↓
Read framework source
    ↓
Trace classes
    ↓
Understand dependencies
    ↓
Figure out conventions
    ↓
Implement manually
```

The goal is to hide framework complexity **inside the framework**, rather than forcing the LLM to understand that complexity.

### LLM Surface ≠ Internal Surface

Betrayer may internally contain complex systems and abstractions.

That is acceptable.

The important part is that this complexity should not become unnecessary cognitive work for the LLM.

The LLM should primarily need to understand:

* What capability exists
* What input it accepts
* How to invoke it
* What it produces
* What can fail
* What to do next

It should not normally need to understand how the framework internally implements the capability.

---

## Design Principles

Betrayer is guided by eight primary goals:

1. **Less file reading**
   Minimize the amount of framework and project source the LLM needs to inspect.

2. **Less reasoning**
   Provide predictable architecture and canonical ways of doing things.

3. **Fewer tool calls**
   Prefer operations that accomplish complete tasks instead of many small operations.

4. **Fewer tokens**
   Reduce unnecessary context, boilerplate, and output.

5. **Less ambiguity**
   Prefer one obvious convention over multiple equivalent approaches.

6. **Faster API discovery**
   Make capabilities easy for an LLM to discover and understand.

7. **Faster code generation**
   Provide generators, conventions, and reusable application structures.

8. **Faster error recovery**
   Provide structured, actionable errors and diagnostics so an LLM can identify and fix problems quickly.

The core question for every feature is:

> **Does this make an LLM build an application faster with less reading, reasoning, tool calls, tokens, and ambiguity?**

If not, the feature or abstraction should be reconsidered or simplified.

---

## Application Foundation

Betrayer provides a common foundation for applications.

The architecture is intended to grow around capabilities rather than forcing one application type.

```text
                         BETRAYER
                            │
                  Application Foundation
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
         Core              CLI            Generators
          │                 │                 │
          ├── Config        │                 │
          ├── Module        │          Project Generator
          ├── Service       │          Module Generator
          ├── Container     │          Resource Generator
          ├── Application   │          CRUD Generator
          └── ...           │          Migration Generator
                            │
             ┌──────────────┼──────────────┐
             │              │              │
            Web          Database        Future
             │              │              │
            API            ORM          Worker
            HTTP         Migration      Queue
            Resource     Repository      Scheduler
            Routing      Transaction     Events
             │              │              │
             └──────────────┴──────────────┘
```

These capabilities are composable.

An application can use only the parts it needs.

---

## Example: Bersuara

For example, suppose we want to build an AI music application called **Bersuara**.

Betrayer can provide the application foundation:

```text
Bersuara
│
├── CLI
│
├── API
│
├── Web UI
│
├── Worker
│
├── Storage
│
└── Database
```

The domain-specific logic remains inside Bersuara:

```text
Prompt
   ↓
Music Generation Service
   ↓
AI Model / Inference Engine
   ↓
Audio Processing
   ↓
Storage
   ↓
Result
```

Betrayer does not need to know how the music generation model works.

It provides the application infrastructure around it.

The same principle can be used for completely different applications.

---

## Current Capabilities

The current development roadmap includes:

* Application and bootstrap foundation
* Configuration
* Dependency/container foundation
* Module system
* Service layer
* CLI
* Project generators
* Resource generators
* CRUD generators
* Migration generators
* Extension generators
* Database abstraction
* ORM / query builder
* Repository
* HTTP/API resources
* Validation
* Testing
* Diagnostics
* Jobs and workers
* Queue
* Scheduler
* WebSocket / realtime
* Authentication and authorization
* Cache and pagination
* LLM capability contracts
* Framework discoverability
* Architecture validation
* Application integration

Not every application will need every capability.

---

## LLM Capability Contracts

One of the important parts of Betrayer is making framework capabilities discoverable by machines.

Instead of requiring an LLM to inspect framework source code, capabilities can expose contracts describing:

```text
Capability
Purpose
Input
Usage
Output
Errors
Next Steps
Dependencies
Side Effects
Examples
```

For example:

```json
{
  "capability": "crud.create",
  "purpose": "Create a complete CRUD resource",
  "input": {
    "name": "string"
  },
  "usage": "bet make crud <name>",
  "output": [
    "model",
    "repository",
    "service",
    "routes",
    "module"
  ]
}
```

This allows coding agents to interact with Betrayer through a stable capability surface instead of depending on internal framework implementation details.

---

## CLI

The CLI is one of the primary interfaces for interacting with Betrayer.

Examples:

```bash
bet create project
bet make module users
bet make resource product
bet make service payment
bet make crud product
bet make migration create_products_table
```

Generators are important because they allow an LLM to create complete framework structures with a small number of commands rather than manually creating and configuring many files.

---

## Current Architecture Direction

The framework is intentionally modular.

A simplified application can look like:

```text
Application
    │
    ├── Module
    │
    ├── Service
    │
    ├── Resource / Interface
    │
    ├── Repository
    │
    └── Infrastructure
```

For database-backed applications:

```text
Model
  ↓
Query
  ↓
Repository
  ↓
Database
```

For web/API applications:

```text
Request
  ↓
Resource
  ↓
Service
  ↓
Repository
  ↓
Database
```

These are capabilities provided by Betrayer, not requirements imposed on every application.

---

## Roadmap

The current roadmap is organized into the following major stages:

|  # | Stage                             | Status |
| -: | --------------------------------- | :----: |
| 01 | Core Foundation                   |    ✅   |
| 02 | Configuration                     |    ✅   |
| 03 | Database Foundation               |    ✅   |
| 04 | Migration                         |    ✅   |
| 05 | Module System                     |    ✅   |
| 06 | Service Layer                     |    ✅   |
| 07 | CLI & Generator                   |    ✅   |
| 08 | Resource / API                    |    ✅   |
| 09 | Database E2E & ORM                |   🔴   |
| 10 | Golden Path Integration           |   🔴   |
| 11 | Validation & Request Pipeline     |    ⏳   |
| 12 | Testing System                    |    ⏳   |
| 13 | Diagnostics & Developer Tools     |    ⏳   |
| 14 | Events / Jobs / Queue / Scheduler |    ⏳   |
| 15 | WebSocket / Realtime              |    ⏳   |
| 16 | Application Essentials            |    ⏳   |
| 17 | LLM Intelligence                  |    ⏳   |
| 18 | Architecture Guard                |    ⏳   |
| 19 | Framework Discoverability         |    ⏳   |
| 20 | Final Integration & LLM Benchmark |    ⏳   |

The roadmap is not intended to turn Betrayer into a feature-heavy clone of another framework.

The objective is to build capabilities that materially reduce the work required for an LLM to create and maintain real applications.

---

## Development Philosophy

Betrayer prioritizes:

```text
LLM efficiency
    ↓
Application simplicity
    ↓
Predictable architecture
    ↓
Composable capabilities
    ↓
Real working applications
```

Features are not valuable merely because they exist.

A feature is valuable when it helps an application — and especially an LLM building that application — accomplish its work with less unnecessary complexity.

---

## Relationship With Coding Agents

Betrayer is designed to work naturally with coding agents.

A coding agent should not need special knowledge of Betrayer's internal source code.

Instead, the framework should expose generic, machine-readable capabilities that any compatible agent can discover and use.

Conceptually:

```text
Coding Agent
     │
     │ generic capability interface
     ↓
Betrayer
     │
     ├── Application
     ├── CLI
     ├── Generators
     ├── Database
     ├── Web/API
     ├── Workers
     └── Other capabilities
```

This keeps the framework independent from any particular coding agent.

---

## Project Status

Betrayer is an experimental framework under active development.

The architecture, APIs, generators, and capabilities may change as the project evolves.

The current priority is not production readiness or feature completeness.

The priority is proving the core idea:

> **Can a general-purpose application framework make it significantly easier for an LLM to build, understand, debug, and extend real applications?**

That is the direction of Betrayer.
