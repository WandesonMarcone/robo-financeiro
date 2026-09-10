import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "ghost" | "gold";

const styles: Record<Variant, string> = {
  primary:
    "bg-olive text-sand hover:bg-olive/90 border border-olive",
  ghost:
    "bg-transparent text-olive border border-olive/20 hover:border-gold hover:text-olive",
  gold:
    "bg-gold text-olive hover:bg-gold/90 border border-gold",
};

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={`inline-flex items-center justify-center px-4 py-2 text-sm font-medium tracking-wide transition disabled:opacity-50 ${styles[variant]} ${className}`}
      {...props}
    />
  );
}
