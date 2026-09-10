import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LogoSlot } from "./LogoSlot";

describe("LogoSlot", () => {
  it("expoe marca textual sem inventar logotipo", () => {
    render(<LogoSlot />);
    expect(screen.getByLabelText("Estrategia Fardada")).toBeInTheDocument();
    expect(screen.getByText("Estrategia Fardada")).toBeInTheDocument();
  });
});
