# AMPP — Autonomous Merchant Protocol Proxy

> **AI can negotiate the deal. Deterministic policy decides whether money can move.**

AMPP (Autonomous Merchant Protocol Proxy) is a protocol-oriented commerce gateway designed for autonomous AI agents.

Traditional e-commerce assumes a human is present at checkout. Autonomous agents need a safer transaction layer that allows them to discover products, negotiate commercial terms, request payment, and complete fulfillment — while ensuring that an AI model cannot independently authorize spending.

AMPP creates that boundary.

---

## The Problem

Today's commerce flow is designed around a human:

```text
Search → Select → Checkout → Pay
```

An autonomous agent needs a different transaction flow:

```text
Discover → Negotiate → Authorize → Pay → Fulfill
```

The core security problem is:

> **How do we allow an AI agent to negotiate a transaction without giving the AI authority to spend money?**

AMPP solves this by separating **commercial intelligence** from **transaction authorization**.

---

## Core Principle

```text
                         AI / LLM
                            │
                            │ Commercial suggestion
                            ▼
                    ┌───────────────┐
                    │   Negotiation │
                    └───────┬───────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │ DETERMINISTIC TRUST     │
              │ BOUNDARY                │
              │                         │
              │ • Signature             │
              │ • Expiry                │
              │ • Merchant              │
              │ • Budget                │
              │ • Quantity              │
              │ • Price Policy          │
              │ • Replay Protection     │
              └────────────┬────────────┘
                           │
                       AUTHORIZED
                           │
                           ▼
                        PAYMENT
```

**The LLM is outside the authorization boundary.**

Gemini can suggest a price and provide reasoning, but it cannot:

* increase the user's spending limit
* change the authorized merchant
* increase the permitted quantity
* bypass price policy
* authorize payment
* bypass mandate verification

Every AI-generated commercial proposal is independently validated by deterministic policy.

---

# Architecture

```text
                         HUMAN
                           │
                           │ Signed Spending Mandate
                           ▼
                    ┌───────────────┐
                    │  BUYER AGENT  │
                    └───────┬───────┘
                            │
                    Discovery + Intent
                            │
                            ▼
                    ┌───────────────┐
                    │  AMPP PROXY   │
                    └───────┬───────┘
                            │
              ┌─────────────┴─────────────┐
              │                           │
              ▼                           ▼
       Gemini Negotiator          Deterministic Trust
       Commercial Suggestion            Boundary
              │                           │
              └─────────────┬─────────────┘
                            │
                            ▼
                    POLICY APPROVED
                            │
                            ▼
                   INVENTORY HOLD (60s)
                            │
                            ▼
                  HTTP 402 / x402
                            │
                            ▼
                   RAZORPAY ADAPTER
                            │
                            ▼
                  PAYMENT VERIFICATION
                            │
                            ▼
                       SETTLEMENT
                            │
                            ▼
                   INVENTORY COMMIT
                            │
                            ▼
                 FULFILLMENT RECEIPT
```

---

# Autonomous Transaction Flow

## 1. Spending Mandate

The human establishes the agent's spending authority through a signed mandate.

The mandate defines constraints such as:

* Maximum spending amount
* Authorized merchant
* Currency
* Product category
* Maximum quantity
* Validity period

The mandate is cryptographically signed using **Ed25519**.

---

## 2. Agent Discovery

AMPP exposes an agent discovery manifest:

```http
GET /.well-known/agent-manifest.json
```

This allows an agent to discover the merchant's autonomous-commerce capabilities.

---

## 3. Purchase Proposal & Negotiation

The buyer agent submits a purchase proposal:

```http
POST /api/v1/agent/negotiate
```

The proposal contains information such as:

* Transaction ID
* Merchant
* SKU
* Quantity
* Requested price
* Category
* Region
* Signed spending mandate

AMPP verifies the mandate and its constraints before allowing negotiation to proceed.

---

## 4. AI Negotiation

Gemini acts as the **commercial negotiation layer**.

It receives transaction context and returns a structured suggestion:

```json
{
  "decision": "ACCEPT",
  "suggested_unit_price": 4650,
  "reason": "The requested price is within a reasonable range."
}
```

The AI result is treated as an **untrusted suggestion**.

It is never treated as authorization.

The dashboard exposes:

```text
Requested Price
Gemini Suggestion
Approved Price
Decision
AI Reasoning
```

This makes the separation between AI negotiation and deterministic authorization visible to the user.

---

## 5. Deterministic Trust Boundary

The AI-generated commercial terms are passed through deterministic policy validation.

The system checks:

* Ed25519 mandate signature
* Mandate expiry
* Authorized merchant
* Currency
* Maximum spend
* Maximum quantity
* Authorized category
* Merchant pricing policy
* Transaction state
* Replay/idempotency constraints

Only after these checks pass can the transaction proceed.

```text
Requested Price
      │
      ▼
Mandate Verification
      │
      ▼
Gemini Suggestion
      │
      ▼
Deterministic Policy
      │
      ▼
Approved Price
```

### Key security property

> **AI proposes. Deterministic policy authorizes.**

---

# Inventory Reservation

Once the transaction is authorized, AMPP creates a temporary inventory hold.

The current hold duration is:

```text
60 seconds
```

The hold prevents the product from being committed indefinitely while payment is being completed.

If the hold expires, the transaction is transitioned to an expired state and the inventory becomes available again.

---

# HTTP 402 / x402 Payment Challenge

After authorization and inventory reservation, AMPP exposes a payment challenge:

```http
GET /api/v1/agent/transactions/{transaction_id}/payment
```

The endpoint returns an HTTP `402 Payment Required` challenge containing:

* Protocol
* Version
* Amount
* Currency
* Transaction ID
* Hold token
* Expiry
* Settlement rail

AMPP uses **x402-style payment semantics**, with Razorpay acting as the payment/settlement rail.

---

# Razorpay Payment Flow

The authorized transaction proceeds through:

```text
Payment Challenge
       │
       ▼
Razorpay Order
       │
       ▼
Payment
       │
       ▼
Payment Signature Verification
       │
       ▼
Payment Settlement
       │
       ▼
Inventory Commit
       │
       ▼
Fulfillment
```

Razorpay payment signatures are verified using HMAC-SHA256 before the payment is accepted.

The implementation currently uses **Razorpay Test Mode** for demonstration.

---

# Transaction State Machine

AMPP maintains an explicit transaction lifecycle:

```text
PROPOSED
    ↓
VALIDATED
    ↓
HELD
    ↓
PAYMENT_PENDING
    ↓
PAYMENT_VERIFIED
    ↓
SETTLING
    ↓
SETTLED
    ↓
INVENTORY_COMMITTED
    ↓
COMPLETED
```

Failure and timeout states include:

```text
EXPIRED
RELEASED
FAILED
```

Explicit state transitions prevent invalid operations from being performed out of order.

---

# Fulfillment Receipt

After successful settlement and inventory commitment, AMPP generates a fulfillment receipt containing:

* Receipt ID
* Transaction ID
* Merchant
* Payment ID
* Amount
* Currency
* SKU
* Quantity
* Issuance timestamp
* Receipt digest

The receipt digest provides a tamper-evident representation of the receipt contents.

---

# Security Model

AMPP follows a simple security principle:

> **AI proposes. Policy authorizes. Payment executes.**

### Threat → Defense

| Threat                       | Defense                                   |
| ---------------------------- | ----------------------------------------- |
| AI exceeds spending limit    | Signed mandate + maximum-spend validation |
| AI changes merchant          | Merchant binding                          |
| AI increases quantity        | Quantity constraint                       |
| AI suggests an invalid price | Deterministic merchant policy             |
| Forged mandate               | Ed25519 signature verification            |
| Expired mandate              | Timestamp validation                      |
| Expired inventory hold       | 60-second TTL                             |
| Replayed transaction         | Idempotency / nonce protection            |
| Fake payment                 | Razorpay HMAC verification                |
| Payment/order failure        | Explicit `FAILED` state                   |
| Invalid transaction sequence | Transaction state machine                 |

The most important security boundary is:

```text
             UNTRUSTED
                 │
          ┌──────▼──────┐
          │  Gemini AI  │
          └──────┬──────┘
                 │
                 │ Suggestion
                 ▼
        ┌───────────────────┐
        │ Deterministic     │
        │ Trust Boundary    │
        └─────────┬─────────┘
                  │
              AUTHORIZED
                  │
                  ▼
               PAYMENT
```

---

# Technology Stack

## Backend

* Python
* FastAPI
* Pydantic
* Ed25519 cryptographic signatures
* Google Gemini API
* Razorpay API
* Requests

## Frontend

* React
* Vite
* JavaScript
* `@noble/ed25519`

## Testing

* pytest
* End-to-end transaction tests
* Transaction state-machine validation
* Payment verification tests
* Inventory expiry tests
* Failure-path tests

---

# API Endpoints

## Agent Discovery

```http
GET /.well-known/agent-manifest.json
```

Returns the merchant's autonomous-commerce capabilities.

---

## Negotiation

```http
POST /api/v1/agent/negotiate
```

Validates the mandate, obtains an AI negotiation suggestion, applies deterministic policy, reserves inventory, and creates a transaction deal.

---

## Payment Challenge

```http
GET /api/v1/agent/transactions/{transaction_id}/payment
```

Returns an HTTP 402 payment challenge for the authorized transaction.

---

## Create Payment Order

```http
POST /api/v1/agent/settle
```

Creates the payment order through the configured Razorpay settlement adapter.

---

## Verify Payment

```http
POST /api/v1/agent/verify-payment
```

Verifies the Razorpay payment signature.

---

## Settle Payment

```http
POST /api/v1/agent/settle-payment
```

Moves the verified payment into the settlement stage.

---

## Commit Inventory

```http
POST /api/v1/agent/commit-inventory
```

Commits the previously reserved inventory after successful settlement.

---

## Fulfill

```http
POST /api/v1/agent/fulfill
```

Generates the fulfillment receipt for the completed transaction.

---

# Project Structure

```text
merchant-proxy/
│
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
│
├── app/
│   ├── api/
│   │   ├── catalog.py
│   │   ├── manifest.py
│   │   ├── negotiate.py
│   │   └── settle.py
│   │
│   ├── core/
│   │   ├── inventory.py
│   │   ├── mandate.py
│   │   ├── policy.py
│   │   ├── transaction.py
│   │   └── transaction_store.py
│   │
│   ├── models/
│   │   ├── proposal.py
│   │   ├── settlement.py
│   │   └── transaction.py
│   │
│   ├── services/
│   │   ├── deal_store.py
│   │   ├── gemini_negotiator.py
│   │   ├── negotiator.py
│   │   └── razorpay_adapter.py
│   │
│   ├── config.py
│   └── main.py
│
├── tests/
│   └── ...
│
└── frontend/
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.jsx
        ├── App.css
        └── main.jsx
```

---

# Running Locally

## Backend

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file:

```env
GEMINI_API_KEY=
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
```

Start the API:

```bash
uvicorn app.main:app --reload
```

The backend runs at:

```text
http://127.0.0.1:8000
```

Interactive API documentation is available at:

```text
http://127.0.0.1:8000/docs
```

---

## Frontend

From the project root:

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at:

```text
http://localhost:5173
```

---

# Testing

Run the complete test suite:

```bash
pytest -q
```

The test suite covers:

* Mandate validation
* Ed25519 signature verification
* Negotiation
* Deterministic policy
* Inventory holds
* Transaction state transitions
* Payment verification
* Settlement
* Fulfillment
* Replay/idempotency handling
* Expired holds
* Payment/order failures
* End-to-end transaction flow

---

# Protocol Positioning

AMPP is designed around concepts relevant to emerging agentic-commerce infrastructure, including:

* HTTP 402 / x402 payment semantics
* Cryptographically delegated spending authority
* Agent discovery
* Autonomous negotiation
* Protocol-oriented merchant interaction

The implementation uses an **AP2-inspired cryptographic delegation model** rather than claiming full AP2 interoperability.

Similarly:

* **x402** is treated as the payment-challenge protocol layer.
* **Razorpay** is treated as the payment/settlement rail.
* The transaction lifecycle uses explicit inventory and payment states rather than claiming an atomic database/payment transaction.

---

# Design Philosophy

AMPP separates **intelligence** from **authority**.

An LLM is useful for:

* Understanding commercial context
* Suggesting prices
* Negotiating terms
* Providing reasoning

But the LLM should not be trusted with unrestricted financial authority.

Therefore:

```text
LLM
 │
 │ Intelligence
 ▼
Negotiation
 │
 │ Untrusted output
 ▼
Deterministic Trust Boundary
 │
 │ Authorization
 ▼
Payment
 │
 ▼
Fulfillment
```

This allows autonomous agents to negotiate commerce while keeping financial authorization bounded by explicit, verifiable rules.

---

# Demo Flow

The complete demonstration shows:

```text
Signed Spending Mandate
        ↓
Agent Discovery
        ↓
Purchase Proposal
        ↓
Gemini Negotiation
        ↓
Deterministic Authorization
        ↓
Inventory Hold
        ↓
HTTP 402 Payment Challenge
        ↓
Razorpay Test Payment
        ↓
Payment Verification
        ↓
Settlement
        ↓
Inventory Commit
        ↓
Fulfillment Receipt
```

### Core Message

> **Autonomous agents should be able to negotiate like humans, but they should not be able to spend like unrestricted users.**

AMPP provides the boundary between the two.
