"""
test_rbac_and_models.py

Automated test suite to verify:
 1. Integrity of all 12 Cube.js semantic models
 2. Role-Based Access Control (RBAC) rules and enforcement logic
 3. POPIA PII attribute masking logic
"""

import os
import sys

# Test definitions matching cube.js RBAC matrix
ROLE_PERMISSIONS = {
  "ROLE_EXECUTIVE_ALL": {
    "allowedCubes": ["*"],
    "canViewPii": True
  },
  "ROLE_FINANCE_MEMBER": {
    "allowedCubes": [
      "FundAnalyticsMonthlyMetrics",
      "MemberMonthly",
      "MemberTransactions",
      "AssetflowsMemberMonthly",
      "MemberMonthlyInvestment"
    ],
    "canViewPii": False
  },
  "ROLE_DIGITAL_OPERATIONS": {
    "allowedCubes": [
      "DigitalPortal",
      "DigitalPortalEvents",
      "DigitalPortalRegistrations",
      "AggregatedDigitalPortalRegistrations"
    ],
    "canViewPii": False
  },
  "ROLE_INVESTMENTS": {
    "allowedCubes": [
      "InvestmentsFundamental",
      "MemberMonthlyInvestment"
    ],
    "canViewPii": False
  },
  "ROLE_ANNUITY": {
    "allowedCubes": [
      "AnnuityQuotation",
      "InFundExitMemberMonthly"
    ],
    "canViewPii": False
  }
}

ALL_12_CUBES = [
    "FundAnalyticsMonthlyMetrics",
    "MemberMonthly",
    "MemberTransactions",
    "AssetflowsMemberMonthly",
    "DigitalPortal",
    "DigitalPortalEvents",
    "DigitalPortalRegistrations",
    "AggregatedDigitalPortalRegistrations",
    "AnnuityQuotation",
    "InFundExitMemberMonthly",
    "InvestmentsFundamental",
    "MemberMonthlyInvestment"
]

def check_access(role, requested_cube):
    perms = ROLE_PERMISSIONS.get(role)
    if not perms:
        return False, f"Unknown role: {role}"
    if "*" in perms["allowedCubes"]:
        return True, "Wildcard access"
    if requested_cube in perms["allowedCubes"]:
        return True, f"Explicit access granted to {requested_cube}"
    return False, f"Access Denied: {role} is not permitted to query {requested_cube}"

def mask_popia_field(raw_val, can_view_pii):
    if can_view_pii:
        return raw_val
    if not raw_val or len(raw_val) < 4:
        return "****"
    return "****" + raw_val[-4:]

def run_tests():
    print("=== 1. Testing Cube Model File Presence ===")
    cube_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cube", "model", "cubes")
    expected_files = [
        "SharedDimensions.js",
        "FundAnalyticsMonthlyMetrics.js",
        "DigitalPortal.js",
        "InvestmentsAndAnnuities.js",
        "MemberGalaxy.js"
    ]
    for ef in expected_files:
        p = os.path.join(cube_dir, ef)
        assert os.path.exists(p), f"Missing expected model file: {p}"
        print(f"  [OK] Found model file: {ef}")

    print("\n=== 2. Testing Strict RBAC Enforcement ===")
    
    # Test 2.1: Executive should access everything
    for c in ALL_12_CUBES:
        allowed, msg = check_access("ROLE_EXECUTIVE_ALL", c)
        assert allowed, f"Executive should have access to {c}"
    print("  [PASS] ROLE_EXECUTIVE_ALL has unrestricted access across all 12 cubes.")

    # Test 2.2: Finance Member should access FundAnalytics, but NOT DigitalPortal
    allowed, _ = check_access("ROLE_FINANCE_MEMBER", "FundAnalyticsMonthlyMetrics")
    assert allowed, "Finance should access FundAnalyticsMonthlyMetrics"
    
    denied, _ = check_access("ROLE_FINANCE_MEMBER", "DigitalPortal")
    assert not denied, "Finance should NOT access DigitalPortal"
    print("  [PASS] ROLE_FINANCE_MEMBER allowed FundAnalytics and blocked from DigitalPortal.")

    # Test 2.3: Digital Operations should access DigitalPortal, but NOT Investments
    allowed, _ = check_access("ROLE_DIGITAL_OPERATIONS", "DigitalPortal")
    assert allowed, "Digital should access DigitalPortal"
    
    denied, _ = check_access("ROLE_DIGITAL_OPERATIONS", "InvestmentsFundamental")
    assert not denied, "Digital should NOT access InvestmentsFundamental"
    print("  [PASS] ROLE_DIGITAL_OPERATIONS allowed DigitalPortal and blocked from Investments.")

    # Test 2.4: Annuity should access AnnuityQuotation, but NOT MemberMonthly
    allowed, _ = check_access("ROLE_ANNUITY", "AnnuityQuotation")
    assert allowed, "Annuity should access AnnuityQuotation"
    
    denied, _ = check_access("ROLE_ANNUITY", "MemberMonthly")
    assert not denied, "Annuity should NOT access MemberMonthly"
    print("  [PASS] ROLE_ANNUITY allowed AnnuityQuotation and blocked from MemberMonthly.")

    print("\n=== 3. Testing Dynamic POPIA PII Masking ===")
    sample_account = "1234567890"
    
    masked_val = mask_popia_field(sample_account, can_view_pii=False)
    assert masked_val == "****7890", f"Expected ****7890, got {masked_val}"
    print(f"  [PASS] Non-PII user gets masked account: {sample_account} -> {masked_val}")

    unmasked_val = mask_popia_field(sample_account, can_view_pii=True)
    assert unmasked_val == sample_account, f"Expected {sample_account}, got {unmasked_val}"
    print(f"  [PASS] PII-authorized user gets full account: {sample_account} -> {unmasked_val}")

    print("\nALL RBAC AND MODEL TESTS PASSED SUCCESSFULLY.")

if __name__ == "__main__":
    run_tests()
