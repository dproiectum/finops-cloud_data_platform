"""Business definitions displayed by the FinOps knowledge pages."""

from __future__ import annotations

import pandas as pd


def cost_formulas() -> pd.DataFrame:
    return pd.DataFrame(
        [
            (
                "Billed Cost",
                "SUM(BilledCost)",
                "Amount invoiced in the billing currency. Credits and adjustments may be negative.",
            ),
            (
                "List Cost",
                "SUM(ListCost)",
                "Cost calculated from public or list prices where the provider supplies it.",
            ),
            (
                "Contract Cost",
                "SUM(ContractedCost)",
                "Cost calculated from negotiated prices before applicable commitment benefits.",
            ),
            (
                "Effective Cost",
                "SUM(EffectiveCost)",
                "Aggregate the source-provided amortized cost, including discounts and "
                "allocated prepaid purchases. The dashboard does not recalculate amortization.",
            ),
            (
                "Effective Cost Breakdown",
                "Reservation + Savings Plan + Usage On-Demand + Usage Dynamic + Adjustment "
                "(+ Other Charges, when present)",
                "Each component sums EffectiveCost for a mutually exclusive group of source rows. "
                "This is not Contract Cost plus the full purchase price of RI/SP contracts.",
            ),
            (
                "Reservation / Savings Plan",
                "SUM(EffectiveCost) for Usage + Commitment-Based, grouped by CommitmentDiscountType",
                "Reservation and Savings Plan are separate allocations of effective usage cost; "
                "they are not the full purchase amounts of the contracts.",
            ),
            (
                "Usage On-Demand / Usage Dynamic",
                "SUM(EffectiveCost) for Usage, grouped by PricingCategory",
                "On-Demand and Dynamic usage are separate from commitment-based usage.",
            ),
            (
                "Adjustment / Other Charges",
                "SUM(EffectiveCost) for Adjustment / for all remaining rows",
                "Adjustments retain their sign. Other Charges is displayed only when its net "
                "amount is non-zero; it keeps taxes, credits and unclassified charges in the total.",
            ),
            (
                "Negotiated Savings",
                "List Cost − Contract Cost",
                "Technical price comparison; it is not automatically verified cash savings.",
            ),
            (
                "Savings vs. Catalog Price",
                "List Cost − Effective Cost",
                "Catalog Price means the provider's list price. Positive: effective cost is "
                "below list cost. Negative: effective cost is above list cost. This is the same "
                "price comparison labelled Realized Savings on the Savings page, not proof of cash savings.",
            ),
            (
                "Catalog Price Difference Rate / Saving Rate",
                "(List Cost − Effective Cost) / List Cost × 100",
                "Returns zero when List Cost is zero.",
            ),
            (
                "Month-over-Month Change",
                "(Current Billed Cost − Previous Billed Cost) / |Previous Billed Cost| × 100",
                "Not calculated when the previous month is zero or absent.",
            ),
            (
                "Average by Resource",
                "Billed Cost / Active Resources",
                "Portfolio-level indicator, not a unit price.",
            ),
        ],
        columns=["KPI", "Formula", "Interpretation"],
    )


def focus_columns() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("BilledCost", "Cost", "Amount invoiced in BillingCurrency", "No"),
            ("EffectiveCost", "Cost", "Amortized cost including discounts and allocated prepaid purchases", "No"),
            ("ListCost", "Cost", "Cost evaluated at list pricing", "No"),
            ("ContractedCost", "Cost", "Cost evaluated at negotiated pricing", "No"),
            ("BillingCurrency", "Cost", "Currency used for billing; EUR in this project", "No"),
            ("BillingPeriodStart", "Time", "First date of the billing period", "No"),
            ("BillingPeriodEnd", "Time", "Exclusive end date of the billing period", "No"),
            ("ChargePeriodStart", "Time", "Start timestamp of the charge", "No"),
            ("ChargePeriodEnd", "Time", "End timestamp of the charge", "No"),
            ("ChargeCategory", "Charge", "Usage, Purchase, Tax, Adjustment or Credit", "Yes"),
            ("ChargeDescription", "Charge", "Provider description of the charge", "Yes"),
            ("ChargeFrequency", "Charge", "Recurring, one-time or usage-based frequency", "Yes"),
            ("PricingCategory", "Pricing", "On-Demand, Commitment-Based or Dynamic", "No"),
            ("PricingQuantity", "Pricing", "Quantity used for price calculation", "Yes"),
            ("PricingUnit", "Pricing", "Unit associated with the pricing quantity", "Yes"),
            ("ServiceCategory", "Consumption", "Normalized family of cloud services", "Yes"),
            ("ServiceName", "Consumption", "Provider service name; mandatory before Silver", "No"),
            ("ResourceId", "Resource", "Stable resource identifier when available", "Yes"),
            ("ResourceName", "Resource", "Human-readable resource name", "Yes"),
            ("ResourceType", "Resource", "Provider resource type", "Yes"),
            ("Region", "Resource", "Region associated with consumption", "Yes"),
            ("SkuId", "SKU", "Provider SKU identifier", "Yes"),
            ("SubAccountId", "Organization", "Subscription identifier", "Yes"),
            ("SubAccountName", "Organization", "Subscription display name", "Yes"),
            ("x_CostCenter", "Organization", "Internal allocation code supplied by the source. "
             "Preserved unchanged in Silver. Missing values use the documented synthetic "
             "Europe/Corporate allocation policy; unmatched regions remain Unallocated Costs. "
             "This does not indicate commitment coverage.", "Yes"),
            ("cost_center_source", "Allocation", "Original x_CostCenter, retained for traceability.", "No"),
            ("cost_center_allocated", "Allocation", "Source cost center or synthetic regional fallback.", "No"),
            ("allocation_method", "Allocation", "SOURCE, REGION_EUROPE, GLOBAL_CORPORATE, "
             "REGION_CORPORATE or UNALLOCATED.", "No"),
            ("Tags", "Allocation", "Key/value metadata attached to the resource", "Yes"),
            ("_source_file", "Lineage", "Parquet path that produced the record", "No"),
            ("_ingestion_run_id", "Lineage", "Pipeline execution identifier", "No"),
            ("_ingested_at", "Lineage", "Silver publication timestamp", "No"),
            ("_contract_version", "Governance", "Applied Data Contract version", "No"),
        ],
        columns=["Column", "Family", "Meaning", "Nullable"],
    )


def glossary() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("Charge Line", "One cost or usage record conforming to the FOCUS model."),
            ("Active Resource", "Distinct resource that generated at least one charge in the period."),
            ("Consumed Service", "Distinct ServiceName represented in the selected period."),
            ("Cost Center", "Organizational grouping used to allocate cloud expenditure."),
            ("Unallocated Costs", "Costs without a usable source cost center or an applicable "
             "fallback rule; not a Reservation/Savings Plan indicator."),
            ("CostCenter_Europe", "Synthetic fallback for missing cost centers in West Europe, "
             "North Europe, France Central, Sweden Central and UK South."),
            ("CostCenter_Corporate", "Synthetic central-budget fallback for Global and explicitly "
             "approved headquarters regions. It does not prove actual organizational ownership."),
            ("Batch", "Pipeline run identifier attached to published records."),
            ("Datamart", "Certified, subject-oriented table prepared for analytics."),
            ("Reconciliation", "Comparison of row counts and billed cost before and after publication."),
            ("Canary", "Limited production execution used to validate one month before full promotion."),
            ("Inform", "FinOps capability that creates cost visibility and allocation."),
            ("Optimize", "FinOps capability that identifies and prioritizes value opportunities."),
            ("Operate", "FinOps capability that embeds accountability into recurring processes."),
        ],
        columns=["Term", "Definition"],
    )
