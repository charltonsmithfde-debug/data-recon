// data-recon/cube/model/cubes/SharedDimensions.js

cube('DimDate', {
  sql: `SELECT * FROM scbi_sdp_mart.dim_date`,
  dimensions: {
    dateSk: {
      sql: 'date_sk',
      type: 'number',
      primaryKey: true,
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

cube('DimMember', {
  sql: `SELECT * FROM scbi_cdp_mart.cnf__dim_member`,
  dimensions: {
    memberHk: {
      sql: 'member_hk',
      type: 'string',
      primaryKey: true
    },
    memberNk: {
      sql: (SECURITY_CONTEXT) => {
        if (SECURITY_CONTEXT && SECURITY_CONTEXT.canViewPii) {
          return 'member_nk';
        }
        return `'***-MASKED-' || SUBSTR(member_nk, LENGTH(member_nk) - 3, 4)`;
      },
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
    currentAge: {
      sql: 'current_age',
      type: 'number'
    }
  }
});

cube('DimClient', {
  sql: `SELECT * FROM scbi_cdp_mart.cnf__dim_client`,
  dimensions: {
    clientHk: {
      sql: 'client_hk',
      type: 'string',
      primaryKey: true
    },
    clientName: {
      sql: 'client_name',
      type: 'string'
    }
  }
});

cube('DimFund', {
  sql: `SELECT * FROM scbi_cdp_mart.cnf__dim_fund`,
  dimensions: {
    fundHk: {
      sql: 'fund_hk',
      type: 'string',
      primaryKey: true
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

cube('DimEmployer', {
  sql: `SELECT * FROM scbi_cdp_mart.cnf__dim_employer`,
  dimensions: {
    employerHk: {
      sql: 'employer_hk',
      type: 'string',
      primaryKey: true
    },
    employerName: {
      sql: 'employer_name',
      type: 'string'
    }
  }
});

cube('DimPaypoint', {
  sql: `SELECT * FROM scbi_cdp_mart.cnf__dim_paypoint`,
  dimensions: {
    paypointHk: {
      sql: 'paypoint_hk',
      type: 'string',
      primaryKey: true
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

cube('DimBrokerConsultant', {
  sql: `SELECT * FROM scbi_cdp_mart.cnf__dim_broker_consultant`,
  dimensions: {
    brokerConsultantHk: {
      sql: 'broker_consultant_hk',
      type: 'string',
      primaryKey: true
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

cube('DimAnnuityProduct', {
  sql: `SELECT * FROM scbi_cdp_mart.cnf__dim_annuity_product`,
  dimensions: {
    productHk: {
      sql: 'product_hk',
      type: 'string',
      primaryKey: true
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

cube('DimInvestmentProduct', {
  sql: `SELECT * FROM scbi_cdp_mart.cnf__dim_investment_product`,
  dimensions: {
    investmentProductHk: {
      sql: 'investment_product_hk',
      type: 'string',
      primaryKey: true
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

