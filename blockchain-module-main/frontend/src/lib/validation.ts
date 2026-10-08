// src/lib/validation.ts
// Reusable field-level validators, used across every form in the app for
// the red-border + error-message-below pattern. No form library is
// installed (every form here is plain useState/controlled inputs), so
// this stays dependency-free and composes onto existing JSX rather than
// requiring a rewrite: each validator is `(value: string) => string | null`
// (an error message, or null if valid); `validate()` runs a list of them
// and returns the first error. Pair with `errorInputClass` for the border
// and `<FieldError>` (components/FieldError.tsx) for the message.

export type Validator = (value: string) => string | null;

export function validate(value: string, ...validators: Validator[]): string | null {
  for (const fn of validators) {
    const err = fn(value ?? "");
    if (err) return err;
  }
  return null;
}

// Runs a {field: value} map against a {field: Validator[]} map — returns
// a {field: error} map containing only fields that actually failed, so
// `Object.keys(errors).length === 0` means the whole form is valid.
export function validateAll<T extends Record<string, string>>(
  values: T,
  rules: Partial<Record<keyof T, Validator[]>>
): Partial<Record<keyof T, string>> {
  const errors: Partial<Record<keyof T, string>> = {};
  for (const key in rules) {
    const fns = rules[key];
    if (!fns) continue;
    const err = validate(values[key], ...fns);
    if (err) errors[key] = err;
  }
  return errors;
}

export const required = (msg = "This field is required"): Validator => (v) =>
  !v || !v.trim() ? msg : null;

export const isNumber = (msg = "Enter a valid number"): Validator => (v) =>
  v.trim() !== "" && Number.isNaN(Number(v)) ? msg : null;

export const isInteger = (msg = "Must be a whole number"): Validator => (v) =>
  v.trim() !== "" && !Number.isNaN(Number(v)) && !Number.isInteger(Number(v)) ? msg : null;

export const isPositive = (msg = "Must be greater than 0"): Validator => (v) =>
  v.trim() !== "" && !Number.isNaN(Number(v)) && Number(v) <= 0 ? msg : null;

export const isNonNegative = (msg = "Cannot be negative"): Validator => (v) =>
  v.trim() !== "" && !Number.isNaN(Number(v)) && Number(v) < 0 ? msg : null;

export const min = (n: number, msg?: string): Validator => (v) =>
  v.trim() !== "" && !Number.isNaN(Number(v)) && Number(v) < n ? (msg || `Must be at least ${n}`) : null;

export const max = (n: number, msg?: string): Validator => (v) =>
  v.trim() !== "" && !Number.isNaN(Number(v)) && Number(v) > n ? (msg || `Must be at most ${n}`) : null;

export const minLength = (n: number, msg?: string): Validator => (v) =>
  v.length > 0 && v.trim().length < n ? (msg || `Must be at least ${n} characters`) : null;

export const maxLength = (n: number, msg?: string): Validator => (v) =>
  v.length > n ? (msg || `Must be at most ${n} characters`) : null;

export const isEmail = (msg = "Enter a valid email address"): Validator => (v) =>
  v.trim() !== "" && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim()) ? msg : null;

// 03XXXXXXXXX or +92XXXXXXXXXX — same rule procurement.py/vendors.py already
// enforce server-side (see CLAUDE.md / VENDOR_ONBOARDING.md); kept in sync.
export const isPakistaniMobile = (msg = "Enter a valid Pakistani mobile number (e.g. 03XXXXXXXXX)"): Validator => (v) =>
  v.trim() !== "" && !/^(\+92|0)[0-9]{10}$/.test(v.replace(/[\s-]/g, "")) ? msg : null;

// Literal 24-char / PK-prefix rule, matching vendors.py's server-side check
// exactly (not a full mod-97 IBAN checksum — see VENDOR_ONBOARDING.md
// "Known limitations", same disclosed scope here).
export const isPakistaniIBAN = (msg = "Must be a 24-character Pakistani IBAN starting with PK"): Validator => (v) => {
  if (v.trim() === "") return null;
  const iban = v.trim().toUpperCase().replace(/\s/g, "");
  return iban.length !== 24 || !iban.startsWith("PK") ? msg : null;
};

// Letters, numbers, spaces, and common punctuation only — blocks control
// characters and stray symbols without being so strict it rejects real
// names/addresses (apostrophes, hyphens, periods, commas, slashes, &).
export const noSpecialChars = (msg = "Only letters, numbers, spaces and basic punctuation are allowed"): Validator => (v) =>
  v.trim() !== "" && !/^[a-zA-Z0-9\s.,'&/()-]*$/.test(v) ? msg : null;

// Full ISO 13616 / mod-97 IBAN checksum (unlike isPakistaniIBAN above, which
// is format-only) — used for the verified vendor payout account, where a
// mistyped IBAN would misdirect a real payout. Move the first 4 chars to
// the end, map letters to two-digit numbers (A=10..Z=35), the result mod 97
// must equal 1.
export const isPakistaniIBANChecksum = (msg = "This IBAN's check digits don't add up — double-check it was entered correctly"): Validator => (v) => {
  const iban = v.trim().toUpperCase().replace(/\s/g, "");
  if (iban === "") return null;
  if (iban.length !== 24 || !/^PK\d{2}[A-Z]{4}[A-Z0-9]{16}$/.test(iban)) {
    return "Must be a 24-character Pakistani IBAN (PK + 2 digits + 4-letter bank code + 16 alphanumeric)";
  }
  const rearranged = iban.slice(4) + iban.slice(0, 4);
  let digits = "";
  for (const ch of rearranged) {
    digits += /[0-9]/.test(ch) ? ch : String(ch.charCodeAt(0) - 55);
  }
  // mod 97 on a (potentially) huge digit string, done in chunks to stay
  // within safe-integer range — the standard incremental-remainder trick.
  let remainder = 0;
  for (const ch of digits) {
    remainder = (remainder * 10 + Number(ch)) % 97;
  }
  return remainder === 1 ? null : msg;
};

export const isAlphaOnly = (msg = "Only letters and spaces are allowed"): Validator => (v) =>
  v.trim() !== "" && !/^[a-zA-Z\s]*$/.test(v) ? msg : null;

// Shared Tailwind classes for an invalid field's border/ring — append to
// an input's existing className when it has an error.
export const errorInputClass = "border-destructive focus:ring-destructive/50";

// ── Order-quantity helpers (inline checks on every order form) ──────────
// Built from the validators above. The backend enforces the same rules
// (Pydantic Field(gt=0) / ge=0 in procurement.py and vendor_orders.py).

/** Quantity being ordered: required, a number, greater than zero. */
export function orderQuantityError(value: number | string): string | null {
  return validate(
    value === null || value === undefined ? "" : String(value),
    required("Quantity is required"),
    isNumber("Quantity must be a number"),
    isNonNegative("Quantity cannot be negative"),
    isPositive("Quantity must be greater than 0"),
  );
}

/** Quantity counted on delivery: zero is allowed (nothing usable arrived), negative is not. */
export function receivedQuantityError(value: number | string): string | null {
  return validate(
    value === null || value === undefined ? "" : String(value),
    required("Quantity is required"),
    isNumber("Quantity must be a number"),
    isNonNegative("Quantity cannot be negative"),
  );
}

/** Optional unit price: blank is allowed, negative is not. */
export function unitPriceError(value: number | string): string | null {
  return validate(
    value === null || value === undefined ? "" : String(value),
    isNumber("Unit price must be a number"),
    isNonNegative("Unit price cannot be negative"),
  );
}
