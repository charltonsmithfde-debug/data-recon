/**
 * version-two/cube/model/SharedDimensions.js
 * Ticket: V2-2.3 — Semantic Domain Cube Models & Multi-Table Join Graphs
 *
 * Defines Cube 1.7.x shared dimension cubes backed by the DuckLake `lake` catalog:
 *  - SharedDimensions (conforming view over dim_scheme, dim_date, dim_member)
 *  - DimDate (lake.scbi_sdp_mart.dim_date)
 *  - DimScheme / DimFund (lake.scbi_cdp_mart.cnf__dim_fund)
 *  - DimMember (lake.scbi_cdp_mart.cnf__dim_member) — binds `member_age` & POPIA masking
 *  - DimClient (lake.scbi_cdp_mart.cnf__dim_client)
 *  - DimEmployer (lake.scbi_cdp_mart.cnf__dim_employer)
 *  - DimPaypoint (lake.scbi_cdp_mart.cnf__dim_paypoint)
 *  - DimBrokerConsultant (lake.scbi_cdp_mart.cnf__dim_broker_consultant)
 *  - DimAnnuityProduct (lake.scbi_cdp_mart.cnf__dim_annuity_product)
 *  - DimInvestmentProduct (lake.scbi_cdp_mart.cnf__dim_investment_product)
 */

'use strict';

const { compilePiiDimensionSql } = require('../security');

function defineSharedDimensions(cubeFn) {
  cubeFn('SharedDimensions', {
    sql_table: 'lake.scbi_cdp_mart.cnf__dim_fund',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__dim_fund`,
    joins: {
      dim_date: {
        sql: `${CUBE}.effective_date_sk = ${dim_date}.date_sk`,
        relationship: 'many_to_one'
      }
    },
    measures: {
      schemeCount: {
        sql: 'fund_hk',
        type: 'count_distinct',
        title: 'Total Schemes'
      }
    },
    dimensions: {
      fundHk: {
        sql: 'fund_hk',
        type: 'string',
        primary_key: true
      },
      schemeName: {
        sql: 'fund_name',
        type: 'string'
      },
      schemeType: {
        sql: 'fund_classification',
        type: 'string'
      },
      schemeStatus: {
        sql: 'fund_status',
        type: 'string'
      }
    }
  });

  cubeFn('DimDate', {
    sql_table: 'lake.scbi_sdp_mart.dim_date',
    sql: `SELECT * FROM lake.scbi_sdp_mart.dim_date`,
    dimensions: {
      dateSk: {
        sql: 'date_sk',
        type: 'number',
        primary_key: true,
        shown: true
      },
      dateNk: {
        sql: 'date_nk',
        type: 'time'
      },
      calendarYear: {
        sql: 'calendar_year',
        type: 'number',
        shown: true
      },
      calendarMonthSk: {
        sql: 'calendar_month_sk',
        type: 'number',
        shown: true
      },
      formattedDate: {
        sql: `UPPER(STRFTIME(date_nk, '%d-%b-%Y'))`,
        type: 'string'
      }
    }
  });

  cubeFn('DimScheme', {
    sql_table: 'lake.scbi_cdp_mart.cnf__dim_fund',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__dim_fund`,
    dimensions: {
      schemeHk: {
        sql: 'fund_hk',
        type: 'string',
        primary_key: true
      },
      schemeName: {
        sql: 'fund_name',
        type: 'string'
      },
      schemeType: {
        sql: 'fund_classification',
        type: 'string'
      },
      schemeStatus: {
        sql: 'fund_status',
        type: 'string'
      }
    }
  });

  cubeFn('DimMember', {
    sql_table: 'lake.scbi_cdp_mart.cnf__dim_member',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__dim_member`,
    dimensions: {
      memberHk: {
        sql: 'member_hk',
        type: 'string',
        primary_key: true
      },
      member_id: {
        sql: (SECURITY_CONTEXT) => compilePiiDimensionSql('member_id', SECURITY_CONTEXT),
        type: 'string'
      },
      id_number: {
        sql: (SECURITY_CONTEXT) => compilePiiDimensionSql('id_number', SECURITY_CONTEXT),
        type: 'string'
      },
      memberNk: {
        sql: (SECURITY_CONTEXT) => compilePiiDimensionSql('member_nk', SECURITY_CONTEXT),
        type: 'string'
      },
      memberGender: {
        sql: 'member_gender',
        type: 'string'
      },
      memberMaritalStatus: {
        sql: 'member_marital_status',
        type: 'string'
      },
      memberAgeBand: {
        sql: 'member_age_band',
        type: 'string'
      },
      memberAge: {
        sql: 'member_age',
        type: 'number'
      },
      member_age: {
        sql: 'member_age',
        type: 'number'
      }
    }
  });

  cubeFn('dim_date', {
    sql_table: 'lake.scbi_sdp_mart.dim_date',
    sql: `SELECT * FROM lake.scbi_sdp_mart.dim_date`,
    dimensions: {
      date_sk: { sql: 'date_sk', type: 'number', primary_key: true },
      calendar_year: { sql: 'calendar_year', type: 'number' }
    }
  });

  cubeFn('dim_scheme', {
    sql_table: 'lake.scbi_cdp_mart.cnf__dim_fund',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__dim_fund`,
    dimensions: {
      scheme_hk: { sql: 'fund_hk', type: 'string', primary_key: true },
      scheme_name: { sql: 'fund_name', type: 'string' },
      scheme_type: { sql: 'fund_classification', type: 'string' }
    }
  });

  cubeFn('dim_member', {
    sql_table: 'lake.scbi_cdp_mart.cnf__dim_member',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__dim_member`,
    dimensions: {
      member_hk: { sql: 'member_hk', type: 'string', primary_key: true },
      member_id: {
        sql: (SECURITY_CONTEXT) => compilePiiDimensionSql('member_id', SECURITY_CONTEXT),
        type: 'string'
      },
      id_number: {
        sql: (SECURITY_CONTEXT) => compilePiiDimensionSql('id_number', SECURITY_CONTEXT),
        type: 'string'
      },
      member_age: { sql: 'member_age', type: 'number' },
      member_age_band: { sql: 'member_age_band', type: 'string' }
    }
  });

  cubeFn('DimClient', {
    sql_table: 'lake.scbi_cdp_mart.cnf__dim_client',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__dim_client`,
    dimensions: {
      clientHk: {
        sql: 'client_hk',
        type: 'string',
        primary_key: true
      },
      client_name: {
        sql: (SECURITY_CONTEXT) => compilePiiDimensionSql('client_name', SECURITY_CONTEXT),
        type: 'string'
      },
      clientName: {
        sql: (SECURITY_CONTEXT) => compilePiiDimensionSql('client_name', SECURITY_CONTEXT),
        type: 'string'
      }
    }
  });

  cubeFn('DimFund', {
    sql_table: 'lake.scbi_cdp_mart.cnf__dim_fund',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__dim_fund`,
    dimensions: {
      fundHk: {
        sql: 'fund_hk',
        type: 'string',
        primary_key: true
      },
      fundName: {
        sql: 'fund_name',
        type: 'string'
      },
      fundClassification: {
        sql: 'fund_classification',
        type: 'string'
      },
      fundStatus: {
        sql: 'fund_status',
        type: 'string'
      }
    }
  });

  cubeFn('DimEmployer', {
    sql_table: 'lake.scbi_cdp_mart.cnf__dim_employer',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__dim_employer`,
    dimensions: {
      employerHk: {
        sql: 'employer_hk',
        type: 'string',
        primary_key: true
      },
      employerName: {
        sql: 'employer_name',
        type: 'string'
      }
    }
  });

  cubeFn('DimPaypoint', {
    sql_table: 'lake.scbi_cdp_mart.cnf__dim_paypoint',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__dim_paypoint`,
    dimensions: {
      paypointHk: {
        sql: 'paypoint_hk',
        type: 'string',
        primary_key: true
      },
      paypointName: {
        sql: 'paypoint_name',
        type: 'string'
      },
      paypointClassification: {
        sql: 'paypoint_classification',
        type: 'string'
      },
      paypointBusinessUnit: {
        sql: 'paypoint_business_unit',
        type: 'string'
      }
    }
  });

  cubeFn('DimBrokerConsultant', {
    sql_table: 'lake.scbi_cdp_mart.cnf__dim_broker_consultant',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__dim_broker_consultant`,
    dimensions: {
      brokerConsultantHk: {
        sql: 'broker_consultant_hk',
        type: 'string',
        primary_key: true
      },
      brokerConsultantName: {
        sql: 'broker_consultant_name',
        type: 'string'
      },
      brokerConsultantBrokerage: {
        sql: 'broker_consultant_brokerage',
        type: 'string'
      },
      brokerConsultantBusiness: {
        sql: 'broker_consultant_business',
        type: 'string'
      },
      brokerConsultantTeam: {
        sql: 'broker_consultant_team',
        type: 'string'
      }
    }
  });

  cubeFn('DimAnnuityProduct', {
    sql_table: 'lake.scbi_cdp_mart.cnf__dim_annuity_product',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__dim_annuity_product`,
    dimensions: {
      productHk: {
        sql: 'product_hk',
        type: 'string',
        primary_key: true
      },
      productDescription: {
        sql: 'product_description',
        type: 'string'
      },
      productGroup: {
        sql: 'product_group',
        type: 'string'
      }
    }
  });

  cubeFn('DimInvestmentProduct', {
    sql_table: 'lake.scbi_cdp_mart.cnf__dim_investment_product',
    sql: `SELECT * FROM lake.scbi_cdp_mart.cnf__dim_investment_product`,
    dimensions: {
      investmentProductHk: {
        sql: 'investment_product_hk',
        type: 'string',
        primary_key: true
      },
      investmentProductName: {
        sql: 'investment_portfolio_name',
        type: 'string'
      },
      investmentMemberChoice: {
        sql: 'investment_member_choice',
        type: 'string'
      },
      investmentProductRiskMeter: {
        sql: 'investment_product_risk_meter',
        type: 'string'
      }
    }
  });
}

if (typeof global.cube === 'function') {
  defineSharedDimensions(global.cube);
}

module.exports = { defineSharedDimensions };
