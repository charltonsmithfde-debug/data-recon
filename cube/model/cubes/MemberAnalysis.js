// data-recon/cube/model/cubes/MemberAnalysis.js

cube('MemberMonthly', {
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
    avgAua: {
      sql: 'aua_amount',
      type: 'avg',
      format: 'currency'
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
      primaryKey: true,
      shown: true
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
  }
});
