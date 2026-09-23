// data-recon/cube/model/cubes/AnnuityQuotation.js
// Semantic cube definition for Life Annuity Reporting: Quotes & Acceptances
// Aligned with pbi-scbi/semantic_models/use-case/AnnuityQuotation/AnnuityQuotations

cube('AnnuityQuotation', {
  sql: `SELECT * FROM scbi_cdp_mart.cnf__fact_annuity_quotations 
        WHERE derived_quotation_status <> 'Accepted' 
          AND NOT (derived_quotation_type = 'Bulk' AND LOWER(source) = 'online')`,

  joins: {
    DimDate: {
      sql: `${CUBE}.date_sk = ${DimDate}.date_sk`,
      relationship: 'belongsTo'
    },
    DimBrokerConsultant: {
      sql: `${CUBE}.quoted_broker_consultant_hk = ${DimBrokerConsultant}.broker_consultant_hk`,
      relationship: 'belongsTo'
    },
    DimFund: {
      sql: `${CUBE}.fund_hk = ${DimFund}.fund_hk`,
      relationship: 'belongsTo'
    },
    DimAnnuityProduct: {
      sql: `${CUBE}.annuity_product_hk = ${DimAnnuityProduct}.product_hk`,
      relationship: 'belongsTo'
    },
    DimMember: {
      sql: `${CUBE}.member_hk = ${DimMember}.member_hk`,
      relationship: 'belongsTo'
    }
  },

  measures: {
    quotedMembers: {
      sql: 'quoted_member_id_number',
      type: 'countDistinct',
      title: 'Quoted Members'
    },
    acceptedMembers: {
      sql: 'CASE WHEN LOWER(derived_quotation_status) = \'quoted and accepted\' THEN quoted_member_id_number END',
      type: 'countDistinct',
      title: 'Accepted Members'
    },
    quotationCount: {
      sql: 'quotation_number',
      type: 'countDistinct',
      title: 'Quotation Count'
    },
    acceptedQuotations: {
      sql: 'CASE WHEN LOWER(derived_quotation_status) = \'quoted and accepted\' THEN quotation_number END',
      type: 'countDistinct',
      title: 'Accepted Quotations'
    },
    quotedPurchasePrice: {
      sql: 'quotation_purchase_price',
      type: 'sum',
      format: 'currency',
      title: 'Quote Purchase Price'
    },
    lastQuotationPrice: {
      sql: 'CASE WHEN quotation_number = latest_quotation_number AND quotation_number <> \'n/a\' THEN quotation_purchase_price ELSE 0 END',
      type: 'sum',
      format: 'currency',
      title: 'Last Quotation Price'
    },
    acceptedPurchasePrice: {
      sql: 'CASE WHEN LOWER(derived_quotation_status) = \'quoted and accepted\' THEN quotation_purchase_price ELSE 0 END',
      type: 'sum',
      format: 'currency',
      title: 'Accepted Purchase Price'
    },
    memberConversionRate: {
      sql: 'CASE WHEN ${quotedMembers} > 0 THEN (${acceptedMembers} * 100.0) / ${quotedMembers} ELSE 0 END',
      type: 'number',
      format: 'percent',
      title: 'Member Conversion Rate'
    },
    purchasePriceConversionRate: {
      sql: 'CASE WHEN ${lastQuotationPrice} > 0 THEN (${acceptedPurchasePrice} * 100.0) / ${lastQuotationPrice} ELSE 0 END',
      type: 'number',
      format: 'percent',
      title: 'Purchase Price Conversion Rate'
    }
  },

  dimensions: {
    quotationNumber: {
      sql: 'quotation_number',
      type: 'string',
      primaryKey: true,
      shown: true
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
  }
});
