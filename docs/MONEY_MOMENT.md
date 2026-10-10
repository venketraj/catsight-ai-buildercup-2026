# The money moment

> The climax of the demo, the video and the deck: **one clause, one number.**
>
> Every figure here is derived below from the `DOMAIN_PRIMER.md` worked example. **None of it goes on a slide until it comes out of a real engine run** (`QA-11`). This document exists so the engine can be built to produce it.
>
> **Status: resolved.** The reinstatement-premium basis is settled in §4 from the primer's own arithmetic — the convention was recoverable from the published one-event figures, so it needed deriving rather than deciding. §4.5 lists two items a reinsurance practitioner should still sanity-check; neither blocks the build, and neither moves the headline.

---

## 1. The question

Every catastrophe team argues about it after a big storm:

> **Is this one event or two — and which losses belong to which?**

It is not academic. In 2024 the English Court of Appeal ruled on how a 168-hour clause works in *UnipolSai v Covéa*, holding that "occur" means "first occur". Jebi's own loss development was driven partly by overlapping Typhoon Trami claims arriving weeks later, and the market's insured-loss estimate moved from roughly $6bn at end-2018 to around $15bn by mid-2019.

The hours clause is the clause that decides the answer. CatSight finds it, verifies the quote, and prices both readings.

## 2. The setup

Sakura General Insurance's Cat XL programme, from the worked example (synthetic):

| Layer | Structure | Limit | Attaches at | Premium | Lion Re share | Reinstatements |
|---|---|---|---|---|---|---|
| L1 | 20 xs 10 | 20.0 | 10.0 | 2.0 | **25%** | 1 @ 100%, pro rata as to amount |
| L2 | 30 xs 30 | 30.0 | 30.0 | 1.5 | **10%** | — |
| L3 | 40 xs 60 | 40.0 | 60.0 | 1.0 | 0% | — |

Gross loss from the event: **54.4**. All figures $M.

Note where Lion Re's money sits: **25% of L1, only 10% of L2.** That asymmetry is the whole point of what follows.

## 3. The two readings, priced

### Reading A — one event (54.4)

The cedent's reading: all damage falls inside one hours window.

```
L1  ceded = min(max(54.4 − 10, 0), 20) = min(44.4, 20) = 20.0   burn 100%  EXHAUSTED
L2  ceded = min(max(54.4 − 30, 0), 30) = min(24.4, 30) = 24.4   burn  81.3%
L3  ceded = min(max(54.4 − 60, 0), 40) =                   0    burn   0%
```

- Total ceded **44.4** · cedent retention **10.0**
- Lion Re loss = 20.0 × 25% + 24.4 × 10% = 5.00 + 2.44 = **7.44**
- Lion Re RIP receipts = (20/20 × 2.0 × 1.0) × 25% + (24.4/30 × 1.5 × 1.0) × 10% = 0.500 + 0.122 = **0.622**
- **Lion Re net = 7.44 − 0.622 = 6.82**

### Reading B — two events (35.0 + 19.4)

The reinsurer's reading: the losses first occur in two separate windows. Each occurrence carries its own retention.

```
Occurrence 1 (35.0)          Occurrence 2 (19.4)
L1  min(25, 20) = 20.0       L1  min(9.4, 20) =  9.4   ← needs the reinstatement
L2  min( 5, 30) =  5.0       L2  min(  0, 30) =    0
L3                 0         L3                   0
```

- L1 total **29.4** (within 20 limit + 1 reinstatement = 40 available ✓) · L2 total **5.0**
- Total ceded **34.4** · cedent retention **10.0 + 10.0 = 20.0**
- Lion Re loss = 29.4 × 25% + 5.0 × 10% = 7.35 + 0.50 = **7.85**
- Lion Re RIP receipts = (20/20 × 2.0 × 1.0) × 25% + (5.0/30 × 1.5 × 1.0) × 10% = 0.500 + 0.025 = **0.525**
  - *Occurrence 2's 9.4 erosion of L1 generates no RIP: the single reinstatement was consumed in full by occurrence 1, so nothing further is restored. Derivation in §4.*
- **Lion Re net = 7.85 − 0.525 = 7.325**

### The money at stake, per party

| | Reading A · one event | Reading B · two events | Move |
|---|---|---|---|
| **Total ceded** | 44.4 | 34.4 | **−10.0 · −22.5%** |
| Cedent retention | 10.0 | 20.0 | +10.0 · doubles |
| L1 ceded | 20.0 | 29.4 | +9.4 · burden shifts **down** into L1 |
| L2 ceded | 24.4 | 5.0 | −19.4 |
| **Lion Re gross** | 7.44 | **7.85** | **+0.41 · +5.5%** |
| **Lion Re net** | 6.82 | **7.33** | **+0.51 · +7.4%** |

### Why this is the moment

**The split that saves the treaty $10.0M costs Lion Re more.**

Because Lion Re holds 25% of L1 and 10% of L2, the reading that cuts total ceded recoveries by 22.5% pushes the surviving burden down into the layer where Lion Re's share is heaviest. The cedent argues one event. The reinsurer argues two. **They are not arguing about the same pot of money** — and a single headline number would hide that.

This is why the Courtroom is genuinely adversarial rather than theatrical, and it is the detail a specialist judge will notice. Two agents are not performing a debate; they are advancing the readings their actual economics dictate.

## 4. Resolved: the reinstatement-premium basis

Settled from the primer's own arithmetic. The decisive test is internal consistency — **only one basis reproduces the one-event RIP that `DOMAIN_PRIMER.md` §4 already publishes**, so the convention is recoverable from the existing numbers rather than a matter of opinion.

### 4.1 The test

The primer states, for the one-event case: L1 our RIP **0.5**, L2 our RIP **0.122**, total **0.622**, net **≈ 6.82**. Working backwards from those:

- **L1:** 0.5 ÷ 25% = 2.00 = the *full* L1 premium. L1 was eroded 20 of 20 → factor **1.00**.
- **L2:** 0.122 ÷ 10% = 1.22 = (24.4 / 30) × 1.5 → factor **0.8133**.

L2 was **not exhausted** — only 81% eroded — and it still attracted a reinstatement premium. That settles the rule:

> **RIP = (limit eroded in the occurrence ÷ limit) × premium × rate**, charged **per occurrence**, pro rata as to amount, **capped by the reinstatement capacity available**.

Reinstatement is automatic and applies to partial erosion, not only to exhaustion. That is the standard "pro rata as to amount" mechanic, and it is what the primer's figures encode.

### 4.2 Applying it to the split

**L1** — limit 20, premium 2.0, 1 reinstatement at 100%:

| Occurrence | Erosion | RIP |
|---|---|---|
| 1 | 20.0 | (20/20) × 2.0 × 1.0 = **2.00** — consumes the one reinstatement in full |
| 2 | 9.4 of the restored limit | a *second* reinstatement would be needed to restore it; none remains → **0.00** |

**L2** — limit 30, premium 1.5:

| Occurrence | Erosion | RIP |
|---|---|---|
| 1 | 5.0 | (5/30) × 1.5 × 1.0 = **0.25** |
| 2 | 0 | **0.00** |

Lion Re RIP = 2.00 × 25% + 0.25 × 10% = **0.525** · loss 7.85 · **net 7.325**

Aggregate capacity check: L1 provides limit × (1 + reinstatements) = **40**; consumed 29.4 ✓.

### 4.3 The two bases that are wrong, and why

| Rejected | Rule | Why it fails |
|---|---|---|
| Literal FR-LOSS-3 on **aggregate** ceded | (29.4/20) × 2.0 = 2.94 | Charges for **1.47 reinstatements where the treaty provides one**. You cannot buy more reinstatement than exists. |
| RIP on what the **next** occurrence draws | (9.4/20) × 2.0 = 0.94 | Confuses "amount reinstated" with "amount subsequently used". The reinstatement follows occurrence 1 and is sized by **occurrence 1's** erosion. |

`REQUIREMENTS.md` FR-LOSS-3 gives `RIP = (ceded / limit) × premium × rate` without stating that `ceded` is **per occurrence**. For one occurrence it is correct; applied to aggregate it produces the first row above. **The engine implements §4.1; FR-LOSS-3 is to be read as per-occurrence.**

### 4.4 The finding this unlocks — three parties, not two

With RIP settled, the complete picture:

| Party | One event | Two events | Prefers |
|---|---|---|---|
| **Cedent** — retention + RIP payable | 13.22 | 22.25 | **one event**, by 9.03 |
| **Reinsurance market** — recoveries − RIP received | 41.18 | 32.15 | **two events**, by 9.03 |
| **Lion Re** — our net | 6.82 | 7.33 | **one event**, by 0.51 |

**Lion Re's interest sits with the cedent, against the rest of the market it shares the programme with.**

Holding 25% of L1 but only 10% of L2, the split lifts our share of total recoveries from **16.8% to 22.8%** even as the market's total bill falls by $10M. We are overweight in exactly the layer the split loads.

No portfolio-level number surfaces this. It is precisely what the Courtroom exists to find, and it is the sharpest thing in the demo.

### 4.5 Residual items for a practitioner

The above is settled arithmetic and standard clause mechanics, and it is what the engine implements. Two points a reinsurance practitioner should still sanity-check — not because the maths is in doubt, but because wordings vary between contracts:

1. **Window placement.** The 35.0 / 19.4 split must follow from a legitimate, non-overlapping placement beginning no earlier than the first recorded loss. The engine enforces non-overlap (`FR-WHATIF-1`); whether *this* split is the one a cedent would actually elect is a judgement call about the event's loss timeline.
2. **RIP when a layer is eroded and the treaty then expires unused.** The primer charges it; some wordings do not. It changes nothing above — both readings here have subsequent exposure — but it should be stated in `data/ASSUMPTIONS.md`.

If a practitioner rejects §4.1, **only Lion Re's net figures move.** The headline holds under every basis in §4.3: total ceded **−10.0 / −22.5%**, cedent retention **doubling**, and **Lion Re worse off under the split**.

## 5. How it is used

| Where | Treatment |
|---|---|
| **Product** (`FR-COURT`) | Both readings, both quotes verified, both priced by the engine, `money_at_stake` computed per party in Python. The analyst records a position. |
| **Video** 1:05–1:40 | The Courtroom on the hours clause. Two readings side by side, both cited. The engine prices both. Caption: *"Gemini reads. Tested code calculates."* |
| **Deck** slide 7 | "The money moment: one clause, one number." Lead with −$10.0M / −22.5%, then reveal the per-party asymmetry. |
| **Q&A** | *"What is Gen AI doing that rules can't?"* — constructing both sides of a genuinely ambiguous reading from heterogeneous wordings, with machine-checked citations, then letting tested code price each one. |

**Framing guardrails.** Issue-spotting, not legal advice. The human decides. Synthetic contracts, fictional cedent. The event is real and people died in it — state the number plainly, with no triumph in the voice-over.

## 6. Engine requirements this implies

- `split_occurrences(event, hours)` derives windows from the loss timeline, enforcing non-overlap and "first occur".
- Retentions and reinstatements apply **per occurrence** (FR-LOSS-5).
- Reinstatement capacity is tracked and **capped at `limit × (1 + count)`**; exceeding it is an error, not a silent overrun.
- **RIP accumulates per occurrence** on the limit eroded by *that* occurrence, pro rata as to amount, and stops once reinstatement capacity is consumed (§4.1). Erosion beyond available capacity is still paid if the aggregate limit allows, but generates **no** RIP — nothing is restored.
- The engine returns the **per-party** view: cedent (retention + RIP payable), market (recoveries − RIP received) and our own net, because §4.4 is the story.
- The engine returns the **full result set for both readings in one call**, so the UI never has to recombine numbers — and `money_at_stake` is a Python subtraction over those results, per party, never an LLM output.
- All four perspectives — total ceded, cedent retention, Lion Re gross, Lion Re net — are returned, because the story needs all four.

**QA-11 asserts these exact figures.** If a code change moves them, the test fails and the slide is wrong.
