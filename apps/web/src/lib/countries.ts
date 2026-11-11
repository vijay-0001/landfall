// Display names for ISO codes the API returns in `origin`, `destination` and `shop.country`.
const NAMES: Record<string, string> = {
  GB: "United Kingdom",
  UK: "United Kingdom",
  US: "United States",
  EU: "European Union",
  PT: "Portugal",
  CN: "China",
  IN: "India",
  DE: "Germany",
  EL: "Greece",
  FR: "France",
  CA: "Canada",
  AU: "Australia",
};

export function countryName(code: string): string {
  return NAMES[code.toUpperCase()] ?? code;
}

/** "UK" is what sellers say; the API uses ISO "GB". */
export function countryShort(code: string): string {
  return code.toUpperCase() === "GB" ? "UK" : countryName(code);
}

/** Origins the register prices for a US buyer (the seller can still type any other: it is then "not priced yet"). Sorted by name. */
export const PRICED_ORIGINS: string[] = ["GB", "US", "CN", "IN", "VN", "TR", "TH", "ID", "BD", "PK", "JP", "KR", "MX", "CA",
  "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"];

export const ORIGIN_CHOICES: { code: string; name: string }[] = [
  { code: "GB", name: "United Kingdom" },
  { code: "CN", name: "China" },
  { code: "IN", name: "India" },
  { code: "PT", name: "Portugal" },
  { code: "US", name: "United States" },
];
