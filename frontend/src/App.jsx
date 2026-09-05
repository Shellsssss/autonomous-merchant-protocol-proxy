import { useState } from "react";
import "./App.css";
import * as ed from "@noble/ed25519";

const steps = [
  {
    label: "MANDATE SIGNED",
    description: "Cryptographic spending authority created",
    state: "MANDATE",
  },
  {
    label: "DISCOVERED",
    description: "Merchant capabilities discovered",
    state: "DISCOVERY",
  },
  {
    label: "NEGOTIATED",
    description: "Purchase deal negotiated",
    state: "NEGOTIATION",
  },
  {
    label: "POLICY VERIFIED",
    description: "Deterministic trust boundary passed",
    state: "POLICY",
  },
  {
    label: "INVENTORY HELD",
    description: "Inventory reserved for 60 seconds",
    state: "HOLD",
  },
  {
    label: "HTTP 402",
    description: "x402 payment challenge issued",
    state: "PAYMENT_CHALLENGE",
  },
  {
    label: "PAYMENT VERIFIED",
    description: "Razorpay signature verified",
    state: "PAYMENT_VERIFIED",
  },
  {
    label: "PAYMENT SETTLED",
    description: "Payment settlement completed",
    state: "SETTLED",
  },
  {
    label: "INVENTORY COMMITTED",
    description: "Reserved inventory permanently committed",
    state: "INVENTORY_COMMITTED",
  },
  {
    label: "FULFILLED",
    description: "Signed fulfillment receipt generated",
    state: "COMPLETED",
  },
];

function base64Encode(bytes) {
  let binary = "";

  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }

  return btoa(binary);
}

function stableStringify(value) {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }

  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }

  const keys = Object.keys(value).sort();

  return `{${keys
    .map(
      (key) =>
        `${JSON.stringify(key)}:${stableStringify(value[key])}`
    )
    .join(",")}}`;
}

function canonicalizeMandate(mandate) {
  const payload = { ...mandate };

  delete payload.signature;

  return new TextEncoder().encode(
    stableStringify(payload)
  );
}

async function createSignedMandate({
  maxSpend = 5000,
  category = "electronics",
  maxQuantity = 1,
}) {
  // Generate a fresh Ed25519 key pair
  const privateKey = ed.utils.randomSecretKey();
  const publicKey = await ed.getPublicKeyAsync(privateKey);

  const now = Math.floor(Date.now() / 1000);

  // This structure matches the Python Mandate model
  // and create_signed_mandate() helper.
  const mandate = {
    mandate_id: `mnd_frontend_${crypto.randomUUID()}`,
    subject: "buyer_agent_frontend",
    merchant_id: "merchant_demo_01",

    constraints: {
      max_spend: maxSpend,
      currency: "INR",
      allowed_categories: [category],
      max_quantity: maxQuantity,
    },

    issued_at: now,
    expires_at: now + 300,

    nonce: `frontend_nonce_${crypto.randomUUID()}`,

    public_key: base64Encode(publicKey),

    // The Python implementation excludes this field
    // before signing.
    signature: "placeholder",
  };

  // Create exactly the payload that the backend expects.
  const canonicalPayload = canonicalizeMandate(mandate);

  // Sign it with Ed25519.
  const signature = await ed.signAsync(
    canonicalPayload,
    privateKey
  );

  // Attach the Base64 encoded signature.
  mandate.signature = base64Encode(signature);

  return mandate;
}

function App() {
  const [transaction, setTransaction] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [paymentChallenge, setPaymentChallenge] = useState(null);
  const [paymentOrder, setPaymentOrder] = useState(null);
  const [fulfillmentReceipt, setFulfillmentReceipt] = useState(null);
  const [mandate, setMandate] = useState(null);

  const startAutonomousPurchase = async () => {
    setLoading(true);
    setError(null);
    setPaymentChallenge(null);
    setPaymentOrder(null);

    const transactionId = `txn_frontend_${crypto.randomUUID()}`;

    try {
      // 1. Create signed spending mandate
      const mandate = await createSignedMandate({
        maxSpend: 5000,
        category: "electronics",
        maxQuantity: 1,
      });
      setMandate(mandate);

      // 2. Create purchase proposal
      const proposal = {
        transaction_id: transactionId,
        merchant_id: "merchant_demo_01",
        items: [
          {
            sku: "LAPTOP-PRO-01",
            quantity: 1,
          },
        ],
        requested_unit_price: 4800,
        category: "electronics",
        region: "IN",
        mandate,
      };

      // 3. Negotiate
      const negotiateResponse = await fetch(
        "http://localhost:8000/api/v1/agent/negotiate",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(proposal),
        }
      );

      const deal = await negotiateResponse.json();

      if (!negotiateResponse.ok) {
        const message =
          typeof deal.detail === "object"
            ? deal.detail.message
            : deal.detail || "Negotiation failed.";

        throw new Error(message);
      }

      setTransaction(deal);

      // 4. Request x402 payment challenge
      const paymentResponse = await fetch(
        `http://localhost:8000/api/v1/agent/transactions/${deal.transaction_id}/payment`
      );

      const paymentData = await paymentResponse.json();

      if (paymentResponse.status !== 402) {
        const message =
          typeof paymentData.detail === "object"
            ? paymentData.detail.message
            : paymentData.detail ||
              "Expected an x402 payment challenge.";

        throw new Error(message);
      }

      setPaymentChallenge(paymentData);

      // 5. Request Razorpay order
      const settlementResponse = await fetch(
        "http://localhost:8000/api/v1/agent/settle",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: JSON.stringify({
            transaction_id: deal.transaction_id,
            hold_token: deal.hold_token,
            nonce: crypto.randomUUID() + crypto.randomUUID(),
          }),
        }
      );

      const settlementData = await settlementResponse.json();

      if (!settlementResponse.ok) {
        const message =
          typeof settlementData.detail === "object"
            ? settlementData.detail.message
            : settlementData.detail || "Payment order creation failed.";

        throw new Error(message);
      }

      setPaymentOrder(settlementData);

      // Keep transaction state in sync with backend
      setTransaction((current) => ({
        ...current,
        state: "PAYMENT_PENDING",
      }));
    } catch (err) {
      console.error("Autonomous purchase failed:", err);
      setError(err.message || "Unable to start autonomous purchase.");
    } finally {
      setLoading(false);
    }
  };

  const openRazorpayCheckout = () => {
    if (!paymentOrder || !transaction) {
      setError("No Razorpay order is available.");
      return;
    }

    if (!window.Razorpay) {
      setError("Razorpay Checkout failed to load.");
      return;
    }

    const options = {
      key: import.meta.env.VITE_RAZORPAY_KEY_ID,
      amount: paymentOrder.amount * 100,
      currency: paymentOrder.currency,
      name: "AMPP Demo Merchant",
      description: `Autonomous purchase — ${transaction.sku}`,
      order_id: paymentOrder.payment_id,

      handler: async function (response) {
        try {
          setLoading(true);
          setError(null);

          // 1. Verify payment signature
          const verificationResponse = await fetch(
            "http://localhost:8000/api/v1/agent/verify-payment",
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "Idempotency-Key": crypto.randomUUID(),
              },
              body: JSON.stringify({
                transaction_id: transaction.transaction_id,
                order_id: response.razorpay_order_id,
                payment_id: response.razorpay_payment_id,
                signature: response.razorpay_signature,
              }),
            }
          );

          const verificationData = await verificationResponse.json();

          if (!verificationResponse.ok) {
            const message =
              typeof verificationData.detail === "object"
                ? verificationData.detail.message
                : verificationData.detail || "Payment verification failed.";

            throw new Error(message);
          }

          // Payment signature is verified.
          setTransaction((current) => ({
            ...current,
            state: "PAYMENT_VERIFIED",
          }));

          // 2. Settle the verified payment
          const settlementResponse = await fetch(
            "http://localhost:8000/api/v1/agent/settle-payment",
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "Idempotency-Key": crypto.randomUUID(),
              },
              body: JSON.stringify({
                transaction_id: transaction.transaction_id,
                payment_id: response.razorpay_payment_id,
              }),
            }
          );

          const settlementData = await settlementResponse.json();

          if (!settlementResponse.ok) {
            const message =
              typeof settlementData.detail === "object"
                ? settlementData.detail.message
                : settlementData.detail || "Payment settlement failed.";

            throw new Error(message);
          }

          // Payment is now settled.
          setTransaction((current) => ({
            ...current,
            state: "SETTLED",
          }));

          setPaymentOrder((current) => ({
            ...current,
            payment_id: response.razorpay_payment_id,
            status: settlementData.status,
          }));

          // 3. Commit the inventory hold
          const inventoryResponse = await fetch(
            "http://localhost:8000/api/v1/agent/commit-inventory",
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "Idempotency-Key": crypto.randomUUID(),
              },
              body: JSON.stringify({
                transaction_id: transaction.transaction_id,
                hold_token: transaction.hold_token,
              }),
            }
          );

          const inventoryData = await inventoryResponse.json();

          if (!inventoryResponse.ok) {
            const message =
              typeof inventoryData.detail === "object"
                ? inventoryData.detail.message
                : inventoryData.detail || "Inventory commit failed.";

            throw new Error(message);
          }

          // Inventory has been permanently committed.
          setTransaction((current) => ({
            ...current,
            state: "INVENTORY_COMMITTED",
          }));

          // 4. Generate the fulfillment receipt.
          const fulfillmentResponse = await fetch(
            "http://localhost:8000/api/v1/agent/fulfill",
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "Idempotency-Key": crypto.randomUUID(),
              },
              body: JSON.stringify({
                transaction_id: transaction.transaction_id,
                hold_token: transaction.hold_token,
              }),
            }
          );

          const fulfillmentData = await fulfillmentResponse.json();

          if (!fulfillmentResponse.ok) {
            const message =
              typeof fulfillmentData.detail === "object"
                ? fulfillmentData.detail.message
                : fulfillmentData.detail || "Fulfillment failed.";

            throw new Error(message);
          }

          setFulfillmentReceipt(fulfillmentData);

          setTransaction((current) => ({
            ...current,
            state: "COMPLETED",
          }));
        } catch (err) {
          console.error("Autonomous payment flow failed:", err);
          setError(err.message || "Autonomous payment flow failed.");
        } finally {
          setLoading(false);
        }
      },

      modal: {
        ondismiss: function () {
          console.log("Razorpay Checkout closed.");
        },
      },

      theme: {
        color: "#111111",
      },
    };

    const razorpay = new window.Razorpay(options);

    razorpay.on("payment.failed", function (response) {
      console.error("Razorpay payment failed:", response.error);

      setError(
        response.error?.description || "Razorpay payment failed."
      );
    });

    razorpay.open();
  };

  // Determine the current lifecycle stage.
  const getActiveStep = () => {
  if (!transaction) {
    return -1;
  }

  switch (transaction.state) {
    case "PROPOSED":
      return 2;

    case "VALIDATED":
      return 3;

    case "HELD":
      return 4;

    case "PAYMENT_PENDING":
      return 5;

    case "PAYMENT_VERIFIED":
      return 6;

    case "SETTLING":
      return 7;

    case "SETTLED":
      return 7;

    case "INVENTORY_COMMITTED":
      return 8;

    case "COMPLETED":
      return 9;

    case "EXPIRED":
    case "RELEASED":
    case "FAILED":
      return 0;

    default:
      return 0;
  }
};

  const activeStep = getActiveStep();

  return (
    <div className="app">

      {/* ==================================================
          HEADER
      ================================================== */}

      <header className="topbar">
        <div>
          <div className="brand">AMPP</div>

          <div className="subtitle">
            Autonomous Merchant Protocol Proxy
          </div>
        </div>

        <div className="status">
          <span className="status-dot" />
          SYSTEM ONLINE
        </div>
      </header>


      <main className="dashboard">

        {/* ==================================================
            HERO
        ================================================== */}

        <section className="hero">
          <div className="hero-content">
            <p className="eyebrow">AGENTIC COMMERCE GATEWAY</p>

            <h1>Autonomous Transaction Control</h1>

            <p className="hero-text">
              Discover, negotiate and settle purchases while keeping every
              payment behind a deterministic trust boundary.
            </p>

            <div className="transaction-card">
              <span className="card-label">CURRENT TRANSACTION</span>

              {transaction ? (
                <>
                  <strong>{transaction.sku}</strong>

                  <span className="muted">
                    {transaction.transaction_id}
                  </span>

                  <span className="muted">
                    ₹{transaction.total_amount} · {transaction.quantity} unit
                  </span>

                  {paymentChallenge && (
                    <div className="payment-challenge">
                      <span className="card-label">
                        PAYMENT REQUIRED
                      </span>

                      <strong>HTTP 402 · x402</strong>

                      <span className="muted">
                        ₹{paymentChallenge.amount} {paymentChallenge.currency}
                      </span>

                      <span className="muted">
                        Settlement rail: {paymentChallenge.settlement_rail}
                      </span>
                    </div>
                  )}

                  {paymentOrder && (
                    <div className="payment-order">
                      <span className="card-label">
                        RAZORPAY ORDER
                      </span>

                      <strong>{paymentOrder.payment_id}</strong>

                      <span className="muted">
                        ₹{paymentOrder.amount} {paymentOrder.currency}
                      </span>

                      <span className="verified">
  {transaction?.state === "COMPLETED"
    ? "TRANSACTION COMPLETED"
    : transaction?.state === "INVENTORY_COMMITTED"
      ? "INVENTORY COMMITTED"
      : transaction?.state === "SETTLED"
        ? "PAYMENT SETTLED"
        : transaction?.state === "PAYMENT_VERIFIED"
          ? "PAYMENT VERIFIED"
          : "PAYMENT PENDING"}
</span>
                    </div>
                  )}
                  {fulfillmentReceipt && (
  <div className="receipt-panel">
    <span className="card-label">
      SIGNED FULFILLMENT RECEIPT
    </span>

    <strong>
      {fulfillmentReceipt.receipt_id}
    </strong>

    <span className="verified">
      TRANSACTION COMPLETED ✓
    </span>

    <span className="muted">
      ₹{fulfillmentReceipt.amount}{" "}
      {fulfillmentReceipt.currency}
      {" · "}
      {fulfillmentReceipt.quantity} unit
    </span>

    <span className="receipt-digest">
      {fulfillmentReceipt.receipt_digest}
    </span>
  </div>
)}
                </>
              ) : (
                <>
                  <strong>Waiting for agent</strong>
                  <span className="muted">No active transaction</span>
                </>
              )}

              <button
                className="primary-button"
                onClick={
                  transaction?.state === "COMPLETED" ||
                  transaction?.state === "INVENTORY_COMMITTED" ||
                  transaction?.state === "SETTLED" ||
                  transaction?.state === "PAYMENT_VERIFIED"
                    ? undefined
                    : paymentOrder
                      ? openRazorpayCheckout
                      : startAutonomousPurchase
                }
                disabled={
                  loading ||
                  transaction?.state === "COMPLETED" ||
                  transaction?.state === "INVENTORY_COMMITTED" ||
                  transaction?.state === "SETTLED" ||
                  transaction?.state === "PAYMENT_VERIFIED"
                }
              >
                {loading
                  ? "PROCESSING..."
                  : transaction?.state === "COMPLETED"
                    ? "TRANSACTION COMPLETED ✓"
                    : transaction?.state === "INVENTORY_COMMITTED"
                      ? "INVENTORY COMMITTED ✓"
                      : transaction?.state === "SETTLED"
                        ? "PAYMENT SETTLED ✓"
                        : transaction?.state === "PAYMENT_VERIFIED"
                          ? "PAYMENT VERIFIED ✓"
                          : paymentOrder
                            ? "PAY ₹" + paymentOrder.amount
                            : "START AUTONOMOUS PURCHASE"}
              </button>
            </div>
          </div>
        </section>

        {/* ==================================================
            TRANSACTION LIFECYCLE
        ================================================== */}

        <section className="section">

          <div className="section-header">

            <div>
              <p className="eyebrow">
                TRANSACTION LIFECYCLE
              </p>

              <h2>
                Agent Transaction Flow
              </h2>
            </div>

            <span className="state-badge">
              {transaction
                ? transaction.state
                : "IDLE"}
            </span>

          </div>


          <div className="timeline">
  {steps.map((step, index) => {
    const isCompleted = index <= activeStep;
    const isCurrent = index === activeStep;

    return (
      <div
        className={`step ${
          isCompleted ? "completed" : ""
        } ${isCurrent ? "current" : ""}`}
        key={step.label}
      >
        <div className="step-number">
          {isCompleted ? "✓" : index + 1}
        </div>

        <div>
          <strong>{step.label}</strong>
          <span>{step.description}</span>
        </div>
      </div>
    );
  })}
</div>

        </section>


        {/* ==================================================
    SECURITY + AI
================================================== */}

<section className="showcase-grid">

  {/* SPENDING MANDATE */}

  <div className="panel">

    <p className="eyebrow">
      SPENDING MANDATE
    </p>

    <h3>
      Policy Boundary
    </h3>

    <div className="policy-row">
      <span>Maximum budget</span>
      <strong>₹5,000</strong>
    </div>

    <div className="policy-row">
      <span>Merchant</span>
      <strong>AMPP Demo Merchant</strong>
    </div>

    <div className="policy-row">
      <span>Quantity limit</span>
      <strong>1 unit</strong>
    </div>

    <div className="policy-row">
      <span>Category</span>
      <strong>Electronics</strong>
    </div>

    <div className="policy-row">
      <span>Ed25519 signature</span>

      <span className="verified">
        {transaction ? "VERIFIED" : "READY"}
      </span>
    </div>

  </div>


  {/* AI NEGOTIATION */}

<div className="panel">

  <p className="eyebrow">
    AI NEGOTIATION
  </p>

  <h3>
    Gemini Deal Analysis
  </h3>

  <div className="policy-row">
    <span>Requested price</span>

    <strong>
      {transaction?.requested_unit_price
        ? `₹${transaction.requested_unit_price}`
        : "₹4,800"}
    </strong>
  </div>

  <div className="policy-row">
    <span>Gemini suggestion</span>

    <strong>
      {transaction?.ai_suggested_unit_price
        ? `₹${transaction.ai_suggested_unit_price}`
        : "—"}
    </strong>
  </div>

  <div className="policy-row">
    <span>Approved price</span>

    <strong>
      {transaction
        ? `₹${transaction.approved_unit_price}`
        : "—"}
    </strong>
  </div>

  <div className="policy-row">
    <span>Decision</span>

    <span className="verified">
      {transaction?.ai_decision || "WAITING"}
    </span>
  </div>

  <div className="ai-note">

    <strong>AI reasoning</strong>

    <div style={{ marginTop: "8px" }}>
      {transaction?.ai_reason ||
        "Gemini negotiation has not started yet."}
    </div>

  </div>

  <div className="trust-statement">
    AI can negotiate the commercial terms.
    <br />
    It cannot authorize spending.
  </div>

</div>


  {/* TRUST BOUNDARY */}

  <div className="panel">

    <p className="eyebrow">
      TRUST BOUNDARY
    </p>

    <h3>
      Deterministic Authorization
    </h3>

    <div className="checks">

      <div>✓ Cryptographic signature</div>
      <div>✓ Mandate expiry</div>

      <div>✓ Merchant authorization</div>
      <div>✓ Spending limit</div>

      <div>✓ Category authorization</div>
      <div>✓ Quantity limit</div>

      <div>✓ Deterministic floor price</div>
      <div>✓ Replay protection</div>

    </div>

    <div className="trust-statement">
      Gemini proposes.
      <br />
      Deterministic policy authorizes.
    </div>

  </div>


  {/* PAYMENT PROTOCOL */}

  <div className="panel">

    <p className="eyebrow">
      PAYMENT PROTOCOL
    </p>

    <h3>
      x402 → Razorpay
    </h3>

    <div className="policy-row">
      <span>Protocol</span>
      <strong>x402</strong>
    </div>

    <div className="policy-row">
      <span>Settlement rail</span>
      <strong>Razorpay</strong>
    </div>

    <div className="policy-row">
      <span>Amount</span>
      <strong>
        {transaction
          ? `₹${transaction.total_amount}`
          : "—"}
      </strong>
    </div>

    <div className="policy-row">
      <span>Status</span>

      <span className="verified">
        {transaction?.state || "READY"}
      </span>
    </div>

  </div>

</section>

        {/* ==================================================
            ERROR
        ================================================== */}

        {error && (
          <div className="error-message">
            <strong>
              Transaction rejected
            </strong>

            <span>
              {error}
            </span>
          </div>
        )}
      </main>

    </div>
  );
}

export default App;