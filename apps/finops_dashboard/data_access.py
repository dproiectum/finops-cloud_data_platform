"""Read-only Databricks SQL access using the Databricks App identity."""

from __future__ import annotations

import os

import pandas as pd


class DatabricksDataSource:
    label = "Databricks SQL · Unity Catalog"

    def _connect(self):
        try:
            from databricks import sql
            from databricks.sdk import WorkspaceClient
            from databricks.sdk.core import Config
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "Install databricks-sql-connector and databricks-sdk"
            ) from exc

        config = Config()
        hostname = (
            os.getenv("DATABRICKS_SERVER_HOSTNAME")
            or os.getenv("DATABRICKS_HOST")
            or config.host
            or ""
        ).removeprefix("https://").removeprefix("http://")
        http_path = os.getenv("DATABRICKS_HTTP_PATH", "")
        warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID", "")
        if not http_path and warehouse_id:
            warehouse = WorkspaceClient().warehouses.get(id=warehouse_id)
            if warehouse.odbc_params is not None:
                http_path = warehouse.odbc_params.path or ""
                hostname = warehouse.odbc_params.hostname or hostname
        if not hostname or not http_path:
            raise ValueError(
                "Add a SQL Warehouse app resource or provide DATABRICKS_HTTP_PATH"
            )
        return sql.connect(
            server_hostname=hostname,
            http_path=http_path,
            credentials_provider=lambda: config.authenticate,
            _use_arrow_native_complex_types=False,
        )

    def query(self, sql_text: str) -> pd.DataFrame:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql_text)
                return cursor.fetchall_arrow().to_pandas()

    def healthcheck(self) -> None:
        self.query("SELECT 1 AS ok")
