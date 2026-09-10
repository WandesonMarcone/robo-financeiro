import type { InputHTMLAttributes } from "react";

export function Input({
  label,
  className = "",
  id,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  const inputId = id || props.name || label;
  return (
    <label className="block space-y-1.5" htmlFor={inputId}>
      <span className="text-[11px] uppercase tracking-[0.18em] text-olive/70">{label}</span>
      <input
        id={inputId}
        className={`w-full border border-olive/20 bg-white px-3 py-2 text-sm text-ink outline-none focus:border-gold ${className}`}
        {...props}
      />
    </label>
  );
}
