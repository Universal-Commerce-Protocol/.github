# Checkout Capability

- **Capability Name:** `dev.ucp.shopping.checkout`

## Overview

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHALL**, **SHOULD**, and
**MAY** in this document are to be interpreted as described in RFC 2119.

## Continue URL

When `continue_url` is present, the platform **MUST** redirect the buyer to it.

The business **MUST NOT** reuse an idempotency key.

Platforms retry on failure, and businesses MUST respond within the timeout.

The literal `MUST` inside a code span is a value, not an obligation.

```text
The platform MUST ignore everything inside a fenced block.
```

## Session Teardown

The host **MUST** tear down the context and **MAY** redirect the buyer.

**Business responsibilities:**

- **MUST** validate the cart before completing checkout.
- **SHOULD** log every rejected request.
