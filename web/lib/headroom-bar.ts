export interface HeadroomBar {
  state: "ok" | "breach" | "not-disclosed";
  breach: boolean;
  applicableLimit: number | null;
  fillPct: number;
}

/*
 * Headroom bar, defined once: the applicable limit is the waived limit
 * when one applies, otherwise the covenant limit. Headroom is
 * direction-aware (min: ratio minus limit; max: limit minus ratio), and
 * the fill is headroom as a share of the applicable limit, capped at
 * 100%. The bar is red only when the covenant actually breaches its
 * applicable limit.
 */
export function headroomBar(
  ratio: number | null | undefined,
  limit: number | null | undefined,
  direction: string | null | undefined,
  waivedLimit: number | null | undefined,
): HeadroomBar {
  const applicableLimit = waivedLimit ?? limit ?? null;
  if (
    ratio === null ||
    ratio === undefined ||
    applicableLimit === null ||
    applicableLimit === 0
  ) {
    return {
      state: "not-disclosed",
      breach: false,
      applicableLimit,
      fillPct: 0,
    };
  }
  const headroom =
    direction === "min" ? ratio - applicableLimit : applicableLimit - ratio;
  const breach = headroom < 0;
  return {
    state: breach ? "breach" : "ok",
    breach,
    applicableLimit,
    fillPct: Math.min(100, (Math.abs(headroom) / applicableLimit) * 100),
  };
}
