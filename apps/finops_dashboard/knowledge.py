"""Business definitions displayed by the FinOps knowledge pages."""

from __future__ import annotations

import pandas as pd


def cost_formulas() -> pd.DataFrame:
    return pd.DataFrame(
        [
            (
                "Billed cost",
                "SUM(BilledCost)",
                "Amount invoiced in the billing currency. Credits and adjustments may be negative.",
            ),
            (
                "List cost",
                "SUM(ListCost)",
                "Cost calculated from public or list prices where the provider supplies it.",
            ),
            (
                "Contracted cost",
                "SUM(ContractedCost)",
                "Cost calculated from negotiated prices before applicable commitment benefits.",
            ),
            (
                "Effective cost",
                "SUM(EffectiveCost)",
                "Economic cost after discounts and commitment-benefit allocation.",
            ),
            (
                "Negotiated difference",
                "List cost − Contracted cost",
                "Technical price comparison; it is not automatically verified cash savings.",
            ),
            (
                "Commitment difference",
                "Contracted cost − Effective cost",
                "May be negative. Eligibility and coverage must be validated before "
                "calling it realized savings.",
            ),
            (
                "Total difference vs list",
                "List cost − Effective cost",
                "Technical comparison between public price and effective economic cost.",
            ),
            (
                "Savings rate",
                "(List cost − Effective cost) / List cost × 100",
                "Returns zero when List cost is zero.",
            ),
            (
                "Month-over-month change",
                "(Current billed cost − Previous billed cost) / |Previous billed cost| × 100",
                "Not calculated when the previous month is zero or absent.",
            ),
            (
                "Average cost per resource",
                "Billed cost / Active resources",
                "Portfolio-level indicator, not a unit price.",
            ),
        ],
        columns=["KPI", "Formula", "Interpretation"],
    )


def focus_columns() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("BilledCost", "Cost", "Amount invoiced in BillingCurrency", "No"),
            ("EffectiveCost", "Cost", "Cost after allocated discounts and benefits", "No"),
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
            ("x_CostCenter", "Organization", "Azure extension used for allocation", "Yes"),
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
            ("Charge line", "One cost or usage record conforming to the FOCUS model."),
            ("Active resource", "Distinct resource that generated at least one charge in the period."),
            ("Consumed service", "Distinct ServiceName represented in the selected period."),
            ("Cost center", "Organizational grouping used to allocate cloud expenditure."),
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
