# NEXUS ERP — Maintained list of Pakistani banks + mobile wallet providers
# for vendor payout accounts (see vendor_payment_accounts.py,
# VENDOR_PAYOUT_ACCOUNTS.md). Exposed publicly via /api/public/vendors/banks
# and /api/public/vendors/wallet-providers for the registration wizard's
# selects, and used server-side to reject unknown bank_name values.
#
# PK_BANKS values are each bank's SBP-assigned 4-letter IBAN institution
# code (the characters right after the "PKkk" country/check-digit prefix
# in a Pakistani IBAN) — used only as an informational cross-check against
# the IBAN the vendor enters (warn, never block, since this mapping isn't
# exhaustive and a vendor may bank with an institution not listed here).

PK_BANKS: dict[str, str] = {
    "Allied Bank Limited": "ABPA",
    "Askari Bank": "ASCM",
    "Bank Al Habib": "BAHL",
    "Bank Alfalah": "ALFH",
    "BankIslami Pakistan": "BKIP",
    "Dubai Islamic Bank Pakistan": "DUBB",
    "Faysal Bank": "FAYS",
    "Habib Bank Limited": "HABB",
    "Habib Metropolitan Bank": "MPBL",
    "JS Bank": "JSBL",
    "MCB Bank": "MUCB",
    "Meezan Bank": "MEZN",
    "National Bank of Pakistan": "NBPA",
    "Soneri Bank": "SONE",
    "Standard Chartered Bank Pakistan": "SCBL",
    "Summit Bank": "SUMB",
    "United Bank Limited": "UNIL",
}

WALLET_PROVIDERS: dict[str, str] = {
    "jazzcash": "JazzCash",
    "easypaisa": "Easypaisa",
    "nayapay": "NayaPay",
    "sadapay": "SadaPay",
}
