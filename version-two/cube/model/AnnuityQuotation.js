/**
 * version-two/cube/model/AnnuityQuotation.js
 * Ticket: V2-2.3 — Semantic Domain Cube Models & Multi-Table Join Graphs
 *
 * Cube 1.7.x semantic model for Life Annuity Quotations & Acceptances over
 * `lake.scbi_cdp_mart.cnf__fact_annuity_quotations`.
 */

'use strict';

const { compilePiiDimensionSql } = require('../security');

function defineAnnuityQuotation(cubeFn) {
  cubeFn('AnnuityQuotation', {
    sql_table: 'lake.scbi_cdp_mart.cnf__fact_annuity_quotations',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__fact_annuity_quotations
          WHERE derived_quotation_status <> 'Accepted'
            AND NOT (derived_quotation_type = 'Bulk' AND LOWER(source) = 'online')`,

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
      DimBrokerConsultant: {
        sql: `${CUBE}.quoted_broker_consultant_hk = ${DimBrokerConsultant}.broker_consultant_hk`,
        relationship: 'many_to_one'
      },
      DimAnnuityProduct: {
        sql: `${CUBE}.annuity_product_hk = ${DimAnnuityProduct}.product_hk`,
        relationship: 'many_to_one'
      }
    },

    measures: {
      quotationCount: {
        sql: 'quotation_number',
        type: 'count_distinct',
        title: 'Quotation Count'
      },
      acceptedQuotations: {
        sql: `CASE WHEN LOWER(derived_quotation_status) = 'quoted and accepted' THEN quotation_number END`,
        type: 'count_distinct',
        title: 'Accepted Quotations'
      },
      quotedMembers: {
        sql: 'quoted_member_id_number',
        type: 'count_distinct',
        title: 'Quoted Members'
      },
      acceptedMembers: {
        sql: `CASE WHEN LOWER(derived_quotation_status) = 'quoted and accepted' THEN quoted_member_id_number END`,
        type: 'count_distinct',
        title: 'Accepted Members'
      },
      quotedPurchasePrice: {
        sql: 'quotation_purchase_price',
        type: 'sum',
        format: 'currency',
        title: 'Quote Purchase Price'
      },
      lastQuotationPrice: {
        sql: `CASE WHEN quotation_number = latest_quotation_number AND quotation_number <> 'n/a' THEN quotation_purchase_price ELSE 0 END`,
        type: 'sum',
        format: 'currency',
        title: 'Last Quotation Price'
      },
      acceptedPurchasePrice: {
        sql: `CASE WHEN LOWER(derived_quotation_status) = 'quoted and accepted' THEN quotation_purchase_price ELSE 0 END`,
        type: 'sum',
        format: 'currency',
        title: 'Accepted Purchase Price'
      },
      averageCommissionRate: {
        sql: 'commission_rate',
        type: 'avg',
        format: 'percent',
        title: 'Average Commission Rate'
      },
      memberConversionRate: {
        sql: `CASE WHEN \${quotedMembers} > 0 THEN (\${acceptedMembers} * 100.0) / \${quotedMembers} ELSE 0 END`,
        type: 'number',
        format: 'percent',
        title: 'Member Conversion Rate'
      },
      purchasePriceConversionRate: {
        sql: `CASE WHEN \${lastQuotationPrice} > 0 THEN (\${acceptedPurchasePrice} * 100.0) / \${lastQuotationPrice} ELSE 0 END`,
        type: 'number',
        format: 'percent',
        title: 'Purchase Price Conversion Rate'
      }
    },

    dimensions: {
      quotationNumber: {
        sql: 'quotation_number',
        type: 'string',
        primary_key: true,
        shown: true
      },
      id_number: {
        sql: (SECURITY_CONTEXT) => compilePiiDimensionSql('quoted_member_id_number', SECURITY_CONTEXT),
        type: 'string'
      },
      member_id: {
        sql: (SECURITY_CONTEXT) => compilePiiDimensionSql('member_hk', SECURITY_CONTEXT),
        type: 'string'
      },
      derivedQuotationStatus: {
        sql: 'derived_quotation_status',
        type: 'string'
      },
      derivedQuotationType: {
        sql: 'derived_quotation_type',
        type: 'string'
      },
      derivedBusinessType: {
        sql: 'derived_business_type',
        type: 'string'
      },
      source: {
        sql: 'source',
        type: 'string'
      },
      dateNk: {
        sql: 'date_nk',
        type: 'time'
      },
      quotationCreatedDate: {
        sql: 'quotation_created_date',
        type: 'time'
      }
    },

    pre_aggregations: {
      monthlyQuotationRollup: {
        measures: ['quotationCount', 'acceptedQuotations', 'quotedPurchasePrice', 'averageCommissionRate'],
        dimensions: ['derivedQuotationStatus', 'derivedQuotationType'],
        time_dimension: 'quotationCreatedDate',
        granularity: 'month'
      }
    }
  });
}

if (typeof global.cube === 'function') {
  defineAnnuityQuotation(global.cube);
}

module.exports = { defineAnnuityQuotation };
