#!/usr/bin/env node
/**
 * mint_sql_users.js -- provision the Cube SQL API credential store (US-8.3).
 *
 * Emits one CUBEJS_SQL_USERS value holding one entry per BI connection, plus the plaintext
 * passwords once, so they can be pasted into Metabase and Power BI and then forgotten. Passwords
 * are generated here; they are never an argument, so they never reach the shell history or the
 * process table of a shared machine.
 *
 *   node cube/mint_sql_users.js                       # the default per-role connection set
 *   node cube/mint_sql_users.js member investments    # a subset, by short name
 *
 * The store is a scrypt digest per user (Node scryptSync defaults: N=16384, r=8, p=1, 32-byte
 * key). cube.js refuses to start on a plaintext password in the store, because CUBEJS_SQL_USERS
 * is readable by anyone who can describe the service.
 *
 * Least privilege is the whole point of minting several. Cube derives the security context at
 * login, so a connection *is* a role: one Metabase database entry per role domain, each seeing
 * only its own cubes. ROLE_EXECUTIVE_ALL is deliberately absent -- it is the only role with PII
 * in the clear, so a shared executive connection would unmask member_nk on every dashboard that
 * joins DimMember. If an executive connection is genuinely wanted it is a POPIA decision, made
 * once, in writing, and minted by hand.
 *
 * Re-running this mints *new* passwords. Rotation is the intended use; it takes the existing
 * connections down until Metabase and Power BI are updated, so do it deliberately.
 */

'use strict';

const crypto = require('crypto');

// Short name -> the connection as it is provisioned. The username is what an operator sees in
// Metabase's connection list and in Cube's logs, so it names the domain, not a person.
const CONNECTIONS = {
  member: {
    username: 'metabase.member@sanlam.co.za',
    role: 'ROLE_FINANCE_MEMBER',
    serves: 'Member & finance dashboards -- MemberMonthly, MemberMonthlyInvestment, DimMember'
  },
  investments: {
    username: 'metabase.investments@sanlam.co.za',
    role: 'ROLE_INVESTMENTS',
    serves: 'Investment dashboards -- InvestmentsFundamental, MemberMonthlyInvestment'
  },
  quotations: {
    username: 'metabase.quotations@sanlam.co.za',
    role: 'ROLE_ANNUITY',
    serves: 'Annuity quotation dashboards -- AnnuityQuotation'
  },
  powerbi_member: {
    username: 'powerbi.member@sanlam.co.za',
    role: 'ROLE_FINANCE_MEMBER',
    serves: 'Power BI Desktop, member & finance datasets'
  },
  powerbi_investments: {
    username: 'powerbi.investments@sanlam.co.za',
    role: 'ROLE_INVESTMENTS',
    serves: 'Power BI Desktop, investment datasets'
  }
};

const SCRYPT_SALT_BYTES = 8;
const SCRYPT_KEY_BYTES = 32;

function scryptDigest(password) {
  const salt = crypto.randomBytes(SCRYPT_SALT_BYTES);
  const key = crypto.scryptSync(password, salt, SCRYPT_KEY_BYTES);
  return `scrypt:${salt.toString('hex')}:${key.toString('hex')}`;
}

function generatePassword() {
  // 32 bytes of entropy, base64url. Postgres drivers vary in how they escape a password inside a
  // connection string, so the alphabet is deliberately free of ':', '/', '@' and whitespace.
  return crypto.randomBytes(32).toString('base64url');
}

function main(argv) {
  const requested = argv.length > 0 ? argv : Object.keys(CONNECTIONS);

  const unknown = requested.filter((name) => !CONNECTIONS[name]);
  if (unknown.length > 0) {
    console.error(`Unknown connection(s): ${unknown.join(', ')}`);
    console.error(`Known: ${Object.keys(CONNECTIONS).join(', ')}`);
    process.exit(2);
  }

  const store = {};
  const plaintext = [];

  for (const name of requested) {
    const connection = CONNECTIONS[name];
    const password = generatePassword();
    store[connection.username] = {
      password: scryptDigest(password),
      role: connection.role
    };
    plaintext.push({ name, ...connection, password });
  }

  console.log('# ── Paste these into the BI tool once, then discard this output ───────────────');
  for (const entry of plaintext) {
    console.log(`#   ${entry.name}`);
    console.log(`#     user:     ${entry.username}`);
    console.log(`#     password: ${entry.password}`);
    console.log(`#     role:     ${entry.role}`);
    console.log(`#     serves:   ${entry.serves}`);
  }
  console.log('#');
  console.log('# ── The credential store. Only the digests. Supply it to the SQL runtime: ────');
  console.log('#   export CUBEJS_SQL_USERS=\'<the line below>\'');
  console.log('#   ./cube/deploy_cube_sql_vm.sh');
  console.log(JSON.stringify(store));
}

main(process.argv.slice(2));
