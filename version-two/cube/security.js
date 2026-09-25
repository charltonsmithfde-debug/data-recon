/**
 * version-two/cube/security.js
 * Ticket: V2-2.2 — Server-Enforced RBAC & Dynamic POPIA Masking Security Context
 *
 * Responsibilities:
 *  1. Verifies HS256 JWT tokens and extracts `role` and `canViewPii` into `securityContext`.
 *  2. Enforces compile-time role cube allowlists (`ROLE_PERMISSIONS[role].allowedCubes`),
 *     rejecting unauthorized cube queries with HTTP 403 Forbidden.
 *  3. Dynamically compiles POPIA PII dimensions (`id_number`, `member_id`, `client_name`, `member_nk`)
 *     to salted SHA-256 hashes whenever `canViewPii === false`.
 *  4. Verifies SQL API credentials using constant-time `scrypt` hash comparison (`crypto.scryptSync`
 *     + `crypto.timingSafeEqual`), rejecting forged or plaintext credentials.
 *  5. Resolves corporate identity emails against `thin-web-app/role_assignments.json` (ADR-0003).
 */

'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const CUBE_DIR = __dirname;
const PROJECT_ROOT = path.resolve(CUBE_DIR, '..', '..');
const DEFAULT_ROSTER_PATH = path.join(PROJECT_ROOT, 'thin-web-app', 'role_assignments.json');

const MIN_API_SECRET_BYTES = 32;
const SCRYPT_SALT_BYTES = 8;
const SCRYPT_KEY_BYTES = 32;
const SCRYPT_DIGEST_PATTERN = /^scrypt:([0-9a-f]{16,}):([0-9a-f]{64})$/i;
const ABSENT_USER_DIGEST = `scrypt:${'00'.repeat(SCRYPT_SALT_BYTES)}:${'00'.repeat(SCRYPT_KEY_BYTES)}`;

const DEFAULT_POPIA_SALT = process.env.POPIA_HASH_SALT || 'scbi-popia-v2-domain-salt';

/**
 * Authoritative Role Permissions Matrix (PRD §5.2 & ADR-0003).
 * Supports both V2 domain cubes and V1 legacy cube aliases for zero-downtime migration.
 */
const ROLE_PERMISSIONS = {
  ROLE_EXECUTIVE_ALL: {
    allowedCubes: ['*'],
    canViewPii: true,
    description: 'Executive leadership with full cube access and authorized PII visibility'
  },
  ROLE_INVESTMENT_ANALYST: {
    allowedCubes: [
      'InvestmentAnalysis',
      'SharedDimensions',
      'InvestmentsFundamental',
      'MemberMonthlyInvestment'
    ],
    canViewPii: false,
    description: 'Portfolio & asset managers (InvestmentAnalysis + SharedDimensions, PII masked)'
  },
  ROLE_ANNUITY_ANALYST: {
    allowedCubes: ['AnnuityQuotation', 'SharedDimensions'],
    canViewPii: false,
    description: 'Actuarial & annuity operations (AnnuityQuotation + SharedDimensions, PII masked)'
  },
  ROLE_MEMBER_OPERATIONS: {
    allowedCubes: [
      'MemberAnalysis',
      'SharedDimensions',
      'MemberMonthly',
      'MemberMonthlyInvestment',
      'DimMember'
    ],
    canViewPii: true,
    description: 'Pension fund administrators (MemberAnalysis + SharedDimensions, Role-Authorized PII)'
  },
  ROLE_AUDIT_COMPLIANCE: {
    allowedCubes: ['*'],
    canViewPii: false,
    description: 'Risk & data privacy auditors (All cubes read-only, PII masked)'
  },
  // V1 Role Roster & SQL API Compatibility Aliases
  ROLE_FINANCE_MEMBER: {
    allowedCubes: [
      'MemberAnalysis',
      'SharedDimensions',
      'MemberMonthly',
      'MemberMonthlyInvestment',
      'DimMember'
    ],
    canViewPii: false,
    description: 'Financial & Member Measures (Least-privilege default fallback, PII masked)'
  },
  ROLE_INVESTMENTS: {
    allowedCubes: [
      'InvestmentAnalysis',
      'SharedDimensions',
      'InvestmentsFundamental',
      'MemberMonthlyInvestment'
    ],
    canViewPii: false,
    description: 'Investment Products & Market Values (PII masked)'
  },
  ROLE_ANNUITY: {
    allowedCubes: ['AnnuityQuotation', 'SharedDimensions'],
    canViewPii: false,
    description: 'Annuity Quotations & In-Fund Preservation (PII masked)'
  },
  ROLE_DIGITAL_OPERATIONS: {
    allowedCubes: ['SharedDimensions'],
    canViewPii: false,
    description: 'Digital Operations (SharedDimensions only, PII masked)'
  }
};

/**
 * Shared non-PII dimension cubes accessible across roles for filtering and grouping.
 */
const SHARED_DIMENSIONS = [
  'SharedDimensions',
  'DimDate',
  'DimFund',
  'DimScheme',
  'DimClient',
  'DimEmployer',
  'DimPaypoint',
  'DimBrokerConsultant',
  'DimAnnuityProduct',
  'DimInvestmentProduct'
];

/**
 * Dimension fields classified as Personal Identifiable Information under POPIA.
 */
const PII_DIMENSIONS = new Set(['id_number', 'member_id', 'client_name', 'member_nk']);

/**
 * Custom error carrying HTTP 403 status code for RBAC/security denials.
 */
class ForbiddenSecurityError extends Error {
  constructor(message, statusCode = 403) {
    super(message);
    this.name = 'ForbiddenSecurityError';
    this.statusCode = statusCode;
    this.httpStatus = statusCode;
    this.status = statusCode;
  }
}

function base64UrlEncode(input) {
  const buf = Buffer.isBuffer(input) ? input : Buffer.from(String(input), 'utf8');
  return buf.toString('base64url');
}

function base64UrlDecode(input) {
  return Buffer.from(String(input), 'base64url');
}

/**
 * Validates that the configured HS256 secret meets RFC 7518 minimum length (32 bytes).
 *
 * @param {string} secret
 */
function assertValidApiSecret(secret) {
  if (!secret || typeof secret !== 'string') {
    throw new ForbiddenSecurityError('[AuthError] CUBEJS_API_SECRET is missing.', 401);
  }
  const byteLen = Buffer.byteLength(secret, 'utf8');
  if (byteLen < MIN_API_SECRET_BYTES) {
    throw new ForbiddenSecurityError(
      `[ConfigError] CUBEJS_API_SECRET is ${byteLen} bytes; HS256 requires >= ${MIN_API_SECRET_BYTES} bytes.`,
      500
    );
  }
}

/**
 * Mints a signed HS256 JWT token for testing and gateway propagation.
 *
 * @param {Record<string, any>} payload
 * @param {string} secret
 * @returns {string}
 */
function signHs256Jwt(payload, secret) {
  assertValidApiSecret(secret);
  const header = { alg: 'HS256', typ: 'JWT' };
  const nowSec = Math.floor(Date.now() / 1000);
  const body = {
    iat: nowSec,
    exp: nowSec + 3600,
    ...payload
  };
  const signingInput = `${base64UrlEncode(JSON.stringify(header))}.${base64UrlEncode(JSON.stringify(body))}`;
  const signature = crypto
    .createHmac('sha256', Buffer.from(secret, 'utf8'))
    .update(signingInput, 'utf8')
    .digest('base64url');
  return `${signingInput}.${signature}`;
}

/**
 * Verifies an HS256 JWT token in constant time and returns its decoded payload.
 *
 * @param {string} token
 * @param {string} secret
 * @returns {Record<string, any>}
 */
function verifyHs256Jwt(token, secret) {
  assertValidApiSecret(secret);
  if (!token || typeof token !== 'string') {
    throw new ForbiddenSecurityError('[AuthDenied] Missing Authorization bearer token.', 401);
  }

  const rawToken = token.replace(/^Bearer\s+/i, '').trim();
  const parts = rawToken.split('.');
  if (parts.length !== 3) {
    throw new ForbiddenSecurityError('[AuthDenied] Malformed JWT token structure.', 401);
  }

  const [headerB64, payloadB64, signatureB64] = parts;
  let header;
  let payload;
  try {
    header = JSON.parse(base64UrlDecode(headerB64).toString('utf8'));
    payload = JSON.parse(base64UrlDecode(payloadB64).toString('utf8'));
  } catch (_err) {
    throw new ForbiddenSecurityError('[AuthDenied] Invalid JWT JSON encoding.', 401);
  }

  if (header.alg !== 'HS256') {
    throw new ForbiddenSecurityError(
      `[AuthDenied] Unsupported JWT algorithm '${header.alg}'. Expected HS256.`,
      401
    );
  }

  const signingInput = `${headerB64}.${payloadB64}`;
  const expectedSig = crypto
    .createHmac('sha256', Buffer.from(secret, 'utf8'))
    .update(signingInput, 'utf8')
    .digest();

  let providedSig;
  try {
    providedSig = base64UrlDecode(signatureB64);
  } catch (_err) {
    throw new ForbiddenSecurityError('[AuthDenied] Invalid JWT signature encoding.', 401);
  }

  if (
    expectedSig.length !== providedSig.length ||
    !crypto.timingSafeEqual(expectedSig, providedSig)
  ) {
    throw new ForbiddenSecurityError('[AuthDenied] Invalid JWT signature.', 401);
  }

  const nowSec = Math.floor(Date.now() / 1000);
  if (typeof payload.exp === 'number' && payload.exp < nowSec) {
    throw new ForbiddenSecurityError('[AuthDenied] JWT token has expired.', 401);
  }

  return payload;
}

/**
 * Extracts normalized `securityContext` (`role`, `canViewPii`, `sub`) from verified JWT claims.
 * Enforces that `canViewPii` can only be true if the role itself is permitted PII visibility
 * in `ROLE_PERMISSIONS`.
 *
 * @param {Record<string, any>} claims
 * @returns {{ sub: string, role: string, canViewPii: boolean, claims: Record<string, any> }}
 */
function extractSecurityContextFromClaims(claims = {}) {
  const rawRole = typeof claims.role === 'string' ? claims.role.trim() : 'ROLE_FINANCE_MEMBER';
  const role = ROLE_PERMISSIONS[rawRole] ? rawRole : 'ROLE_FINANCE_MEMBER';
  const rolePerms = ROLE_PERMISSIONS[role];

  // Accept either camelCase `canViewPii` or snake_case `can_view_pii` from token payload,
  // capped by the authoritative role capability in ROLE_PERMISSIONS.
  const claimRequestedPii =
    claims.canViewPii === true || claims.can_view_pii === true;
  const canViewPii = Boolean(rolePerms.canViewPii && claimRequestedPii);

  return {
    sub: String(claims.sub || claims.u || claims.email || 'anonymous'),
    role,
    canViewPii,
    claims
  };
}

/**
 * Cube.js `checkAuth` hook: verifies Bearer HS256 token and populates `req.securityContext`.
 *
 * @param {object} req
 * @param {string} auth
 * @param {string} [secretOverride]
 */
async function checkAuth(req, auth, secretOverride) {
  const secret =
    secretOverride ||
    process.env.CUBEJS_API_SECRET ||
    'local-dev-hs256-secret-key-minimum-32-bytes!!';
  const token = auth || req?.headers?.authorization || req?.headers?.Authorization;
  const decoded = verifyHs256Jwt(token, secret);
  const securityContext = extractSecurityContextFromClaims(decoded);
  if (req && typeof req === 'object') {
    req.securityContext = securityContext;
  }
  return securityContext;
}

/**
 * Resolves an authenticated user's email against `thin-web-app/role_assignments.json` (ADR-0003).
 * Unknown emails fall back to least-privileged `ROLE_FINANCE_MEMBER` with `canViewPii: false`.
 *
 * @param {string} email
 * @param {string} [rosterPath=DEFAULT_ROSTER_PATH]
 * @returns {{ email: string, role: string, canViewPii: boolean, groups: Array<string> }}
 */
function resolveUserRoleFromRoster(email, rosterPath = DEFAULT_ROSTER_PATH) {
  const normalizedEmail = String(email || '').trim().toLowerCase();
  let roster = {};
  if (fs.existsSync(rosterPath)) {
    try {
      roster = JSON.parse(fs.readFileSync(rosterPath, 'utf8'));
    } catch (_err) {
      roster = {};
    }
  }

  const entry = roster[normalizedEmail];
  if (!entry || typeof entry !== 'object') {
    return {
      email: normalizedEmail,
      role: 'ROLE_FINANCE_MEMBER',
      canViewPii: false,
      groups: []
    };
  }

  const role = ROLE_PERMISSIONS[entry.role] ? entry.role : 'ROLE_FINANCE_MEMBER';
  const canViewPii = Boolean(
    ROLE_PERMISSIONS[role].canViewPii &&
      (entry.can_view_pii === true || entry.canViewPii === true)
  );

  return {
    email: normalizedEmail,
    role,
    canViewPii,
    groups: Array.isArray(entry.groups) ? entry.groups : []
  };
}

/**
 * Dynamically compiles a POPIA-protected dimension SQL expression.
 * When `canViewPii === true`, returns the raw SQL column expression.
 * When `canViewPii === false`, compiles to a salted SHA-256 hash expression in SQL.
 *
 * @param {string} columnExpr - e.g. `${CUBE}.id_number` or `dim_member.member_id`
 * @param {object} [securityContext]
 * @param {string} [salt=DEFAULT_POPIA_SALT]
 * @returns {string}
 */
function compilePiiDimensionSql(columnExpr, securityContext = {}, salt = DEFAULT_POPIA_SALT) {
  const ctx =
    securityContext && securityContext.securityContext
      ? securityContext.securityContext
      : securityContext || {};
  const role = ctx.role && ROLE_PERMISSIONS[ctx.role] ? ctx.role : 'ROLE_FINANCE_MEMBER';
  const allowedByRole = ROLE_PERMISSIONS[role].canViewPii === true;
  const canViewPii = Boolean(allowedByRole && ctx.canViewPii === true);

  if (canViewPii) {
    return String(columnExpr);
  }
  const safeSalt = String(salt).replace(/'/g, "''");
  return `sha256(CAST(${columnExpr} AS VARCHAR) || '${safeSalt}')`;
}

/**
 * Computes the deterministic salted SHA-256 hex digest for a raw PII value (used in query
 * result verification and local driver execution).
 *
 * @param {string|number|null} value
 * @param {string} [salt=DEFAULT_POPIA_SALT]
 * @returns {string|null}
 */
function hashPiiValue(value, salt = DEFAULT_POPIA_SALT) {
  if (value === null || value === undefined) {
    return null;
  }
  return crypto
    .createHash('sha256')
    .update(`${String(value)}${salt}`, 'utf8')
    .digest('hex');
}

/**
 * Redacts PII dimension keys (`id_number`, `member_id`, `client_name`, `member_nk`) in a row
 * object when `canViewPii === false`.
 *
 * @param {Record<string, any>} row
 * @param {object} securityContext
 * @param {string} [salt=DEFAULT_POPIA_SALT]
 * @returns {Record<string, any>}
 */
function maskRowPiiFields(row, securityContext = {}, salt = DEFAULT_POPIA_SALT) {
  const ctx =
    securityContext && securityContext.securityContext
      ? securityContext.securityContext
      : securityContext || {};
  const role = ctx.role && ROLE_PERMISSIONS[ctx.role] ? ctx.role : 'ROLE_FINANCE_MEMBER';
  const canViewPii = Boolean(ROLE_PERMISSIONS[role].canViewPii && ctx.canViewPii === true);
  if (canViewPii) {
    return { ...row };
  }

  const out = {};
  for (const [key, val] of Object.entries(row || {})) {
    const shortField = key.includes('.') ? key.split('.').pop() : key;
    if (PII_DIMENSIONS.has(shortField)) {
      out[key] = hashPiiValue(val, salt);
    } else {
      out[key] = val;
    }
  }
  return out;
}

/**
 * Cube.js `queryRewrite` hook:
 *  1. Validates the caller's role in `ROLE_PERMISSIONS`.
 *  2. Extracts all cubes referenced in `measures`, `dimensions`, `segments`, `timeDimensions`, and `filters`.
 *  3. Rejects any cube outside `ROLE_PERMISSIONS[role].allowedCubes` (unless in `SHARED_DIMENSIONS`)
 *     with `ForbiddenSecurityError` (`statusCode = 403`).
 *  4. Annotates the query with compiled PII masking metadata (`__popiaMasking`) for downstream verification.
 *
 * @param {Record<string, any>} query
 * @param {{ securityContext?: object }} context
 * @returns {Record<string, any>}
 */
function queryRewrite(query, context = {}) {
  const rawCtx = context?.securityContext || context || {};
  const role = rawCtx.role || 'ROLE_FINANCE_MEMBER';
  const permissions = ROLE_PERMISSIONS[role];

  if (!permissions) {
    throw new ForbiddenSecurityError(
      `[AccessDenied] HTTP 403 Forbidden: Role '${role}' has no defined permissions.`,
      403
    );
  }

  const requestedCubes = new Set();
  const extractCubeName = (memberExpr) => {
    if (typeof memberExpr === 'string' && memberExpr.includes('.')) {
      return memberExpr.split('.')[0];
    }
    return null;
  };

  for (const m of query.measures || []) {
    const c = extractCubeName(m);
    if (c) requestedCubes.add(c);
  }
  for (const d of query.dimensions || []) {
    const c = extractCubeName(d);
    if (c) requestedCubes.add(c);
  }
  for (const s of query.segments || []) {
    const c = extractCubeName(s);
    if (c) requestedCubes.add(c);
  }
  for (const td of query.timeDimensions || []) {
    const c = extractCubeName(td?.dimension);
    if (c) requestedCubes.add(c);
  }
  for (const f of query.filters || []) {
    const c = extractCubeName(f?.member || f?.dimension);
    if (c) requestedCubes.add(c);
  }

  for (const cubeName of requestedCubes) {
    if (SHARED_DIMENSIONS.includes(cubeName)) {
      continue;
    }
    const hasWildcard = permissions.allowedCubes.includes('*');
    const hasExplicitAccess = permissions.allowedCubes.includes(cubeName);
    if (!hasWildcard && !hasExplicitAccess) {
      throw new ForbiddenSecurityError(
        `[AccessDenied] HTTP 403 Forbidden: Role '${role}' is not authorized to query cube '${cubeName}'.`,
        403
      );
    }
  }

  const effectiveCanViewPii = Boolean(permissions.canViewPii && rawCtx.canViewPii === true);
  const compiledDimensionSql = {};

  for (const dim of query.dimensions || []) {
    if (typeof dim === 'string' && dim.includes('.')) {
      const [cubeName, fieldName] = dim.split('.');
      if (PII_DIMENSIONS.has(fieldName)) {
        compiledDimensionSql[dim] = compilePiiDimensionSql(
          `${cubeName}.${fieldName}`,
          { role, canViewPii: effectiveCanViewPii }
        );
      } else {
        compiledDimensionSql[dim] = `${cubeName}.${fieldName}`;
      }
    }
  }

  return {
    ...query,
    __securityContext: {
      role,
      canViewPii: effectiveCanViewPii
    },
    __compiledDimensionSql: compiledDimensionSql
  };
}

/**
 * Generates an `scrypt:<saltHex>:<keyHex>` password digest for SQL API credentials.
 *
 * @param {string} password
 * @param {Buffer} [saltBuf]
 * @returns {string}
 */
function scryptDigest(password, saltBuf) {
  const salt = saltBuf || crypto.randomBytes(SCRYPT_SALT_BYTES);
  const key = crypto.scryptSync(String(password), salt, SCRYPT_KEY_BYTES);
  return `scrypt:${salt.toString('hex')}:${key.toString('hex')}`;
}

/**
 * Verifies a plaintext SQL API password against a stored `scrypt:<saltHex>:<keyHex>` digest
 * using `crypto.timingSafeEqual`.
 *
 * @param {string} suppliedPassword
 * @param {string} storedDigest
 * @returns {boolean}
 */
function verifySqlPassword(suppliedPassword, storedDigest) {
  if (typeof suppliedPassword !== 'string' || suppliedPassword.length === 0) {
    return false;
  }
  if (typeof storedDigest !== 'string' || !SCRYPT_DIGEST_PATTERN.test(storedDigest)) {
    return false;
  }
  const [, saltHex, keyHex] = storedDigest.split(':');
  let derived;
  try {
    derived = crypto.scryptSync(
      suppliedPassword,
      Buffer.from(saltHex, 'hex'),
      SCRYPT_KEY_BYTES
    );
  } catch (_err) {
    return false;
  }
  const expected = Buffer.from(keyHex, 'hex');
  if (derived.length !== expected.length) {
    return false;
  }
  return crypto.timingSafeEqual(derived, expected);
}

/**
 * Parses and validates the `CUBEJS_SQL_USERS` JSON map.
 * Rejects plaintext passwords and unknown roles at startup.
 *
 * @param {string|undefined} rawJson
 * @returns {Record<string, { password: string, role: string }>}
 */
function parseSqlUsers(rawJson) {
  if (!rawJson) {
    return {};
  }
  let parsed;
  try {
    parsed = JSON.parse(rawJson);
  } catch (err) {
    throw new Error(`[ConfigError] CUBEJS_SQL_USERS is not valid JSON: ${err.message}`);
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('[ConfigError] CUBEJS_SQL_USERS must be a JSON object.');
  }

  const store = {};
  for (const [rawUser, entry] of Object.entries(parsed)) {
    const username = String(rawUser).trim().toLowerCase();
    if (!username) {
      throw new Error('[ConfigError] CUBEJS_SQL_USERS contains an empty username.');
    }
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
      throw new Error(`[ConfigError] CUBEJS_SQL_USERS['${username}'] must be an object.`);
    }
    if (!ROLE_PERMISSIONS[entry.role]) {
      throw new Error(
        `[ConfigError] CUBEJS_SQL_USERS['${username}'] references unknown role '${entry.role}'.`
      );
    }
    if (typeof entry.password !== 'string' || !SCRYPT_DIGEST_PATTERN.test(entry.password)) {
      throw new Error(
        `[ConfigError] CUBEJS_SQL_USERS['${username}'].password must be a valid scrypt digest.`
      );
    }
    store[username] = {
      password: entry.password,
      role: entry.role
    };
  }
  return store;
}

/**
 * Cube.js `checkSqlAuth` hook for the PostgreSQL wire-protocol SQL API (port 5432).
 *
 * @param {object} _req
 * @param {string|{u?: string, user?: string, password?: string}} authInfo
 * @param {Record<string, { password: string, role: string }>} [userStoreOverride]
 */
async function checkSqlAuth(_req, authInfo, userStoreOverride) {
  const store = userStoreOverride || parseSqlUsers(process.env.CUBEJS_SQL_USERS);
  const rawUser =
    typeof authInfo === 'string'
      ? authInfo
      : authInfo?.u || authInfo?.user || authInfo?.username || '';
  const suppliedPassword = typeof authInfo === 'object' ? authInfo?.password : '';
  const username = String(rawUser).trim().toLowerCase();

  if (!username) {
    throw new ForbiddenSecurityError(
      '[AuthDenied] SQL API requires an explicit username.',
      403
    );
  }

  const entry = store[username];
  const digestToVerify = entry ? entry.password : ABSENT_USER_DIGEST;
  const accepted = verifySqlPassword(suppliedPassword, digestToVerify);

  if (!entry || !accepted) {
    throw new ForbiddenSecurityError(
      `[AuthDenied] SQL API login rejected for '${username}'.`,
      403
    );
  }

  const role = entry.role;
  return {
    password: suppliedPassword,
    securityContext: {
      sub: username,
      user: username,
      role,
      canViewPii: ROLE_PERMISSIONS[role].canViewPii === true
    }
  };
}

/**
 * Multi-tenant cache partitioning key generator (`contextToAppId`).
 */
function contextToAppId({ securityContext } = {}) {
  const role = securityContext?.role || 'ROLE_FINANCE_MEMBER';
  const piiTag = securityContext?.canViewPii ? 'PII_TRUE' : 'PII_FALSE';
  return `CUBE_V2_${role}_${piiTag}`;
}

module.exports = {
  ROLE_PERMISSIONS,
  SHARED_DIMENSIONS,
  PII_DIMENSIONS,
  DEFAULT_POPIA_SALT,
  ForbiddenSecurityError,
  assertValidApiSecret,
  signHs256Jwt,
  verifyHs256Jwt,
  extractSecurityContextFromClaims,
  checkAuth,
  resolveUserRoleFromRoster,
  compilePiiDimensionSql,
  hashPiiValue,
  maskRowPiiFields,
  queryRewrite,
  scryptDigest,
  verifySqlPassword,
  parseSqlUsers,
  checkSqlAuth,
  contextToAppId
};
