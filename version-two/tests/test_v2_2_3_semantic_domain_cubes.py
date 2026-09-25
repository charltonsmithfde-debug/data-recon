"""
Automated Verification Suite for Ticket V2-2.3:
Semantic Domain Cube Models & Multi-Table Join Graphs

Compatible with both standard library `unittest` and `pytest`.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
VERSION_TWO_DIR = PROJECT_ROOT / "version-two"
CUBE_DIR = VERSION_TWO_DIR / "cube"
MODEL_DIR = CUBE_DIR / "model"

if str(VERSION_TWO_DIR) not in sys.path:
    sys.path.insert(0, str(VERSION_TWO_DIR))

from ducklake.init_catalog import initialize_catalog


class TestV223SemanticDomainCubes(unittest.TestCase):
    """Test suite validating Cube 1.7.x semantic domain models and join graphs (V2-2.3)."""

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = tmp.name
        tmp.close()
        self.temp_db_url = f"sqlite:///{self.db_path}"
        initialize_catalog(db_url=self.temp_db_url)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_all_four_domain_model_files_load_and_compile(self):
        """AC1: Replaces outdated cube/model/cubes/*.js with validated Cube 1.7.x JavaScript models."""
        required_files = [
            "AnnuityQuotation.js",
            "InvestmentAnalysis.js",
            "MemberAnalysis.js",
            "SharedDimensions.js",
            "index.js",
        ]
        for fname in required_files:
            fpath = MODEL_DIR / fname
            self.assertTrue(fpath.is_file(), f"Missing domain model file: {fpath}")

        node_script = f"""
        const model = require({json.dumps(str(MODEL_DIR / "index.js"))});
        console.log(JSON.stringify(model.validateDomainCubes()));
        """
        proc = subprocess.run(
            ["node", "-e", node_script],
            capture_output=True,
            text=True,
            check=True,
        )
        validation = json.loads(proc.stdout.strip())

        self.assertTrue(validation["valid"], f"Domain cube validation errors: {validation['errors']}")
        for core_cube in ["AnnuityQuotation", "InvestmentAnalysis", "MemberAnalysis", "SharedDimensions"]:
            self.assertIn(core_cube, validation["cubes"])

    def test_member_age_replaces_nonexistent_current_age(self):
        """AC2: Fixes legacy column mismatches (binds member_age correctly instead of nonexistent current_age)."""
        for js_file in MODEL_DIR.glob("*.js"):
            content = js_file.read_text(encoding="utf-8")
            self.assertNotIn(
                "current_age",
                content,
                f"Legacy nonexistent column 'current_age' found in {js_file}",
            )

        member_content = (MODEL_DIR / "MemberAnalysis.js").read_text(encoding="utf-8")
        shared_content = (MODEL_DIR / "SharedDimensions.js").read_text(encoding="utf-8")
        self.assertIn("member_age", member_content)
        self.assertIn("member_age", shared_content)

    def test_primary_facts_and_dimension_joins_defined(self):
        """AC3: Defines primary facts (cnf__fact_annuity_quotations, cnf__fact_member_investment_aua) and dimension joins (dim_member, dim_scheme, dim_date)."""
        node_script = f"""
        const model = require({json.dumps(str(MODEL_DIR / "index.js"))});
        const cubes = model.loadDomainCubes();
        console.log(JSON.stringify({{
          AnnuityQuotation: {{
            sql_table: cubes.AnnuityQuotation.sql_table,
            joins: Object.keys(cubes.AnnuityQuotation.joins)
          }},
          InvestmentAnalysis: {{
            sql_table: cubes.InvestmentAnalysis.sql_table,
            joins: Object.keys(cubes.InvestmentAnalysis.joins)
          }},
          MemberAnalysis: {{
            sql_table: cubes.MemberAnalysis.sql_table,
            joins: Object.keys(cubes.MemberAnalysis.joins)
          }}
        }}));
        """
        proc = subprocess.run(
            ["node", "-e", node_script],
            capture_output=True,
            text=True,
            check=True,
        )
        meta = json.loads(proc.stdout.strip())

        self.assertEqual(
            meta["AnnuityQuotation"]["sql_table"],
            "lake.scbi_cdp_mart.cnf__fact_annuity_quotations",
        )
        self.assertEqual(
            meta["InvestmentAnalysis"]["sql_table"],
            "lake.scbi_cdp_mart.cnf__fact_member_investment_aua",
        )
        self.assertEqual(
            meta["MemberAnalysis"]["sql_table"],
            "lake.scbi_cdp_mart.cnf__fact_member_investment_aua",
        )

        for cube_name in ["AnnuityQuotation", "InvestmentAnalysis", "MemberAnalysis"]:
            joins = meta[cube_name]["joins"]
            self.assertIn("dim_member", joins)
            self.assertIn("dim_scheme", joins)
            self.assertIn("dim_date", joins)
            self.assertIn("DimMember", joins)
            self.assertIn("DimScheme", joins)
            self.assertIn("DimDate", joins)

    def test_standard_business_measures_and_sample_queries_execute(self):
        """AC4: Establishes standard business measures (totalAua, activeMemberCount, quotationCount, averageCommissionRate) and executes sample queries across all 4 domain cubes."""
        node_script = f"""
        const cube = require({json.dumps(str(CUBE_DIR / "cube.js"))});
        const model = require({json.dumps(str(MODEL_DIR / "index.js"))});

        (async () => {{
          const driver = new cube.EmbeddedDuckLakeDriver({{
            catalogDbPath: {json.dumps(self.db_path)}
          }});
          try {{
            const annuityRes = await model.executeDomainQuery(
              driver,
              {{
                measures: ['AnnuityQuotation.quotationCount', 'AnnuityQuotation.averageCommissionRate'],
                dimensions: ['DimMember.member_age', 'DimScheme.schemeName', 'DimDate.calendarYear']
              }},
              {{ role: 'ROLE_ANNUITY_ANALYST', canViewPii: false }}
            );

            const investmentRes = await model.executeDomainQuery(
              driver,
              {{
                measures: ['InvestmentAnalysis.totalAua', 'InvestmentAnalysis.averageCommissionRate'],
                dimensions: ['InvestmentAnalysis.ageBand', 'DimScheme.schemeType']
              }},
              {{ role: 'ROLE_INVESTMENT_ANALYST', canViewPii: false }}
            );

            const memberRes = await model.executeDomainQuery(
              driver,
              {{
                measures: ['MemberAnalysis.activeMemberCount', 'MemberAnalysis.totalAua', 'MemberAnalysis.averageCommissionRate'],
                dimensions: ['MemberAnalysis.member_age', 'MemberAnalysis.id_number']
              }},
              {{ role: 'ROLE_FINANCE_MEMBER', canViewPii: false }}
            );

            const sharedRes = await model.executeDomainQuery(
              driver,
              {{
                measures: ['SharedDimensions.schemeCount'],
                dimensions: ['SharedDimensions.schemeName', 'SharedDimensions.schemeType']
              }},
              {{ role: 'ROLE_AUDIT_COMPLIANCE', canViewPii: false }}
            );

            console.log(JSON.stringify({{
              annuityRes,
              investmentRes,
              memberRes,
              sharedRes
            }}));
          }} finally {{
            await driver.release();
          }}
        }})().catch((e) => {{
          console.error(e);
          process.exit(1);
        }});
        """
        proc = subprocess.run(
            ["node", "-e", node_script],
            capture_output=True,
            text=True,
            check=True,
        )
        results = json.loads(proc.stdout.strip())

        # 1. AnnuityQuotation (cnf__fact_annuity_quotations = 129,954 rows)
        self.assertEqual(
            results["annuityRes"]["data"][0]["AnnuityQuotation.quotationCount"],
            129954,
        )
        self.assertEqual(
            results["annuityRes"]["data"][0]["AnnuityQuotation.averageCommissionRate"],
            2.75,
        )
        self.assertEqual(
            set(results["annuityRes"]["joinedCubes"]),
            {"DimMember", "DimScheme", "DimDate"},
        )

        # 2. InvestmentAnalysis (cnf__fact_member_investment_aua = 10,874,107 rows)
        self.assertGreater(
            results["investmentRes"]["data"][0]["InvestmentAnalysis.totalAua"],
            0,
        )
        self.assertEqual(
            results["investmentRes"]["data"][0]["InvestmentAnalysis.averageCommissionRate"],
            2.75,
        )

        # 3. MemberAnalysis (cnf__fact_member_investment_aua = 29,209,326 rows, masked id_number)
        self.assertEqual(
            results["memberRes"]["data"][0]["MemberAnalysis.activeMemberCount"],
            29209326,
        )
        self.assertIn(
            "sha256(CAST(",
            results["memberRes"]["compiledDimensions"]["MemberAnalysis.id_number"],
        )
        self.assertEqual(
            results["memberRes"]["compiledDimensions"]["MemberAnalysis.member_age"],
            "MemberAnalysis.member_age",
        )

        # 4. SharedDimensions (cnf__dim_fund = 6,258 schemes)
        self.assertEqual(
            results["sharedRes"]["data"][0]["SharedDimensions.schemeCount"],
            6258,
        )


if __name__ == "__main__":
    unittest.main()
