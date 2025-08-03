# petabyte
petabyte cloud code!

This repository documents the relationship between the two core components of the **petabyte** decentralized cloud platform:

- [`lumaris_agent`](https://github.com/BDR-Pro/lumaris_agent)
- [`lumaris_api`](https://github.com/BDR-Pro/lumaris_api)

## 🌐 Website 

[Visit the Landing Page](https://52101422ef55413ca04c4499cc498285-main.projects.builder.my/)

## 🔧 What is Lumaris?

**Lumaris** is a decentralized marketplace for computing power. It allows resource providers (sellers) to share CPU, GPU, and storage with buyers who need scalable and affordable computing — similar to AWS EC2, but in a peer-to-peer model.

---

## 📦 Repository Breakdown

### [`lumaris_agent`](https://github.com/BDR-Pro/lumaris_agent)

> **Role**: The lightweight node agent installed on seller machines.

**Key Responsibilities:**

- Registers and authenticates the seller node with the Lumaris backend.
- Exposes resource availability (CPU, RAM, GPU, etc.) to the central system.
- Receives and executes buyer workloads in isolated environments (e.g., VMs or containers).
- Maintains secure communication with the backend (TLS/mTLS).
- Provides health monitoring and uptime metrics for reward calculations.

**Technology Stack**:
- Python-based
- Uses system-level resource reporting and sandboxing tools

---

### [`lumaris_api`](https://github.com/BDR-Pro/lumaris_api)

> **Role**: The centralized API and matchmaking engine (control plane).

**Key Responsibilities:**

- Handles user registration, authentication, and API key management.
- Matches buyers to available sellers based on resource requirements and region.
- Manages job submission, pricing, and escrow/payment flows.
- Stores metadata about nodes, workloads, and transactions.
- Exposes both REST and WebSocket APIs for integration with the frontend or CLI.

**Technology Stack**:
- Python (FastAPI)
- PostgreSQL for persistent data
- Redis or similar for in-memory queues or real-time tasks

---

## 🔗 How They Work Together

1. **Startup**: A seller installs and runs `lumaris_agent`, which connects to `lumaris_api` to authenticate and report availability.
2. **Job Submission**: A buyer uses the API to request resources.
3. **Matchmaking**: `lumaris_api` selects a suitable seller node and dispatches the workload to the corresponding agent.
4. **Execution**: `lumaris_agent` runs the job, monitors its state, and reports progress/results back to the API.
5. **Payment and Logs**: On successful job completion, `lumaris_api` triggers payment flows and retains logs or artifacts if required.

---

## 🚧 Future Plans

- Token-based rewards for high-uptime agents
- Web-based dashboard for both buyers and sellers
- Enhanced security via encrypted disk I/O and ZK-proofs

---

## 🧠 Why Separate Repos?

Keeping `agent` and `api` in separate repositories allows for:

- Independent versioning and deployment
- Clear separation of responsibilities
- Easier contribution and testing for specific subsystems

---

## 📁 This Repo

This documentation repo serves as the architectural overview and index for the Lumaris project. It may also contain:

- Diagrams
- Developer onboarding notes
- Contribution guides
- CI/CD pipeline descriptions

---

## 📬 Contact

For business inquiries, integration discussions, or bug reports, please open an issue
