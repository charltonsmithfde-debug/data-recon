/**
 * version-two/cube/model/MemberAnalysis.js
 * Ticket: V2-2.3 — Semantic Domain Cube Models & Multi-Table Join Graphs
 *
 * Cube 1.7.x semantic model for Member Demographics & AUA over
 * `lake.scbi_cdp_mart.cnf__fact_member_investment_aua` joined with
 * `dim_member`, `dim_scheme`, and `dim_date`.
 */

'use strict';

const { compilePiiDimensionSql } = require('../security');

function defineMemberAnalysis(cubeFn) {
  cubeFn('MemberAnalysis', {
    sql_table: 'lake.scbi_cdp_mart.cnf__fact_member_investment_aua',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__fact_member_investment_aua`,

    joins: {
      dim_date: {
        sql: `${CUBE}.date_sk = ${dim_date}.date_sk`,
        relationship: 'many_to_one'
      },
      DimDate: {
        sql: `${CUBE}.date_sk = ${DimDate}.date_sk`,
        relationship: 'many_to_one'
      },
      dim_member: {
        sql: `${CUBE}.member_hk = ${dim_member}.member_hk`,
        relationship: 'many_to_one'
      },
      DimMember: {
        sql: `${CUBE}.member_hk = ${DimMember}.member_hk`,
        relationship: 'many_to_one'
      },
      dim_scheme: {
        sql: `${CUBE}.fund_hk = ${dim_scheme}.scheme_hk`,
        relationship: 'many_to_one'
      },
      DimScheme: {
        sql: `${CUBE}.fund_hk = ${DimScheme}.scheme_hk`,
        relationship: 'many_to_one'
      },
      DimFund: {
        sql: `${CUBE}.fund_hk = ${DimFund}.fund_hk`,
        relationship: 'many_to_one'
      },
      DimClient: {
        sql: `${CUBE}.client_hk = ${DimClient}.client_hk`,
        relationship: 'many_to_one'
      },
      DimEmployer: {
        sql: `${CUBE}.employer_hk = ${DimEmployer}.employer_hk`,
        relationship: 'many_to_one'
      }
    },

    measures: {
      activeMemberCount: {
        sql: 'member_hk',
        type: 'count_distinct',
        title: 'Active Member Count'
      },
      totalAua: {
        sql: 'aua_amount',
        type: 'sum',
        format: 'currency',
        title: 'Total AUA'
      },
      avgAua: {
        sql: 'aua_amount',
        type: 'avg',
        format: 'currency',
        title: 'Average Member AUA'
      },
      averageCommissionRate: {
        sql: 'commission_rate',
        type: 'avg',
        format: 'percent',
        title: 'Average Commission Rate'
      }
    },

    dimensions: {
      dateSk: {
        sql: 'date_sk',
        type: 'number',
        primary_key: true,
        shown: true
      },
      member_id: {
        sql: (SECURITY_CONTEXT) => compilePiiDimensionSql('member_id', SECURITY_CONTEXT),
        type: 'string'
      },
      id_number: {
        sql: (SECURITY_CONTEXT) => compilePiiDimensionSql('id_number', SECURITY_CONTEXT),
        type: 'string'
      },
      client_name: {
        sql: (SECURITY_CONTEXT) => compilePiiDimensionSql('client_name', SECURITY_CONTEXT),
        type: 'string'
      },
      member_age: {
        sql: 'member_age',
        type: 'number',
        title: 'Member Age'
      },
      memberAge: {
        sql: 'member_age',
        type: 'number',
        title: 'Member Age'
      },
      memberAgeBand: {
        sql: 'member_age_band',
        type: 'string'
      },
      memberGender: {
        sql: 'member_gender',
        type: 'string'
      },
      clientHk: {
        sql: 'client_hk',
        type: 'string'
      },
      fundHk: {
        sql: 'fund_hk',
        type: 'string'
      },
      employerHk: {
        sql: 'employer_hk',
        type: 'string'
      },
      memberHk: {
        sql: 'member_hk',
        type: 'string'
      }
    },

    pre_aggregations: {
      memberDemographicsSummary: {
        measures: ['activeMemberCount', 'totalAua', 'avgAua', 'averageCommissionRate'],
        dimensions: ['member_age', 'memberAgeBand', 'memberGender']
      }
    }
  });
}

if (typeof global.cube === 'function') {
  defineMemberAnalysis(global.cube);
}

module.exports = { defineMemberAnalysis };
