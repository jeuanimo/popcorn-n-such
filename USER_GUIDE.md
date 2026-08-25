# Popcorn N Such — Staff & Customer Guide

> Auto-maintained alongside the codebase. Last updated: 2026-05-21.

---

## Table of Contents

**For Customers**
- [Your Account & Dashboard](#your-account--dashboard)
- [Shopping & Checkout](#shopping--checkout)
- [Order History](#order-history)
- [Shipment Tracking](#shipment-tracking)
- [Reorder & Subscribe & Save](#reorder--subscribe--save)
- [Managing Subscriptions](#managing-subscriptions)

**For Staff & Admins**
- [Staff Portal Overview](#staff-portal-overview)
- [Order Management](#order-management)
- [Shipping Labels](#shipping-labels)
  - [Generating a Label](#generating-a-label)
  - [Draft Labels (No Carrier Credentials)](#draft-labels-no-carrier-credentials)
  - [Reprinting & Downloading](#reprinting--downloading)
  - [Thermal Printer Setup (QZ Tray)](#thermal-printer-setup-qz-tray)
- [Tracking Updates for Buyers](#tracking-updates-for-buyers)
- [Operational Settings](#operational-settings)
  - [Business / Ship-From Address](#business--ship-from-address)
  - [Shipping Provider & Rates](#shipping-provider--rates)
  - [Label Printer (QZ Tray)](#label-printer-qz-tray)
  - [Pitney Bowes API](#pitney-bowes-api)
  - [GoDaddy Payments](#godaddy-payments)
  - [Payments: refunds and unconfirmed charges](#payments-refunds-and-unconfirmed-charges)
  - [Email / SMTP](#email--smtp)
- [Site Content (CMS)](#site-content-cms)
- [Fundraisers & Organizations](#fundraisers--organizations)

---

## For Customers

### Your Account & Dashboard

After logging in, your dashboard shows:
- Recent orders and their current status
- Active subscriptions (up to 4 shown, with a link to manage all)
- Quick links to your order history and account settings

---

### Shopping & Checkout

1. Browse products and add items to your cart using the **+** / **−** quantity stepper.
2. When ready, click **Checkout** from the cart page.
3. Enter your shipping address and contact details.
4. Review your order totals (subtotal, shipping, tax, and any discounts).
5. Enter your card details in the secure payment box and click **Pay & Place Order**.
6. You will receive a confirmation email if outbound email is configured.

**About your card details.** The payment box is provided directly by GoDaddy
Payments. Your card number, security code and expiry date go straight to GoDaddy
and are never stored by this site. We keep only the card brand and last four
digits so you can recognise the payment later.

**Prices are calculated on the server**, so the amount charged always matches
the order as we have it recorded.

**If the Pay button stops responding**, wait a moment rather than clicking again
— the button is disabled while payment is in progress, and the system is built
so a double submit cannot charge you twice.

**If you see "We're confirming your payment"**, it means the connection to the
payment processor was interrupted and we do not yet know whether the payment
succeeded. Do **not** pay again. We will confirm with the processor and email
you, usually within a few minutes.

---

### Order History

Go to **My Account → My Orders** to see all your past orders. Each row shows:
- Order number and date
- Status badge (Paid, Processing, Packed, Shipped, Delivered, etc.)
- Tracking number and a direct link to the carrier's tracking page (when a label has been generated)

Click an order number to open the detail view.

---

### Shipment Tracking

On any order detail page, if a shipping label has been generated you will see a **Shipment Tracking** card showing:
- Tracking number (linked to the carrier's website)
- Carrier and service name
- A timeline of tracking events (most recent first)

The timeline is populated from stored scan data. Click **Refresh Status** to fetch the latest update live from the carrier. The result is cached for 5 minutes, so rapid clicks will return the same data without hitting the carrier API twice.

You will receive an automatic email notification when your package is:
- **Out for delivery**
- **Delivered**

These emails are sent once per status event and use the store's configured SMTP settings.

---

### Reorder & Subscribe & Save

On any order detail page:

**Reorder** — click **Reorder These Items** to add all line items from that order back into your active cart in one click.

**Subscribe & Save** — set up automatic repeat orders on a schedule:

| Interval | Description |
|---|---|
| Weekly | New order every 7 days |
| Every 2 Weeks | New order every 14 days |
| Monthly | New order every 30 days |
| Every 2 Months | New order every 60 days |

Select your interval and click **Subscribe**. The system schedules the next order date immediately.

---

### Managing Subscriptions

Go to **My Account → Subscriptions** (or click **Manage Subscriptions** from the order list) to see all your active, paused, and cancelled subscriptions.

Each subscription card shows:
- The items and quantities
- The repeat interval
- The next scheduled order date

Available actions:
- **Pause** — stops the next order from processing; subscription stays on file
- **Resume** — re-activates a paused subscription and resets the next order date
- **Cancel** — permanently cancels the subscription

---

## For Staff & Admins

### Staff Portal Overview

Navigate to **Staff Portal** (staff-only link in the nav). From here you can access:
- Order list and detail views
- Shipping label generation and monitoring
- Inventory management
- Operational Settings (configuration)
- Site Content (CMS blocks)

---

### Order Management

The **Orders** section lets you:
- Search orders by order number, customer name, or email
- Filter by status
- View full order detail including line items, pricing breakdown, and shipping address
- Update order status

---

### Shipping Labels

#### Generating a Label

1. Go to **Staff Portal → Shipping → Generate & Print Label**.
2. Select an order from the dropdown (shows paid and in-progress orders).
3. Choose a carrier/service (USPS Ground Advantage, FedEx Ground, UPS Ground).
4. Click **Generate Label**.
5. The system calls the Pitney Bowes API and returns the label. A print dialog opens automatically.

The generated label is stored in the database and can be reprinted or downloaded at any time from the **Label Monitor** list.

#### Draft Labels (No Carrier Credentials)

If Pitney Bowes credentials are not yet configured, the system automatically falls back to a **Draft Label** — a printable address label (PDF format) with a "DRAFT — No Tracking Number" banner. Staff can:
- Print it directly from the browser (the browser's "Save as PDF" option works for record-keeping)
- Use it to package and hand-deliver or ship via another method

Draft labels are logged in the system and flagged so they can be replaced with a real label once credentials are set up.

#### Reprinting & Downloading

From **Staff Portal → Shipping → Label Monitor**:
- Search by tracking number or order number
- Click **Print** to open the label PDF in the browser print dialog
- Click **Download** to save the PDF to disk
- Reprints are logged in the audit trail

#### Thermal Printer Setup (QZ Tray)

Popcorn N Such supports direct printing to a network thermal label printer (Zebra, Rollo, DYMO 4XL, etc.) via **QZ Tray** — a free Java desktop app that runs on the computer at the store.

**One-time setup (per workstation):**

1. Download and install [QZ Tray](https://qz.io/download/) on the computer connected (or networked) to the label printer.
2. In the staff portal, go to **Operational Settings → Label Printer (QZ Tray)** and enter:
   - **Printer Name** — must match exactly how the printer appears in the OS print spooler (e.g., `ZDesigner GK420d`)
   - **Printer IP Address** — the network IP of the printer (e.g., `192.168.1.100`)
3. On the **Generate & Print Label** page, follow the **QZ Tray Setup** card:
   - Click **Install Library** to download the QZ Tray JS bridge file from the CDN to the server (one-time, staff only)
   - Start QZ Tray on your workstation
   - Click **Connect to QZ** in the browser — the page connects via WebSocket to the local QZ Tray instance
4. When QZ Tray is connected, labels with ZPL data print directly to the thermal printer without a browser print dialog.

If QZ Tray is not available (not installed, not running, or the printer name is not found), the system falls back to the browser PDF print flow automatically.

---

### Tracking Updates for Buyers

#### Live polling (on demand)
When a customer clicks **Refresh Status** on their order page, the site calls the Pitney Bowes tracking API, stores the result, and displays the timeline. Results are cached for 5 minutes.

#### Webhook push (automatic)
Configure the following URL in your Pitney Bowes account dashboard under **Tracking Webhooks**:

```
https://<your-domain>/shipping/webhooks/tracking/
```

When PB pushes a tracking event, the site:
1. Looks up the label by tracking number
2. Saves the event to the database
3. Emails the customer automatically for **Out for Delivery** and **Delivered** events

To secure the webhook, set the environment variable `SHIPPING_WEBHOOK_SECRET` to a shared secret string, then configure PB to send that value in the `X-PB-Webhook-Secret` request header.

---

### Operational Settings

Go to **Staff Portal → Operational Settings**. Changes take effect immediately — no server restart is required. Secret fields (API keys, passwords) are never shown back in the form; leave them blank to keep the current value.

#### Business / Ship-From Address

This address appears in the **FROM** field on every shipping label. Enter your actual store or warehouse address:

| Field | Example |
|---|---|
| Business Name | Popcorn N Such |
| Street Address | 123 Main Street |
| Suite / Unit | Suite 4 *(optional)* |
| City | Belleville |
| State | IL |
| ZIP Code | 62220 |
| Country | US |

#### Shipping Provider & Rates

| Setting | Description |
|---|---|
| Shipping Provider | **Pitney Bowes** for live carrier rates; **Flat Rate** for a fixed charge with no API |
| Default Package Weight (oz) | Used when item weight is unknown |
| Flat / Fallback Rate (cents) | Charged on Flat Rate mode, or when the live API fails — `899` = $8.99 |
| Free Shipping Threshold (cents) | Orders at or above this subtotal ship free — `7500` = $75; set `0` to disable |

#### Label Printer (QZ Tray)

| Setting | Description |
|---|---|
| Printer Name | Exact name as shown in OS print spooler or QZ Tray |
| Printer IP Address | Network IP for reference; configure this in QZ Tray's printer settings |

#### Pitney Bowes API

| Setting | Description |
|---|---|
| API Key | Client ID from your PB developer account |
| API Secret | Client secret — stored encrypted, never shown |
| Environment | `sandbox` for testing, `production` for live shipments |
| Sandbox / Production URL | Leave blank to use PB defaults |

#### GoDaddy Payments

Card payments run through **GoDaddy Payments (Poynt)**. Customers type their card
into a secure form supplied by GoDaddy — the card number, security code and
expiry date never reach this application's servers.

Credentials are set by your developer as environment variables, not in this
screen, because they include a private cryptographic key. See
[docs/PAYMENTS.md](docs/PAYMENTS.md).

| Setting | Description |
|---|---|
| Environment | `st` = test mode (no real money), `prod` = live |
| Application ID / Business ID | From your Poynt HQ portal |
| Store ID | Optional; identifies which store the sale belongs to |
| Private key | Issued with your Poynt application — never share it |
| Webhook Secret | Verifies messages sent to us by GoDaddy |

The webhook URL to enter in GoDaddy's dashboard is shown at the bottom of the
GoDaddy section — copy it directly from there.

**Checking payments are working.** Ask your developer to run
`python manage.py check_payments_ready`. It reports anything missing or unsafe
before you go live.

#### Payments: refunds and unconfirmed charges

**Issuing a refund.** Go to **Django admin → Payment transactions**, open the
payment, and use **Payment refunds** to record a full or partial refund. Only
staff accounts can refund. The original payment record is never deleted — the
refund is stored alongside it, so the history stays complete. You cannot refund
more than was originally charged.

**"Payment being confirmed" orders.** Occasionally the connection to GoDaddy
drops after we send a charge but before we hear back. When that happens we do
*not* know whether the customer was charged, so the system:

- shows the customer a page telling them **not** to try paying again,
- creates no order,
- marks the payment `ambiguous` and keeps asking GoDaddy what happened.

This resolves itself automatically, usually within minutes. **Never manually
charge a customer again in this situation** — that is how double charges happen.
If a payment stays unresolved, it appears in Django admin with
*Requires reconciliation* ticked; escalate it to your developer.

#### Email / SMTP

| Setting | Description |
|---|---|
| Contact Email | Displayed on the contact page |
| Default From Email | The `From:` address for all outbound emails |
| SMTP Host | Your mail server hostname (e.g., `smtp.gmail.com`) |
| SMTP Port | Usually `587` (TLS) or `465` (SSL) |
| SMTP User | Username / email address for SMTP auth |
| SMTP Password | Never shown after save |
| Use TLS | Check for most modern SMTP providers |

---

### Site Content (CMS)

Go to **Staff Portal → Site Content** to manage editable content blocks that appear on public-facing pages (hero banners, promotional sections, testimonials, etc.).

Each block has:
- **Page** — which page it appears on (home, about, contact, etc.)
- **Section Name** — internal key used to place the block in the right area (e.g., `hero`, `promo-banner`)
- **Heading Text** — large headline shown to visitors
- **Body Text** — supporting paragraphs
- **Image** — optional section image
- **Button Text & Link** — optional call-to-action button
- **Display Order** — lower numbers appear first
- **Active toggle** — hide a section without deleting it

---

### Fundraisers & Organizations

*(Documentation for fundraiser campaigns, organization dashboards, team leaderboards, and seller stores is maintained separately in the operations runbook.)*

---

## Environment Variables Reference

Variables that affect shipping and tracking specifically:

| Variable | Description |
|---|---|
| `SHIPPING_PROVIDER` | `pitney_bowes` or `flat_rate` |
| `SHIPPING_FROM_NAME` | Business name on labels |
| `SHIPPING_FROM_ADDRESS_LINE_1` | Street address |
| `SHIPPING_FROM_ADDRESS_LINE_2` | Suite/unit (optional) |
| `SHIPPING_FROM_CITY` | City |
| `SHIPPING_FROM_STATE` | 2-letter state code |
| `SHIPPING_FROM_POSTAL_CODE` | ZIP code |
| `SHIPPING_FROM_COUNTRY` | 2-letter country code (default `US`) |
| `SHIPPING_DEFAULT_WEIGHT_OZ` | Fallback package weight |
| `ESTIMATED_SHIPPING_CENTS` | Flat/fallback rate in cents |
| `FREE_SHIPPING_THRESHOLD_CENTS` | Free shipping cutoff in cents |
| `PITNEY_BOWES_API_KEY` | PB client ID |
| `PITNEY_BOWES_API_SECRET` | PB client secret |
| `PITNEY_BOWES_ENV` | `sandbox` or `production` |
| `LABEL_PRINTER_NAME` | QZ Tray printer name |
| `LABEL_PRINTER_IP` | Label printer network IP |
| `SHIPPING_WEBHOOK_SECRET` | Optional PB webhook verification secret |

All of the above can also be set via **Operational Settings** in the staff portal — no server restart needed.
