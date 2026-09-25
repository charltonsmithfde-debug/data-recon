/**
 * version-two/cube/model/InvestmentAnalysis.js
 * Ticket: V2-2.3 — Semantic Domain Cube Models & Multi-Table Join Graphs
 *
 * Cube 1.7.x semantic models for Investment AUA & Monthly Market Values over:
 *  - `lake.scbi_cdp_mart.cnf__fact_member_investment_aua`
 *  - `lake.scbi_cdp_mart.cnf__fact_inv_monthly_market_value`
 */

'use strict';

const { compilePiiDimensionSql } = require('../security');

function defineInvestmentAnalysis(cubeFn) {
  cubeFn('InvestmentAnalysis', {
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
      },
      DimInvestmentProduct: {
        sql: `${CUBE}.investment_product_hk = ${DimInvestmentProduct}.investment_product_hk`,
        relationship: 'many_to_one'
      }
    },

    measures: {
      totalAua: {
        sql: 'aua_amount',
        type: 'sum',
        format: 'currency',
        title: 'Total AUA'
      },
      activeMemberCount: {
        sql: 'member_hk',
        type: 'count_distinct',
        title: 'Active Member Count'
      },
      averageCommissionRate: {
        sql: 'commission_rate',
        type: 'avg',
        format: 'percent',
        title: 'Average Commission Rate'
      },
      distinctClients: {
        sql: 'client_hk',
        type: 'count_distinct',
        title: 'Distinct Clients'
      },
      distinctPortfolios: {
        sql: 'investment_product_hk',
        type: 'count_distinct',
        title: 'Distinct Portfolios'
      }
    },

    dimensions: {
      dateSk: {
        sql: 'date_sk',
        type: 'number',
        primary_key: true,
        shown: true
      },
      client_name: {
        sql: (SECURITY_CONTEXT) => compilePiiDimensionSql('client_name', SECURITY_CONTEXT),
        type: 'string'
      },
      member_id: {
        sql: (SECURITY_CONTEXT) => compilePiiDimensionSql('member_hk', SECURITY_CONTEXT),
        type: 'string'
      },
      portfolioName: {
        sql: 'investment_product_name',
        type: 'string'
      },
      riskMeter: {
        sql: 'investment_product_risk_meter',
        type: 'string'
      },
      member_age: {
        sql: 'member_age',
        type: 'number'
      },
      ageBand: {
        sql: 'member_age_band',
        type: 'string'
      },
      pensionableServiceBand: {
        sql: 'pensionable_service_years_band',
        type: 'string'
      }
    },

    pre_aggregations: {
      monthlyAuaByScheme: {
        measures: ['totalAua', 'activeMemberCount', 'averageCommissionRate'],
        dimensions: ['portfolioName', 'riskMeter', 'ageBand']
      }
    }
  });

  cubeFn('InvestmentsFundamental', {
    sql_table: 'lake.scbi_cdp_mart.cnf__fact_inv_monthly_market_value',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__fact_inv_monthly_market_value`,
    joins: {
      DimDate: {
        sql: `${CUBE}.date_sk = ${DimDate}.date_sk`,
        relationship: 'many_to_one'
      },
      DimFund: {
        sql: `${CUBE}.fund_hk = ${DimFund}.fund_hk`,
        relationship: 'many_to_one'
      }
    },
    measures: {
      totalMarketValue: {
        sql: 'market_value',
        type: 'sum',
        format: 'currency'
      },
      totalTransactionUnits: {
        sql: 'transaction_units',
        type: 'sum'
      }
    },
    dimensions: {
      dateSk: {
        sql: 'date_sk',
        type: 'number',
        primary_key: true,
        shown: true
      }
    }
  });
}

if (typeof global.cube === 'function') {
  defineInvestmentAnalysis(global.cube);
}

module.exports = { defineInvestmentAnalysis };
