"""Offline authorization checks; fixtures are not live-cloud test evidence."""

from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import unittest
import weakref
from unittest.mock import MagicMock, patch

import pandas as pd

APP = Path(__file__).resolve().parents[2] / "apps/finops_dashboard"
ROOT = APP.parents[1]
sys.path.insert(0, str(APP))

from config import DashboardConfig  # noqa: E402
from data_access import DatabricksDataSource  # noqa: E402
from security import (  # noqa: E402
    AccessContext, Identity, SecurityError, auth_mode, demo_identity, iap_identity, resolve_access,
)
from security.queries import ScopedQueries  # noqa: E402
from security.validate_live import validate  # noqa: E402


class FixtureSource:
    """Run the generated scoped queries with native SQLite named parameters.

    Only qualification and CURRENT_TIMESTAMP keyword syntax are adapted; query
    predicates, joins, aggregates and binding values run unchanged.
    """

    label = "Offline synthetic fixture"

    def __init__(self):
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        weakref.finalize(self, self.connection.close)
        self.calls = []
        self.connection.executescript("""
            CREATE TABLE entitlement (
              identity_provider TEXT, principal_id TEXT, environment TEXT,
              role TEXT, scope_type TEXT, scope_id TEXT, is_active BOOLEAN,
              valid_from TIMESTAMP, valid_to TIMESTAMP
            );
            CREATE TABLE business_scope (
              environment TEXT, application_code TEXT, domain_id TEXT,
              subdomain_id TEXT, is_active BOOLEAN
            );
            CREATE TABLE charges (
              environment TEXT, billing_month TEXT, date TEXT, resource_id TEXT,
              resource_name TEXT, resource_group_name TEXT, region TEXT, service_name TEXT,
              cost_center TEXT, subscription_id TEXT, subscription_name TEXT, sku_id TEXT,
              meter_category TEXT, meter_name TEXT, charge_category TEXT,
              charge_subcategory TEXT, charge_frequency TEXT, application_code TEXT,
              application_name TEXT, application_owner_id TEXT, application_owner_email TEXT,
              application_business_owner TEXT, billed_cost REAL, effective_cost REAL,
              list_cost REAL, contracted_cost REAL, effective_cost_component TEXT,
              billing_currency TEXT, ingestion_run_id TEXT, ingested_at TIMESTAMP
            );
            CREATE TABLE pipeline_run (
              environment TEXT, pipeline_name TEXT, billing_month TEXT, started_at TIMESTAMP,
              finished_at TIMESTAMP, run_id TEXT, status TEXT, message TEXT
            );
            CREATE TABLE monthly_reconciliation (
              environment TEXT, billing_month TEXT, reconciled_at TIMESTAMP, status TEXT,
              billing_rows INT, after_rows INT, after_billing_difference INT
            );
            INSERT INTO pipeline_run VALUES
              ('prod','test','2026-01','2026-02-01','2026-02-01','test-prod','SUCCESS','ok'),
              ('dev','test','2026-01','2026-02-01','2026-02-01','test-dev','SUCCESS','ok');
            INSERT INTO monthly_reconciliation VALUES
              ('prod','2026-01','2026-02-01','PASSED',2,2,0);
        """)
        self.grant("demo-finops-admin", "FINOPS_ADMIN", "ALL", "*")
        self.grant("demo-app-owner-a", "APPLICATION_OWNER", "APPLICATION", "APP00013057")
        self.grant("demo-app-owner-b", "APPLICATION_OWNER", "APPLICATION", "BSN0003965")
        self.connection.executemany("INSERT INTO business_scope VALUES (?,?,?,?,?)", [
            ("prod", "APP00013057", "DOMAIN_A", "SUB_A", True),
            ("prod", "BSN0003965", "DOMAIN_B", "SUB_B", True),
        ])
        self.charge("APP00013057", "2026-01", 100, 90, 150, 120, "reservation")
        self.charge("APP00013057", "2026-01", 50, 45, 80, 70, "usage_on_demand")
        self.charge("APP00013057", "2026-02", 10, 8, 15, 12, "savings_plan")
        self.charge("BSN0003965", "2026-01", 200, 180, 250, 220, "usage_dynamic")
        self.charge("BSN0003965", "2026-01", -20, -20, -20, -20, "adjustment")
        self.charge("BSN0003965", "2025-12", 20, 18, 25, 22, "usage_on_demand")
        # An unmapped credit makes the global Jan total smaller than owner A's.
        self.charge(None, "2026-01", -300, -300, -300, -300, "other")
        self.charge("APP00013057", "2026-01", 10000, 10000, 10000, 10000, "other", "dev")

    def healthcheck(self):
        pass

    def grant(self, principal, role, scope_type, scope_id, environment="prod", provider="demo"):
        self.connection.execute("INSERT INTO entitlement VALUES (?,?,?,?,?,?,?,?,?)", (
            provider, principal, environment, role, scope_type, scope_id,
            True, "2000-01-01 00:00:00", None,
        ))

    def charge(self, app, month, billed, effective, list_cost, contracted, component, env="prod"):
        values = (
            env, month, month + "-01", f"{app}-resource", f"{app}-name", f"{app}-group",
            "test-region", f"{app}-service", f"{app}-center", f"{app}-sub", f"{app}-subscription",
            f"{app}-sku", "Compute", f"{app}-meter", "Usage", "test", "Usage-Based",
            app, f"{app}-application", f"{app}-owner", "example@example.invalid", "test",
            billed, effective, list_cost, contracted, component, "USD", "test-ingestion",
            "2026-03-01 00:00:00",
        )
        self.connection.execute("INSERT INTO charges VALUES (" + ",".join("?" for _ in values)
                                + ")", values)
        self.connection.commit()

    @staticmethod
    def translate(text):
        objects = {
            "finops_ops.security.user_entitlement": "entitlement",
            "finops_ops.security.business_scope": "business_scope",
            "finops_prod.datamart.v_dashboard_charge_scoped": "charges",
            "finops_prod.silver.focus_cost_usage_central": "raw_source",
            "finops_ops.audit.pipeline_run": "pipeline_run",
            "finops_ops.audit.monthly_reconciliation": "monthly_reconciliation",
        }
        text = text.replace("`", "")
        for qualified, local in objects.items():
            text = text.replace(qualified, local)
        return text.replace("CURRENT_TIMESTAMP()", "CURRENT_TIMESTAMP")

    def query(self, text, parameters=None):
        self.calls.append((text, parameters))
        result = pd.read_sql_query(self.translate(text), self.connection, params=parameters)
        if "date" in result:
            result["date"] = pd.to_datetime(result["date"])
        return result

    def run(self, bound):
        return self.query(bound.text, bound.parameters)


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {}, clear=True):
            self.config = DashboardConfig.from_environment()
        self.source = FixtureSource()

    def queries(self, principal):
        return ScopedQueries(resolve_access(self.source, self.config, demo_identity(principal)))

    def test_missing_identity_or_wrong_provider_denies(self):
        for identity in [demo_identity("demo-no-access"), Identity("iap", "demo-app-owner-a")]:
            with self.subTest(identity=identity), self.assertRaises(SecurityError):
                resolve_access(self.source, self.config, identity)

    def test_application_owners_receive_exact_subsets_and_months(self):
        a, b = self.queries("demo-app-owner-a"), self.queries("demo-app-owner-b")
        self.assertEqual(self.source.run(a.available_months(self.config))["billing_month"].tolist(),
                         ["2026-02", "2026-01"])
        self.assertEqual(self.source.run(b.available_months(self.config))["billing_month"].tolist(),
                         ["2026-01", "2025-12"])
        self.assertEqual(self.source.run(a.executive_summary(self.config, "2026-01"))
                         .iloc[0]["billed_cost"], 150)
        self.assertEqual(self.source.run(b.executive_summary(self.config, "2026-01"))
                         .iloc[0]["billed_cost"], 180)
        self.assertEqual(self.source.run(a.application_owners(self.config, "2026-01"))
                         ["application_code"].tolist(), ["APP00013057"])

    def test_admin_includes_unknown_credits_but_not_other_environment(self):
        admin = self.queries("demo-finops-admin")
        summary = self.source.run(admin.executive_summary(self.config, "2026-01")).iloc[0]
        self.assertEqual(summary["billed_cost"], 30)
        self.assertEqual(summary["charge_lines"], 5)
        self.assertLess(summary["billed_cost"], 150)  # Never use filtered <= global as a test.
        counts = self.source.run(admin.environment_run_counts(self.config))
        self.assertEqual(counts["environment"].tolist(), ["prod"])

    def test_savings_components_and_cost_bases_reconcile(self):
        query = self.queries("demo-app-owner-a")
        row = self.source.run(query.savings_summary(self.config, "2026-01")).iloc[0]
        self.assertEqual(row["contracted_cost"], 190)
        self.assertEqual(row["effective_cost"], 135)
        self.assertEqual(row["reservation"], 90)
        self.assertEqual(row["usage_on_demand"], 45)
        self.assertEqual(row["total_savings"], 95)
        self.assertEqual(sum(row[k] for k in (
            "reservation", "savings_plan", "usage_on_demand", "usage_dynamic", "adjustment",
            "other_effective_cost",
        )), row["effective_cost"])

    def test_every_business_query_uses_scoped_rows_and_executes(self):
        query = self.queries("demo-app-owner-a")
        requests = [
            query.available_months(self.config), query.executive_history(self.config),
            query.executive_summary(self.config, "2026-01"), query.monthly_trend(self.config),
            query.daily_trend(self.config, "2026-01"), query.monthly_savings(self.config),
            query.savings_summary(self.config, "2026-01"), query.services(self.config, "2026-01"),
            query.cost_centers(self.config, "2026-01"), query.charge_types(self.config, "2026-01"),
            query.resources(self.config, "2026-01"), query.resource_groups(self.config, "2026-01"),
            query.subscriptions(self.config, "2026-01"),
            query.application_owners(self.config, "2026-01"),
            query.portfolio_services(self.config), query.portfolio_resources(self.config),
            query.sku_costs(self.config),
        ]
        for bound in requests:
            with self.subTest(sql=bound.text[-100:]):
                self.assertIn("WITH authorized_rows AS", bound.text)
                self.assertNotIn("demo-app-owner-a", bound.text)
                self.assertIn("EXISTS", bound.text)
                frame = self.source.run(bound)
                self.assertFalse(frame.empty)
                self.assertNotIn("BSN0003965", frame.to_csv(index=False))
                self.assertNotIn("Unknown", frame.to_csv(index=False))

    def test_union_permissions_do_not_duplicate_charges(self):
        self.source.grant("demo-app-owner-a", "DOMAIN_MANAGER", "DOMAIN", "DOMAIN_A")
        self.source.grant("demo-app-owner-a", "APPLICATION_OWNER", "APPLICATION", "BSN0003965")
        row = self.source.run(self.queries("demo-app-owner-a")
                              .executive_summary(self.config, "2026-01")).iloc[0]
        self.assertEqual(row["billed_cost"], 330)
        self.assertEqual(row["charge_lines"], 4)

    def test_live_revocation_and_expiry_recheck_even_existing_query(self):
        for field, value in [("is_active", "FALSE"), ("valid_to", "'2000-01-01'")]:
            with self.subTest(field=field):
                self.source = FixtureSource()
                bound = self.queries("demo-app-owner-a").monthly_savings(self.config)
                self.source.connection.execute(
                    f"UPDATE entitlement SET {field}={value} WHERE principal_id='demo-app-owner-a'"
                )
                self.assertTrue(self.source.run(bound).empty)
                with self.assertRaises(SecurityError):
                    self.queries("demo-app-owner-a")

    def test_scope_revocation_blocks_existing_query(self):
        bound = self.queries("demo-app-owner-a").available_months(self.config)
        self.source.connection.execute(
            "UPDATE business_scope SET is_active=FALSE WHERE application_code='APP00013057'"
        )
        self.assertTrue(self.source.run(bound).empty)
        with self.assertRaises(SecurityError):
            self.queries("demo-app-owner-a")

    def test_ambiguous_mappings_fail_closed_and_do_not_multiply_costs(self):
        bound = self.queries("demo-app-owner-a").monthly_savings(self.config)
        self.source.connection.execute("INSERT INTO business_scope SELECT * FROM business_scope "
                                       "WHERE application_code='APP00013057'")
        self.assertTrue(self.source.run(bound).empty)
        with self.assertRaises(SecurityError):
            self.queries("demo-app-owner-a")

    def test_invalid_and_duplicate_permissions_fail_closed(self):
        for role, scope_type, scope_id in [
            ("UNKNOWN", "APPLICATION", "APP00013057"),
            ("APPLICATION_OWNER", "ALL", "*"),
            ("APPLICATION_OWNER", "APPLICATION", "APP00013057"),
        ]:
            with self.subTest(role=role, scope_type=scope_type):
                self.source = FixtureSource()
                self.source.grant("demo-app-owner-a", role, scope_type, scope_id)
                with self.assertRaises(SecurityError):
                    self.queries("demo-app-owner-a")

    def test_domains_and_subdomains_resolve_only_confirmed_mappings(self):
        for role, scope_type, scope_id in [
            ("DOMAIN_MANAGER", "DOMAIN", "DOMAIN_A"),
            ("SUBDOMAIN_MANAGER", "SUBDOMAIN", "SUB_A"),
        ]:
            self.source.grant("domain-persona", role, scope_type, scope_id)
        access = resolve_access(self.source, self.config, Identity("demo", "domain-persona"))
        self.assertEqual(self.source.run(ScopedQueries(access).application_owners(
            self.config, "2026-01"))["application_code"].tolist(), ["APP00013057"])
        self.source.grant("unmapped-domain", "DOMAIN_MANAGER", "DOMAIN", "NO_DOMAIN")
        with self.assertRaises(SecurityError):
            resolve_access(self.source, self.config, Identity("demo", "unmapped-domain"))

    def test_operations_are_blocked_in_python_and_rechecked_in_sql(self):
        owner = self.queries("demo-app-owner-a")
        for request in [
            lambda: owner.latest_pipeline_runs(self.config),
            lambda: owner.latest_reconciliations(self.config),
            lambda: owner.environment_run_counts(self.config),
            lambda: owner.data_quality(self.config, "2026-01"),
        ]:
            with self.assertRaises(SecurityError):
                request()
        admin = self.queries("demo-finops-admin")
        for bound in [admin.latest_pipeline_runs(self.config),
                      admin.latest_reconciliations(self.config),
                      admin.data_quality(self.config, "2026-01")]:
            self.assertFalse(self.source.run(bound).empty)
        bound = admin.latest_pipeline_runs(self.config)
        self.source.connection.execute("UPDATE entitlement SET is_active=FALSE "
                                       "WHERE principal_id='demo-finops-admin'")
        self.assertTrue(self.source.run(bound).empty)

    def test_injection_values_are_bound_not_interpolated(self):
        injection = "x' OR 1=1 --"
        self.source.grant(injection, "APPLICATION_OWNER", "APPLICATION", "APP00013057")
        self.source.connection.execute("UPDATE entitlement SET identity_provider='iap' "
                                       "WHERE principal_id=?", (injection,))
        access = resolve_access(self.source, self.config, Identity("iap", injection))
        bound = ScopedQueries(access).monthly_savings(self.config)
        self.assertNotIn(injection, bound.text)
        self.assertEqual(self.source.run(bound)["billing_month"].tolist(), ["2026-01", "2026-02"])
        with self.assertRaises(SecurityError):
            self.queries("demo-app-owner-a").services(self.config, "2026-01' OR 1=1 --")

    def test_environment_and_limits_are_validated(self):
        query = self.queries("demo-app-owner-a")
        with self.assertRaises(SecurityError):
            query.available_months(replace(self.config, environment="dev", data_catalog="finops_dev"))
        with self.assertRaises(SecurityError):
            resolve_access(self.source, replace(self.config, data_catalog="finops_dev"),
                           demo_identity("demo-app-owner-a"))
        for limit in [0, 101, True, "20"]:
            with self.assertRaises(SecurityError):
                query.services(self.config, "2026-01", limit)

    def test_backend_passes_native_query_parameters_to_connector(self):
        source = DatabricksDataSource()
        connection = MagicMock()
        cursor = connection.__enter__.return_value.cursor.return_value.__enter__.return_value
        with patch.object(source, "_connect", return_value=connection):
            source.query("SELECT :subject", {"subject": "a' OR 1=1 --"})
        cursor.execute.assert_called_once_with("SELECT :subject", parameters={"subject": "a' OR 1=1 --"})

    def test_live_validation_command_with_offline_fixture(self):
        results = validate(self.source, self.config, "2026-01")
        self.assertEqual([row["status"] for row in results], ["PASSED", "PASSED"])
        self.assertEqual([row["charge_lines"] for row in results], [2, 2])
        self.source.grant("demo-app-owner-a", "FINOPS_ADMIN", "ALL", "*")
        with self.assertRaises(AssertionError):
            validate(self.source, self.config, "2026-01")


class IdentityTests(unittest.TestCase):
    audience = "/projects/243421621568/locations/europe-west1/services/finops-center-private"

    def claims(self):
        return {"iss": "https://cloud.google.com/iap", "aud": self.audience,
                "sub": "verified-subject", "iat": 999, "exp": 1300}

    def test_explicit_modes_and_no_public_fallback(self):
        self.assertEqual(auth_mode({}), "public")
        self.assertEqual(auth_mode({"K_SERVICE": "finops-center"}), "public")
        self.assertEqual(auth_mode({"FINOPS_AUTH_MODE": "demo"}), "demo")
        for values in [
            {"FINOPS_AUTH_MODE": "unknown"},
            {"FINOPS_AUTH_MODE": "demo", "K_SERVICE": "finops-center"},
            {"FINOPS_AUTH_MODE": "iap"},
            {"K_SERVICE": "finops-center-private"},
        ]:
            with self.assertRaises(SecurityError):
                auth_mode(values)

    def test_unsigned_identity_headers_are_never_accepted(self):
        with self.assertRaises(SecurityError):
            iap_identity({"X-Goog-Authenticated-User-Email": "admin@example.invalid"}, self.audience)

    def test_signed_claims_and_case_insensitive_header(self):
        identity = iap_identity({"X-Goog-IAP-JWT-Assertion": "signed-test-token"}, self.audience,
                                decoder=lambda token, audience: self.claims(), now=1000)
        self.assertEqual(identity, Identity("iap", "verified-subject"))

    def test_wrong_audience_issuer_expiry_and_missing_subject_are_denied(self):
        for change in [{"aud": "other"}, {"iss": "other"}, {"exp": 999},
                       {"sub": ""}, {"iat": 2000}, {"exp": None}]:
            with self.subTest(change=change), self.assertRaises(SecurityError):
                iap_identity({"x-goog-iap-jwt-assertion": "test"}, self.audience,
                             decoder=lambda token, audience: {**self.claims(), **change}, now=1000)

    def test_signature_failure_is_sanitized(self):
        with self.assertRaisesRegex(SecurityError, "Identity verification failed") as result:
            iap_identity({"x-goog-iap-jwt-assertion": "secret-token"}, self.audience,
                         decoder=MagicMock(side_effect=ValueError("secret-token is invalid")))
        self.assertNotIn("secret-token", str(result.exception))

    def test_real_signature_validation_and_forgery_rejection(self):
        try:
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives import serialization
            from google.auth import jwt
        except ImportError:
            self.skipTest("Install the dashboard's google-auth and cryptography dependencies")
        key = ec.generate_private_key(ec.SECP256R1())
        private = key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption())
        public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                               serialization.PublicFormat.SubjectPublicKeyInfo)
        claims = {**self.claims(), "iat": int(time.time()) - 1, "exp": int(time.time()) + 300}
        from google.auth import crypt
        signer = crypt.ES256Signer.from_string(private, key_id="fixture-key")
        assertion = jwt.encode(signer, claims).decode()
        with patch("google.oauth2.id_token._fetch_certs", return_value={"fixture-key": public.decode()}):
            self.assertEqual(iap_identity({"x-goog-iap-jwt-assertion": assertion}, self.audience),
                             Identity("iap", "verified-subject"))
            prefix, payload, signature = assertion.split(".")
            forged = prefix + "." + payload + "." + ("A" if signature[0] != "A" else "B") + signature[1:]
            with self.assertRaises(SecurityError):
                iap_identity({"x-goog-iap-jwt-assertion": forged}, self.audience)


class ServingViewTests(unittest.TestCase):
    def test_sql_view_preserves_rows_cost_columns_and_charge_tags(self):
        # Execute the projection/CASE as SQL, adapting only Spark JSON/date UDFs
        # and CREATE OR REPLACE VIEW syntax. This is not Spark runtime evidence.
        statement = (ROOT / "platform/common/sql/security/04_create_dashboard_serving_view.sql")
        text = FixtureSource.translate(statement.read_text(encoding="utf-8"))
        text = text.replace("CREATE OR REPLACE VIEW", "CREATE VIEW")
        with sqlite3.connect(":memory:") as connection:
            connection.create_function("from_json", 2, lambda value, schema: value)
            def element_at(value, key):
                try:
                    return json.loads(value).get(key) if value else None
                except (ValueError, TypeError):
                    return None
            connection.create_function("element_at", 2, element_at)
            connection.create_function("to_date", 1, lambda value: value[:10] if value else None)
            connection.execute("""CREATE TABLE raw_source (
              Tags TEXT, billing_month TEXT, ChargePeriodStart TEXT, ResourceId TEXT,
              ResourceName TEXT, x_ResourceGroupName TEXT, RegionName TEXT, ServiceName TEXT,
              x_CostCenter TEXT, SubAccountId TEXT, SubAccountName TEXT, SkuId TEXT,
              x_SkuMeterCategory TEXT, x_SkuMeterName TEXT, ChargeCategory TEXT,
              ChargeSubcategory TEXT, ChargeFrequency TEXT, BilledCost REAL,
              EffectiveCost REAL, ListCost REAL, ContractedCost REAL, BillingCurrency TEXT,
              _ingestion_run_id TEXT, _ingested_at TEXT, PricingCategory TEXT,
              CommitmentDiscountType TEXT
            )""")
            for tag, billed, effective, component in [
                (json.dumps({"ApplicationCode-Symphony": "APP00013057"}), 100, 90, "Usage"),
                (None, -30, -30, "Adjustment"),
                ("invalid-json", 7, 6, "Usage"),
            ]:
                connection.execute("""INSERT INTO raw_source
                  (Tags,billing_month,ChargePeriodStart,ResourceId,BilledCost,EffectiveCost,
                   ListCost,ContractedCost,ChargeCategory,PricingCategory,CommitmentDiscountType)
                  VALUES (?, '2026-01','2026-01-01','r',?,?,120,110,?,'On-Demand',NULL)
                """, (tag, billed, effective, component))
            connection.executescript(text)
            result = connection.execute("SELECT COUNT(*),SUM(billed_cost),SUM(effective_cost),"
                                        "SUM(list_cost),SUM(contracted_cost) FROM charges").fetchone()
            self.assertEqual(result, (3, 77, 66, 360, 330))
            self.assertEqual(connection.execute("SELECT application_code FROM charges "
                                                "WHERE billed_cost=100").fetchone()[0], "APP00013057")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM charges "
                                                "WHERE application_code IS NULL").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT effective_cost_component FROM charges "
                                                "WHERE billed_cost=-30").fetchone()[0], "adjustment")


class ProtectedDashboardTests(unittest.TestCase):
    def setUp(self):
        import streamlit as st
        st.cache_data.clear()
        st.cache_resource.clear()
        self.source = FixtureSource()

    def tearDown(self):
        import streamlit as st
        st.cache_data.clear()
        st.cache_resource.clear()

    def test_persona_switch_and_revocation_have_no_shared_cached_results(self):
        from streamlit.testing.v1 import AppTest
        with (
            patch.dict(os.environ, {"FINOPS_AUTH_MODE": "demo"}, clear=True),
            patch("data_access.DatabricksDataSource", return_value=self.source),
        ):
            app = AppTest.from_file(str(APP / "app.py"), default_timeout=30).run()
            self.assertFalse(app.exception)
            app.selectbox(key="billing_month").select("2026-01").run()
            self.assertEqual(app.metric[0].value, "150,00 €")
            app.selectbox[0].select("demo-app-owner-b").run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, "180,00 €")
            app.selectbox[0].select("demo-app-owner-a").run()
            app.selectbox(key="billing_month").select("2026-01").run()
            self.assertEqual(app.metric[0].value, "150,00 €")
            self.source.connection.execute("UPDATE charges SET billed_cost=billed_cost+1 "
                                           "WHERE application_code='APP00013057' "
                                           "AND billing_month='2026-01' AND environment='prod'")
            app.run()
            self.assertEqual(app.metric[0].value, "152,00 €")
            self.source.connection.execute("UPDATE entitlement SET is_active=FALSE "
                                           "WHERE principal_id='demo-app-owner-a'")
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.metric), 0)
            self.assertIn("No active permission", app.error[0].value)

    def test_denied_persona_does_not_execute_business_queries(self):
        from streamlit.testing.v1 import AppTest
        with (
            patch.dict(os.environ, {"FINOPS_AUTH_MODE": "demo"}, clear=True),
            patch("data_access.DatabricksDataSource", return_value=self.source),
        ):
            app = AppTest.from_file(str(APP / "app.py"), default_timeout=30).run()
            self.source.calls.clear()
            app.selectbox[0].select("demo-no-access").run()
            self.assertEqual(len(app.metric), 0)
            self.assertEqual(len(self.source.calls), 1)
            self.assertIn("user_entitlement", self.source.calls[0][0])

    def test_iap_failure_stops_before_connection_without_public_fallback(self):
        from streamlit.testing.v1 import AppTest
        with (
            patch.dict(os.environ, {"FINOPS_AUTH_MODE": "iap", "FINOPS_IAP_AUDIENCE": "expected"},
                       clear=True),
            patch("data_access.DatabricksDataSource") as source,
        ):
            app = AppTest.from_file(str(APP / "app.py"), default_timeout=30).run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.metric), 0)
            self.assertIn("Authenticated identity is missing", app.error[0].value)
            source.assert_not_called()

    def test_restricted_pages_render_only_scoped_data_and_hide_operations(self):
        from streamlit.testing.v1 import AppTest
        class TestPage:
            def __init__(self, function, *, title, **kwargs):
                self.function, self.title = function, title
            def run(self):
                self.function()
        titles = ["Executive Overview", "Cost Drivers", "Savings",
                  "Allocation & Accountability", "Resources", "Knowledge Base", "Architecture"]
        for title in titles:
            with (
                self.subTest(page=title),
                patch.dict(os.environ, {"FINOPS_AUTH_MODE": "demo"}, clear=True),
                patch("data_access.DatabricksDataSource", return_value=self.source),
                patch("streamlit.Page", TestPage),
            ):
                def choose(pages, *, position):
                    self.assertNotIn("Operations & Quality", [page.title for page in pages])
                    return next(page for page in pages if page.title == title)
                with patch("streamlit.navigation", side_effect=choose):
                    app = AppTest.from_file(str(APP / "app.py"), default_timeout=30).run()
                self.assertFalse(app.exception)
                for frame in app.dataframe:
                    self.assertNotIn("BSN0003965", frame.value.to_csv(index=False))

    def test_negative_cost_center_totals_are_retained_as_signed_bars(self):
        from streamlit.testing.v1 import AppTest
        class TestPage:
            def __init__(self, function, *, title, **kwargs):
                self.function, self.title = function, title
            def run(self):
                self.function()
        # Give the default fixture persona global scope only in this isolated test.
        self.source.grant("demo-app-owner-a", "FINOPS_ADMIN", "ALL", "*")
        with (
            patch.dict(os.environ, {"FINOPS_AUTH_MODE": "demo"}, clear=True),
            patch("data_access.DatabricksDataSource", return_value=self.source),
            patch("streamlit.Page", TestPage),
            patch("streamlit.navigation", side_effect=lambda pages, **kwargs:
                  next(page for page in pages if page.title == "Allocation & Accountability")),
        ):
            app = AppTest.from_file(str(APP / "app.py"), default_timeout=30).run()
            app.selectbox(key="billing_month").select("2026-01").run()
            self.assertFalse(app.exception)
            frames = [frame.value for frame in app.dataframe if "cost_center" in frame.value]
            self.assertEqual(frames[0]["total_billed_cost"].min(), -300)
            self.assertTrue(any("Signed bars retain credits" in caption.value
                                for caption in app.caption))


if __name__ == "__main__":
    unittest.main()
