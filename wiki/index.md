# Petabyte — Wiki

Welcome. **Petabyte is a marketplace for GPU compute.** People who need GPUs rent them by the hour
from people who have GPUs sitting idle — at a fraction of hyperscaler prices — with money held in
**escrow** until the work is actually done.

This wiki is the front door for new users. It explains what Petabyte is, how the pieces fit
together, and exactly how to do the common things as a **buyer** (rent compute) or a **seller**
(earn from your hardware).

> **Two ways to read this**
> - In the repo: browse the Markdown files in `wiki/` (this folder).
> - In the running app: open **`/wiki`** — the same pages rendered as a native, themed
>   page in the site, with a heading-driven sidebar (no external dependencies).

## Start here

| If you want to… | Read |
|---|---|
| Understand what Petabyte is and how it's built | [Overview & architecture](overview.md) |
| Get running in 5 minutes | [Getting started](getting-started.md) |
| Rent GPUs and run jobs | [For buyers](buyers.md) |
| Earn from a GPU you own | [For sellers](sellers.md) |
| Use the command line | [CLI](cli.md) |
| Download & run open models (Llama, Qwen, …) | [Models](models.md) |
| Keep data between runs | [Persistent storage](storage.md) |
| Set up a team, roles, 2FA | [Teams & security](teams-and-security.md) |
| Understand billing, escrow, trust | [Payments & trust](payments-and-trust.md) |
| Call the API | [API & keys](api.md) |
| Run your own Petabyte | [Self-hosting](self-hosting.md) |
| Look up a term | [Glossary](glossary.md) |

## The one-paragraph version

A **seller** installs a small **agent** on a machine with a GPU; the agent proves the GPU is real,
lists it, and waits for work. A **buyer** adds funds, picks a GPU (or lets Petabyte pick the
cheapest match), and runs a job or launches a VM. The buyer's money sits in **escrow**; when the job
finishes it's released to the seller minus a platform fee, and if a node drops the buyer is
**refunded**. Everything a buyer or seller needs is in the **web console** (`/console`) or the
**`petabyte` CLI** — and open AI models can be discovered and installed with one command from the
**model hub** (`/models`).

## Is this real money?

Petabyte runs in **TEST MODE** by default — a sandbox where no real card is charged and no real
money moves, so you can try the whole flow safely. Every money screen shows a clear **TEST MODE**
banner when the sandbox is active. See [Payments & trust](payments-and-trust.md).
