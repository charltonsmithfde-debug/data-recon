/**
 * cube.js - Enterprise Semantic Layer Configuration & Security Layer
 * 
 * Features:
 *  - Native DuckDB / DuckLake driver integration
 *  - SQL API (Postgres wire protocol) Authentication mapping
 *  - Strict Multi-Cube Role-Based Access Control (RBAC)
 *  - Dynamic POPIA Attribute Masking (Personal Identifiable Information)
 *  - Multi-tenant query cache partitioning via contextToAppId
 */

// US-1.4: every name in an allowedCubes array must resolve to a cube defined under
// model/cubes/. assertAllowlistsResolve() enforces that at module load, so a permission
// naming a cube nobody defined fails the container instead of quietly granting nothing.
//
// Eight names were removed on 2026-09-20 because no such cube exists. Each is owed by a
// later story -- re-add the name in the same change that defines the cube, never before:
//   FundAnalyticsMonthlyMetrics           -> US-4.3
//   MemberTransactions                    -> US-4.5 (define or delete)
//   AssetflowsMemberMonthly               -> US-4.5 (define or delete)
//   InFundExitMemberMonthly               -> US-4.5 (define or delete)
//   DigitalPortal                         -> US-4.5 (define or delete)
//   DigitalPortalEvents                   -> US-4.5 (define or delete)
//   DigitalPortalRegistrations            -> US-4.5 (define or delete)
//   AggregatedDigitalPortalRegistrations  -> US-4.5 (define or delete)
const ROLE_PERMISSIONS = {
  // 1. Executive role: unrestricted, the only role with PII in the clear
  ROLE_EXECUTIVE_ALL: {
    allowedCubes: ['*'],
    canViewPii: true,
    description: 'Executive & C-Suite Access with Full PII Visibility'
  },

  // 2. Finance & Member Analytics: core member measures and flows
  ROLE_FINANCE_MEMBER: {
    allowedCubes: [
      'MemberMonthly',
      'MemberMonthlyInvestment',
      // US-1.4: DimMember left SHARED_DIMENSIONS because it carries PII. This role drives
      // the US-6.1 demographic cards and is the fallback every verified caller lands on,
      // so it holds DimMember by explicit grant rather than by unconditional bypass.
      // memberNk stays masked for it -- canViewPii is false.
      'DimMember'
    ],
    canViewPii: false,
    description: 'Financial & Member Measures (PII Masked)'
  },

  // 3. Digital Operations: all four portal cubes were undefined and have been removed.
  //    The allowlist is deliberately empty until US-4.5 defines or deletes them. This role
  //    could already query nothing but shared dimensions; that is now stated rather than
  //    implied by four names that resolved to nothing.
  ROLE_DIGITAL_OPERATIONS: {
    allowedCubes: [],
    canViewPii: false,
    description: 'Digital Portal Metrics Only (no portal cube defined yet -- US-4.5)'
  },

  // 4. Investment Consultants: market values and transactions
  ROLE_INVESTMENTS: {
    allowedCubes: [
      'InvestmentsFundamental',
      'MemberMonthlyInvestment'
    ],
    canViewPii: false,
    description: 'Investment Products & Market Values'
  },

  // 5. Annuity & Preservation: quotations
  ROLE_ANNUITY: {
    allowedCubes: [
      'AnnuityQuotation'
    ],
    canViewPii: false,
    description: 'Annuity Quotes and In-Fund Preservation'
  }
};

// Dimension cubes any role may join to for filtering and grouping. These carry no measures
// and no PII.
//
// US-1.4: DimMember is deliberately NOT here. It exposes memberNk, memberGender,
// memberMaritalStatus, memberAgeBand and currentAge, and while it sat on this list every
// role bypassed the cube-boundary check to reach them. It is now allowlisted per role.
const SHARED_DIMENSIONS = [
  'DimDate',
  'DimFund',
  'DimClient',
  'DimEmployer',
  'DimPaypoint',
  'DimBrokerConsultant',
  'DimAnnuityProduct',
  'DimInvestmentProduct'
];

// ── US-1.4 criterion 2: fail the container on an allowlist that names a missing cube ─────
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

function definedCubeNames() {
  const modelDir = path.join(__dirname, 'model', 'cubes');
  let entries;
  try {
    entries = fs.readdirSync(modelDir);
  } catch (err) {
    throw new Error(
      `[ConfigError] US-1.4: cannot read the model layer at ${modelDir}, so role allowlists ` +
      `cannot be validated. Refusing to start. (${err.message})`
    );
  }
  const names = new Set();
  for (const file of entries) {
    if (!file.endsWith('.js')) continue;
    const modelSource = fs.readFileSync(path.join(modelDir, file), 'utf8');
    for (const match of modelSource.matchAll(/^cube\(\s*'([^']+)'/gm)) {
      names.add(match[1]);
    }
  }
  return names;
}

function assertAllowlistsResolve() {
  const defined = definedCubeNames();
  const problems = [];

  for (const [role, permissions] of Object.entries(ROLE_PERMISSIONS)) {
    for (const name of permissions.allowedCubes) {
      if (name !== '*' && !defined.has(name)) {
        problems.push(`ROLE_PERMISSIONS.${role}.allowedCubes names undefined cube '${name}'`);
      }
    }
  }
  for (const name of SHARED_DIMENSIONS) {
    if (!defined.has(name)) {
      problems.push(`SHARED_DIMENSIONS names undefined cube '${name}'`);
    }
  }

  if (problems.length > 0) {
    throw new Error(
      '[ConfigError] US-1.4: RBAC allowlists reference cubes that do not exist:\n  ' +
      problems.join('\n  ') +
      '\n  Cubes actually defined: ' + [...defined].sort().join(', ')
    );
  }
}

assertAllowlistsResolve();

const duckdbModule = require('@cubejs-backend/duckdb-driver');
const DuckDBDriver = duckdbModule.DuckDBDriver || duckdbModule.default || duckdbModule;

// US-2.2: credentials must come from the environment. No in-code fallback --
// a missing variable is a startup failure, not a silent downgrade to a baked-in key.
function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `${name} is not set. Provide it from Secret Manager (Cloud Run: --set-secrets).`
    );
  }
  return value;
}

// ── US-1.3 criteria 1 and 4: the API signing secret, required and vetted ─────────────────
// Cube verifies every REST/GraphQL token against CUBEJS_API_SECRET itself; it is read here only
// so the container fails on a secret that is absent, too short, or known-compromised. Cube
// 0.35 in dev mode silently generates a random secret instead, which turns a misconfigured
// deploy into "every thin-app token is invalid" with nothing in the log saying why.
const MIN_API_SECRET_BYTES = 32;   // RFC 7518 s3.2: an HS256 key is at least the hash width

// SHA-256 of secrets that must never be used again -- digests, not secrets, so this list is
// safe to read and safe to commit. The single entry is the API secret that was hardcoded in
// both servers before US-2.2. US-1.3 criterion 4 requires that a JWT signed with it is
// rejected, and the only way to guarantee that in code is to refuse to run with it configured.
// The 32-byte floor above already excludes this particular value -- it was 24 bytes -- but the
// floor is a rule about key strength, not about this key. This list is the guard that names it,
// and the place to add the next revocation.
const REVOKED_API_SECRET_SHA256 = new Set([
  'a714a688c5d0d354fad31fa06c11531fe47ab43f37c479c8cce2372ebcac7281'
]);

function assertApiSecretIsUsable(secret) {
  const bytes = Buffer.byteLength(secret, 'utf8');
  if (bytes < MIN_API_SECRET_BYTES) {
    throw new Error(
      `[ConfigError] US-1.3: CUBEJS_API_SECRET is ${bytes} bytes. HS256 requires at least ` +
      `${MIN_API_SECRET_BYTES} (RFC 7518 s3.2). Generate one with ` +
      `python -c "import secrets; print(secrets.token_urlsafe(48))".`
    );
  }
  const digest = crypto.createHash('sha256').update(secret, 'utf8').digest('hex');
  if (REVOKED_API_SECRET_SHA256.has(digest)) {
    throw new Error(
      '[ConfigError] US-1.3: CUBEJS_API_SECRET is a revoked secret -- it appeared in the ' +
      'repository, so every copy of it is compromised. Generate a new value and update the ' +
      'Secret Manager entry. Do not restore the old one.'
    );
  }
}

const CUBE_API_SECRET = requireEnv('CUBEJS_API_SECRET');
assertApiSecretIsUsable(CUBE_API_SECRET);

// ── US-1.3 criterion 2: the SQL API credential store ────────────────────────────────────
// checkSqlAuth used to `return { password: auth.password }`, which made Cube compare the
// caller's password against itself: every password was correct. The role came from the spelling
// of the username on top of that, so `exec...` or `admin` self-asserted ROLE_EXECUTIVE_ALL with
// PII in the clear (PRD P3). Both are gone. A caller must appear in CUBEJS_SQL_USERS, and that
// entry -- not the username -- decides the role.
//
// Shape (one JSON object, injected from Secret Manager, never a file in this tree):
//   { "metabase.quotations@sanlam.co.za": {
//       "password": "scrypt:<saltHex>:<keyHex>",
//       "role": "ROLE_ANNUITY" } }
//
// Mint an entry (the password is an argument, so it never enters the script text):
//   node -e "const c=require('crypto'),s=c.randomBytes(8);console.log('scrypt:'+ \
//     s.toString('hex')+':'+c.scryptSync(process.argv[1],s,32).toString('hex'))" '<password>'
//
// Only scrypt digests are accepted. A plaintext password in the store is a startup failure:
// this variable is readable by anyone who can describe the Cloud Run service.
//
// canViewPii is deliberately NOT read from the store -- it comes from ROLE_PERMISSIONS, so PII
// visibility has one definition and a credential entry cannot grant itself more than its role.
//
// Unset means the SQL API authenticates nobody. Cube's own CUBEJS_SQL_USER /
// CUBEJS_SQL_PASSWORD check is bypassed entirely whenever checkSqlAuth is defined, so
// "unconfigured" must not be allowed to mean "unauthenticated". Metabase and Power BI reach the
// semantic layer through this seam (docs/PBI_TO_DUCKLAKE_REPLICA_GUIDE.md s5.2); each needs an
// entry here, one per role it queries as.
const SCRYPT_KEY_BYTES = 32;
const SCRYPT_DIGEST_PATTERN = /^scrypt:([0-9a-f]{8,})+:([0-9a-f]{64})$/i;

function parseSqlUsers(raw) {
  if (!raw) return {};

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    throw new Error(
      `[ConfigError] US-1.3: CUBEJS_SQL_USERS is not valid JSON (${err.message}). Refusing to ` +
      'start -- a typo here would silently close the SQL API instead of failing the deploy.'
    );
  }
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(
      '[ConfigError] US-1.3: CUBEJS_SQL_USERS must be a JSON object of username -> entry.'
    );
  }

  const store = {};
  for (const [rawUsername, entry] of Object.entries(parsed)) {
    const username = String(rawUsername).trim().toLowerCase();
    if (!username) {
      throw new Error('[ConfigError] US-1.3: CUBEJS_SQL_USERS contains an empty username.');
    }
    if (entry === null || typeof entry !== 'object' || Array.isArray(entry)) {
      throw new Error(
        `[ConfigError] US-1.3: CUBEJS_SQL_USERS['${username}'] must be an object with ` +
        'password and role.'
      );
    }
    if (!ROLE_PERMISSIONS[entry.role]) {
      throw new Error(
        `[ConfigError] US-1.3: CUBEJS_SQL_USERS['${username}'] names role '${entry.role}', ` +
        'which has no ROLE_PERMISSIONS entry. queryRewrite would throw on that user\'s first ' +
        'query instead of at deploy time. Known roles: ' +
        Object.keys(ROLE_PERMISSIONS).join(', ')
      );
    }
    if (typeof entry.password !== 'string' || !SCRYPT_DIGEST_PATTERN.test(entry.password)) {
      throw new Error(
        `[ConfigError] US-1.3: CUBEJS_SQL_USERS['${username}'].password is not a scrypt ` +
        'digest of the form scrypt:<saltHex>:<keyHex>. Plaintext passwords are refused; see ' +
        'the minting command above cube.js\'s parseSqlUsers().'
      );
    }
    store[username] = { password: entry.password, role: entry.role };
  }
  return store;
}

const SQL_USERS = parseSqlUsers(process.env.CUBEJS_SQL_USERS);

if (Object.keys(SQL_USERS).length === 0) {
  console.warn(
    '[US-1.3] CUBEJS_SQL_USERS is not set: the SQL API (Postgres wire protocol) will ' +
    'authenticate nobody. Set it to grant Metabase, Power BI or any other SQL client access.'
  );
}

// ── US-8.3: the SQL API must actually be listening, and on the right variable ───────────
// Cube reads the Postgres-wire port from CUBEJS_PG_SQL_PORT. CUBEJS_SQL_PORT -- which this
// image's Dockerfile set and docs/PBI_TO_DUCKLAKE_REPLICA_GUIDE.md s5.2 recommended -- is not a
// Cube variable at all. It binds nothing and logs nothing, so the SQL API is simply absent and
// every Metabase or Power BI connection is refused at the TCP layer. That is indistinguishable
// from a firewall problem from the client side, which is why it is a startup error here rather
// than a warning nobody reads.
//
// Cloud Run cannot carry this protocol: it routes one container port, speaking HTTP/1, HTTP/2,
// gRPC or WebSockets. The Postgres wire protocol is raw TCP and cannot reach a Cloud Run service
// at any port. So this file serves two runtimes from one image:
//   * scbi-cube on Cloud Run -- REST/GraphQL on 4000 for the thin web app. No SQL variables at
//     all, which is why an absent SQL configuration must stay a valid configuration.
//   * the SQL runtime (cube/deploy_cube_sql_vm.sh) -- 5432, reachable privately by Metabase and
//     over IAP TCP forwarding by Power BI Desktop.
// docs/METABASE_CUBE_SQL.md is the operator's side of this.
const LEGACY_SQL_PORT_VAR = 'CUBEJS' + '_SQL_PORT';

function assertSqlApiIsCoherent() {
  // CUBEJS_SQL_SUPER_USER designates a login that may assume another user's security context
  // via `SET user`. The policy that would constrain it -- canSwitchSqlUser -- is not implemented
  // in this file, and its default is permissive once a super user exists. Set, it is a supported
  // way around the per-role boundary the credential store above exists to draw.
  if (process.env.CUBEJS_SQL_SUPER_USER) {
    throw new Error(
      '[ConfigError] US-8.3: CUBEJS_SQL_SUPER_USER is set but this config implements no ' +
      'canSwitchSqlUser policy, so that login can assume any role in CUBEJS_SQL_USERS -- ' +
      'including ROLE_EXECUTIVE_ALL, which is the only role with PII in the clear. Unset it, or ' +
      'implement canSwitchSqlUser in the same change that sets it.'
    );
  }

  const pgPort = process.env.CUBEJS_PG_SQL_PORT;
  const legacyPort = process.env[LEGACY_SQL_PORT_VAR];

  if (pgPort === undefined || pgPort === '') {
    if (legacyPort !== undefined && legacyPort !== '') {
      throw new Error(
        `[ConfigError] US-8.3: ${LEGACY_SQL_PORT_VAR} is set to '${legacyPort}' but that is not ` +
        'a Cube variable -- it binds nothing, and the SQL API is not listening. The variable ' +
        'Cube reads is CUBEJS_PG_SQL_PORT. Set CUBEJS_PG_SQL_PORT=5432 and remove ' +
        `${LEGACY_SQL_PORT_VAR}.`
      );
    }
    if (Object.keys(SQL_USERS).length > 0) {
      throw new Error(
        '[ConfigError] US-8.3: CUBEJS_SQL_USERS provisions SQL clients but CUBEJS_PG_SQL_PORT is ' +
        'not set, so nothing is listening for them. Every connection would be refused at the TCP ' +
        'layer with nothing in this log to explain it. Set CUBEJS_PG_SQL_PORT=5432, or drop ' +
        'CUBEJS_SQL_USERS if this runtime serves the REST API only.'
      );
    }
    return;   // REST-only runtime (Cloud Run). Valid, and deliberately so.
  }

  const port = Number(pgPort);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(
      `[ConfigError] US-8.3: CUBEJS_PG_SQL_PORT='${pgPort}' is not a usable TCP port. Cube ` +
      'coerces it with Number(), and a value that does not coerce leaves the SQL API silently ' +
      'unbound.'
    );
  }
  if (legacyPort !== undefined && legacyPort !== '') {
    console.warn(
      `[US-8.3] ${LEGACY_SQL_PORT_VAR} is set and is ignored by Cube. CUBEJS_PG_SQL_PORT=${port} ` +
      'is what is serving. Remove the stale variable.'
    );
  }
  if (Object.keys(SQL_USERS).length === 0) {
    console.warn(
      `[US-8.3] The SQL API is listening on ${port} with an empty credential store, so it will ` +
      'accept a TCP connection and reject every login. See the CUBEJS_SQL_USERS note above.'
    );
  }
}

assertSqlApiIsCoherent();

// Compared against when the username is unknown, so a login costs the same scrypt work either
// way and the store's membership cannot be probed by timing.
const ABSENT_USER_DIGEST = `scrypt:${'00'.repeat(8)}:${'00'.repeat(SCRYPT_KEY_BYTES)}`;

function verifySqlPassword(supplied, storedDigest) {
  if (typeof supplied !== 'string' || supplied.length === 0) return false;
  const [, saltHex, keyHex] = storedDigest.split(':');
  let derived;
  try {
    derived = crypto.scryptSync(supplied, Buffer.from(saltHex, 'hex'), SCRYPT_KEY_BYTES);
  } catch (err) {
    return false;
  }
  const expected = Buffer.from(keyHex, 'hex');
  if (derived.length !== expected.length) return false;
  return crypto.timingSafeEqual(derived, expected);
}

const GCS_ACCESS_KEY = requireEnv('CUBEJS_DB_DUCKDB_S3_ACCESS_KEY_ID');
const GCS_SECRET_KEY = requireEnv('CUBEJS_DB_DUCKDB_S3_SECRET_ACCESS_KEY');
const BUCKET = process.env.DUCKLAKE_GCS_BUCKET || 'scbi-ducklake-myanalyticsproduct';

const initSql = `
INSTALL httpfs;
LOAD httpfs;
SET s3_endpoint = 'storage.googleapis.com';
SET s3_url_style = 'path';
SET s3_access_key_id = '${GCS_ACCESS_KEY}';
SET s3_secret_access_key = '${GCS_SECRET_KEY}';
SET memory_limit = '3.5GB';
SET preserve_insertion_order = false;

CREATE SCHEMA IF NOT EXISTS scbi_cdp_mart;
CREATE SCHEMA IF NOT EXISTS scbi_sdp_mart;

CREATE OR REPLACE VIEW scbi_sdp_mart.dim_date AS
SELECT * FROM read_parquet('s3://${BUCKET}/scbi_sdp_mart/dim_date/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_member AS
SELECT * FROM read_parquet('s3://${BUCKET}/scbi_cdp_mart/cnf__dim_member/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_fund AS
SELECT * FROM read_parquet('s3://${BUCKET}/scbi_cdp_mart/cnf__dim_fund/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_client AS
SELECT * FROM read_parquet('s3://${BUCKET}/scbi_cdp_mart/cnf__dim_client/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_employer AS
SELECT * FROM read_parquet('s3://${BUCKET}/scbi_cdp_mart/cnf__dim_employer/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_paypoint AS
SELECT * FROM read_parquet('s3://${BUCKET}/scbi_cdp_mart/cnf__dim_paypoint/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_broker_consultant AS
SELECT * FROM read_parquet('s3://${BUCKET}/scbi_cdp_mart/cnf__dim_broker_consultant/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_annuity_product AS
SELECT * FROM read_parquet('s3://${BUCKET}/scbi_cdp_mart/cnf__dim_annuity_product/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__dim_investment_product AS
SELECT * FROM read_parquet('s3://${BUCKET}/scbi_cdp_mart/cnf__dim_investment_product/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_member_investment_aua AS
SELECT * FROM read_parquet('s3://${BUCKET}/scbi_cdp_mart/cnf__fact_member_investment_aua/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_inv_monthly_market_value AS
SELECT * FROM read_parquet('s3://${BUCKET}/scbi_cdp_mart/cnf__fact_inv_monthly_market_value/*.parquet');

CREATE OR REPLACE VIEW scbi_cdp_mart.cnf__fact_annuity_quotations AS
SELECT * FROM read_parquet('s3://${BUCKET}/scbi_cdp_mart/cnf__fact_annuity_quotations/*.parquet');
`;

module.exports = {
  // Configure database driver
  dbType: process.env.CUBEJS_DB_TYPE || 'duckdb',

  driverFactory: () => {
    return new DuckDBDriver({
      initSql: initSql
    });
  },

  // ── 1. SQL API Authentication (Postgres Wire Protocol) ──────────────────────
  // Power BI, Metabase, DBeaver and Excel authenticate here via a Postgres driver.
  //
  // US-1.3 criterion 2. Every rejection throws: Cube treats a thrown checkSqlAuth as a failed
  // login, and there is no return path that authenticates an unknown caller. The password is
  // echoed back only on the success path, *after* verifySqlPassword has already accepted it --
  // Cube's own comparison of that value is then a formality rather than the check. There is no
  // public user and no role inferred from the username.
  checkSqlAuth: async (req, auth) => {
    const username = typeof auth?.u === 'string' ? auth.u.trim().toLowerCase() : '';
    if (!username) {
      throw new Error(
        '[AuthDenied] US-1.3: the SQL API requires a username. There is no public user.'
      );
    }

    const entry = SQL_USERS[username];
    const accepted = verifySqlPassword(auth?.password, entry ? entry.password : ABSENT_USER_DIGEST);
    if (!entry || !accepted) {
      // One message for both cases: which of the two failed is not the caller's business.
      throw new Error(`[AuthDenied] US-1.3: SQL API login rejected for '${username}'.`);
    }

    return {
      password: auth.password,
      securityContext: {
        user: username,
        role: entry.role,
        // From ROLE_PERMISSIONS, never from the credential store -- see parseSqlUsers above.
        canViewPii: ROLE_PERMISSIONS[entry.role].canViewPii === true
      }
    };
  },

  // ── 2. Security Context & Multi-Tenant Cache Partitioning ─────────────────
  contextToAppId: ({ securityContext }) => {
    const role = securityContext?.role || 'ROLE_FINANCE_MEMBER';
    const piiTag = securityContext?.canViewPii ? 'PII_TRUE' : 'PII_FALSE';
    return `CUBE_APP_${role}_${piiTag}`;
  },

  // ── 3. Strict Role-Based Access Control (RBAC) Enforcement ────────────────
  queryRewrite: (query, { securityContext }) => {
    const role = securityContext?.role || 'ROLE_FINANCE_MEMBER';
    const permissions = ROLE_PERMISSIONS[role];

    if (!permissions) {
      throw new Error(`[SecurityException] Unauthorized: Role '${role}' has no defined permissions.`);
    }

    // Identify all cubes referenced in query measures, dimensions, filters, and segments
    const requestedCubes = new Set();
    const extractCubeName = (item) => {
      if (typeof item === 'string' && item.includes('.')) {
        return item.split('.')[0];
      }
      return null;
    };

    (query.measures || []).forEach(m => { const c = extractCubeName(m); if (c) requestedCubes.add(c); });
    (query.dimensions || []).forEach(d => { const c = extractCubeName(d); if (c) requestedCubes.add(c); });
    (query.segments || []).forEach(s => { const c = extractCubeName(s); if (c) requestedCubes.add(c); });
    (query.filters || []).forEach(f => {
      const c = extractCubeName(f.member);
      if (c) requestedCubes.add(c);
    });

    // Enforce strict cube boundaries. SHARED_DIMENSIONS is module-scoped (US-1.4) so the
    // startup assertion can validate it and it is not rebuilt on every query.
    for (const cubeName of requestedCubes) {
      if (SHARED_DIMENSIONS.includes(cubeName)) {
        continue;
      }
      const hasWildcard = permissions.allowedCubes.includes('*');
      const hasExplicitAccess = permissions.allowedCubes.includes(cubeName);

      if (!hasWildcard && !hasExplicitAccess) {
        throw new Error(
          `[AccessDenied] User with role '${role}' is strictly forbidden from querying cube '${cubeName}'.`
        );
      }
    }


    return query;
  }
};
