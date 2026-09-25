import { describe, expect, it } from "vitest";
import { normalizeStatusQuery, normalizeTextoQuery, normalizeTickerQuery, urlPdfValida } from "./documentos";

describe("contrato de pesquisa de documentos", () => {
  it("normaliza ticker para igualdade exata em maiusculas", () => {
    expect(normalizeTickerQuery(" hglg11 ")).toBe("HGLG11");
    expect(normalizeTickerQuery("PETR4")).toBe("PETR4");
    expect(normalizeTickerQuery("   ")).toBeUndefined();
  });

  it("repassa tipo_documento sem inventar catalogo", () => {
    expect(normalizeTextoQuery(" Relatorio Gerencial ")).toBe("Relatorio Gerencial");
    expect(normalizeTextoQuery("")).toBeUndefined();
  });

  it("normaliza status em maiusculas", () => {
    expect(normalizeStatusQuery("salvo")).toBe("SALVO");
    expect(normalizeStatusQuery("  ")).toBeUndefined();
  });
});

describe("url_pdf da API", () => {
  it("aceita somente URL http/https retornada pela API", () => {
    expect(urlPdfValida("https://drive.example/doc.pdf")).toBe("https://drive.example/doc.pdf");
    expect(urlPdfValida("http://fnet.example/x.pdf")).toBe("http://fnet.example/x.pdf");
    expect(urlPdfValida(null)).toBeNull();
    expect(urlPdfValida("")).toBeNull();
    expect(urlPdfValida("javascript:alert(1)")).toBeNull();
    expect(urlPdfValida("/documentos/interno.pdf")).toBeNull();
  });
});
