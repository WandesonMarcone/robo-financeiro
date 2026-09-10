import { describe, expect, it } from "vitest";
import { classifyValue, displayCount, displayField, sumPresent } from "./format";

describe("semantica de exibicao", () => {
  it("nunca converte ausencia em zero", () => {
    expect(classifyValue(null)).toBe("AUSENTE");
    expect(classifyValue(undefined)).toBe("AUSENTE");
    expect(displayField(null).text).toBe("AUSENTE");
    expect(displayField(null).kind).toBe("AUSENTE");
    expect(displayCount(null)).toEqual({ kind: "AUSENTE", text: "AUSENTE", raw: null });
  });

  it("preserva zero real", () => {
    expect(classifyValue(0)).toBe("ZERO");
    expect(displayCount(0)).toEqual({ kind: "ZERO", text: "0", raw: 0 });
    expect(displayField(0).kind).toBe("ZERO");
  });

  it("respeita semantica da API", () => {
    expect(classifyValue(1.2, { semantica: "INVALIDO" })).toBe("INVALIDO");
    expect(classifyValue(null, { semantica: "NAO_APLICAVEL" })).toBe("NAO_APLICAVEL");
    expect(classifyValue(10, { semantica: "PRESENTE" })).toBe("PRESENTE");
    expect(displayField(null, { semantica: "NAO_APLICAVEL" }).text).toBe("NAO_APLICAVEL");
  });

  it("soma somente valores presentes e nao inventa total", () => {
    expect(sumPresent([null, undefined])).toEqual({ total: null, used: 0, skipped: 2 });
    expect(sumPresent([10, null, 5])).toEqual({ total: 15, used: 2, skipped: 1 });
  });
});
