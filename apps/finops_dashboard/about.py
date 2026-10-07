"""A factual project presentation and a concise author profile."""

import pandas as pd
import streamlit as st

from project_costs.view import render_project_costs


PAGE_GUIDE = [
    ("Executive Overview", "Understand monthly spend, cost trends and year-over-year comparisons."),
    ("Cost Drivers", "Identify which services, charge categories and SKUs account for spend."),
    ("Savings", "Compare list and effective costs and inspect the effective-cost components. Price benefit is not proof of cash savings."),
    ("Allocation & Accountability", "Explore showback by cost center, application owner and subscription."),
    ("Resources", "Inspect resource, region and resource-group cost distributions."),
    ("Operations & Quality", "Inspect pipeline audit history, completeness and billing reconciliation. Restricted viewers do not have operational access."),
    ("Consumption & Emission", "Explore usage quantities by service, SKU and unit, plus an explicitly illustrative carbon scenario."),
    ("Knowledge Base", "Look up FOCUS fields, cost formulas and FinOps terminology."),
    ("Architecture", "Follow the data lineage, Medallion layers and analytical products."),
    ("About the Project", "Understand the project, the dashboard pages and the technology stack. Its Project Costs tab covers approved GCP costs and Databricks list-price estimates."),
    ("About Me", "Meet the engineer behind the project and get in touch."),
]

TECH_STACK = [
    ("Source Data", "Independent Python Generator · FOCUS · Parquet", "Produce synthetic Azure cost-and-usage history for reproducible testing."),
    ("Local Proof of Concept", "Python · DuckDB · Streamlit", "Test the end-to-end processing and reporting approach locally before cloud deployment."),
    ("Cloud Source Storage", "Google Cloud Storage · Unity Catalog External Volume", "Keep source Parquet files available to both DEV and PROD without duplicating the source."),
    ("Transformation", "Databricks · Apache Spark / PySpark · SQL", "Apply Bronze ingestion, the Data Contract, Silver conformance and Gold transformations."),
    ("Data Model & Storage", "Delta Lake · Unity Catalog", "Publish dimensional facts, dimensions and question-oriented datamarts. Classic managed storage uses a separate GCS bucket."),
    ("Orchestration", "Databricks Jobs", "Run daily increments, monthly close and historical backfills with audit and validation steps."),
    ("Serving", "Databricks SQL Warehouse · SQL Connector", "Read the serving data through SQL; the dashboard never writes to Unity Catalog."),
    ("Presentation", "Streamlit · pandas · Plotly", "Prepare presentation-level dataframes, interactive charts and European number formatting."),
    ("Web Delivery", "Docker · Cloud Build · Cloud Run", "Build and deploy the dashboard container behind the project domain."),
    ("Version Control", "Git · GitHub", "Version the generator, local POC and cloud implementation as separate projects."),
]


def render_about():
    st.markdown('<div class="finops-kicker">FINOPS · PROJECT</div>', unsafe_allow_html=True)
    st.title("About the Project")
    st.write("FinOps Control Center is a data-engineering project for cloud-cost reporting, showback and cost analysis.")
    project, guide, stack, costs = st.tabs([
        "Overview", "Page Guide", "Technology Stack", "Project Costs"
    ])
    with project:
        st.subheader("From a FinOps Need to a Data Product")
        st.write("The project explores how a governed data platform can make cloud-cost reporting more reliable and easier to evolve. Business calculations are prepared in analytical datamarts rather than repeatedly embedded in visualization tools.")
        st.write("Its implementation follows three stages: an independent synthetic-data generator, a local end-to-end proof of concept, and a cloud platform with separate DEV and PROD processing and a web dashboard.")
        st.subheader("How the Platform Works")
        st.write("Parquet files in GCS are exposed through a shared RAW Volume. Databricks applies a FOCUS Data Contract and Bronze–Silver–Gold transformations before refreshing datamarts. Daily usage is provisional; monthly billing supports reconciliation and monthly close. OPS retains environment-aware audit history.")
        st.subheader("What This Portfolio Demonstrates")
        st.markdown("- Automated data processing and validation.\n- A dimensional model and datamarts for FinOps questions.\n- Showback, cost analysis and explainable calculations.\n- Scoped reporting with fixed synthetic demonstration profiles.\n- FinOps applied to the platform's own operating costs.")
        st.subheader("Scope and Limits")
        st.write("The Azure portfolio is synthetic and does not represent an employer's actual expenditure. Public profile selection demonstrates authorized scopes; it is not user authentication. Project Costs is a separate, approved summary of platform operating costs. Carbon results are teaching scenarios, not measured provider emissions.")
        st.link_button("Explore the Cloud Project on GitHub", "https://github.com/dproiectum/finops-cloud_data_platform")
    with guide:
        st.subheader("What Each Page Covers")
        st.table(pd.DataFrame(PAGE_GUIDE, columns=["Page", "Purpose"]))
        st.caption("Page visibility and data scope depend on the active access context. The guide does not grant access to protected pages.")
    with stack:
        st.subheader("Technology Stack and Responsibilities")
        st.table(pd.DataFrame(TECH_STACK, columns=["Layer", "Technology", "Responsibility"]))
        st.caption("Azure is the cost-data context, not the hosting provider of this cloud implementation. GCP and Databricks host the platform.")
    with costs:
        render_project_costs(embedded=True)


def render_about_me():
    st.markdown('<div class="finops-kicker">ENGINEERING · PROFILE</div>', unsafe_allow_html=True)
    st.title("About Me")
    st.write("I am an engineer interested in improving how systems work, with a focus on performance and efficiency. I believe that even small, well-considered improvements can create value for an organization and the people who depend on it.")
    st.write("My approach starts with understanding the problem through data, then looking at the design of the system itself. Better results sometimes require changing how a system is designed, rather than simply making an existing process run faster. Technology should solve problems without introducing unnecessary complexity or hidden costs.")
    st.write("For me, improving an organization from within is a form of value creation. Reducing wasted effort, making information more reliable and using resources more thoughtfully can make everyday work better.")
    st.write("I enjoy learning across disciplines and putting ideas into practice. Building, testing and refining solutions is how I deepen my understanding and turn knowledge into something useful.")
    st.subheader("Get in Touch")
    st.markdown("If you have questions about the project or would like to discuss it, you can contact me at [lumos@allops.cloud](mailto:lumos@allops.cloud).")
