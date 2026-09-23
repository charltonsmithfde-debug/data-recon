// data-recon/cube/model/cubes/InvestmentAnalysis.js

cube('InvestmentsFundamental', {
  sql: `SELECT * FROM scbi_cdp_mart.cnf__fact_inv_monthly_market_value`,

  joins: {
    DimDate: {
      sql: `${CUBE}.date_sk = ${DimDate}.date_sk`,
      relationship: 'belongsTo'
    },
    DimFund: {
      sql: `${CUBE}.fund_hk = ${DimFund}.fund_hk`,
      relationship: 'belongsTo'
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
      primaryKey: true,
      shown: true
    }
  }
});

cube('MemberMonthlyInvestment', {
  sql: `SELECT * FROM scbi_cdp_mart.cnf__fact_member_investment_aua`,

  joins: {
    DimDate: {
      sql: `${CUBE}.date_sk = ${DimDate}.date_sk`,
      relationship: 'belongsTo'
    },
    DimClient: {
      sql: `${CUBE}.client_hk = ${DimClient}.client_hk`,
      relationship: 'belongsTo'
    },
    DimFund: {
      sql: `${CUBE}.fund_hk = ${DimFund}.fund_hk`,
      relationship: 'belongsTo'
    },
    DimEmployer: {
      sql: `${CUBE}.employer_hk = ${DimEmployer}.employer_hk`,
      relationship: 'belongsTo'
    },
    DimMember: {
      sql: `${CUBE}.member_hk = ${DimMember}.member_hk`,
      relationship: 'belongsTo'
    }
  },

  measures: {
    totalAua: {
      sql: 'aua_amount',
      type: 'sum',
      format: 'currency'
    },
    distinctClients: {
      sql: 'client_hk',
      type: 'countDistinct'
    },
    distinctPortfolios: {
      sql: 'investment_product_hk',
      type: 'countDistinct'
    },
    distinctMembers: {
      sql: 'member_hk',
      type: 'countDistinct'
    }
  },

  dimensions: {
    dateSk: {
      sql: 'date_sk',
      type: 'number',
      primaryKey: true
    },
    portfolioName: {
      sql: 'investment_product_name',
      type: 'string'
    },
    riskMeter: {
      sql: 'investment_product_risk_meter',
      type: 'string'
    },
    ageBand: {
      sql: 'member_age_band',
      type: 'string'
    },
    pensionableServiceBand: {
      sql: 'pensionable_service_years_band',
      type: 'string'
    }
  }
});
